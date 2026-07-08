"""
Beacon Email Poller — Automatically checks Beacon's Gmail inbox
for DOB newsletters and other agency emails, then ingests them
into the Pinecone knowledge base.

Flow:
1. Polls Gmail every POLL_INTERVAL seconds (default: 1 hour)
2. Searches for unread emails matching configured sender filters
3. Extracts HTML body from each email
4. Passes to DOBNewsletterParser → DocumentProcessor → Pinecone
5. Marks processed emails as read and applies a "Beacon-Ingested" label
6. Feeds Content Intelligence engine for blog/newsletter generation

Authentication:
- Uses Google service account with domain-wide delegation
- Impersonates the Beacon email address to access its inbox
- Requires Gmail API scope: https://www.googleapis.com/auth/gmail.modify

Setup:
1. Add Gmail API scope to the service account in Google Workspace Admin
2. Set BEACON_EMAIL env var to the Beacon email address
3. Set EMAIL_POLL_INTERVAL (optional, default 3600 = 1 hour)
4. Set EMAIL_SENDER_FILTERS (optional, comma-separated sender patterns)
"""

import base64
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from google.oauth2 import service_account
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# How often to check for new emails (seconds)
POLL_INTERVAL = int(os.getenv("EMAIL_POLL_INTERVAL", "3600"))  # 1 hour default

# Beacon's email address (must be on Google Workspace domain)
BEACON_EMAIL = os.getenv("BEACON_EMAIL", "")

# Sender patterns to look for (comma-separated)
# Default: DOB Buildings News.
# NOTE: NYC.gov subscription newsletters (the "My NYC.gov News" digest, incl. the
# DOB "Buildings News Update") are actually sent from newsletters.nyc.gov — NOT
# buildings.nyc.gov — so that subdomain must be included or those emails are skipped.
DEFAULT_SENDERS = (
    "noreply@newsletters.nyc.gov,"
    "no-reply@newsletters.nyc.gov,"
    "noreply@buildings.nyc.gov,"
    "no-reply@buildings.nyc.gov,"
    "buildings@nyc.gov"
)
SENDER_FILTERS = os.getenv("EMAIL_SENDER_FILTERS", DEFAULT_SENDERS).split(",")

# Gmail API scopes needed for reading + labeling
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

# Label name for processed emails
INGESTED_LABEL = "Beacon-Ingested"


class EmailPoller:
    """Background poller that checks Beacon's Gmail for newsletters."""

    def __init__(self, retriever=None, content_engine=None, analytics_db=None):
        """
        Args:
            retriever: RAG Retriever instance (for ingesting into Pinecone)
            content_engine: ContentEngine instance (for content opportunities)
            analytics_db: Analytics DB for logging
        """
        self.retriever = retriever
        self.content_engine = content_engine
        self.analytics_db = analytics_db

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._credentials: Optional[service_account.Credentials] = None
        self._label_id: Optional[str] = None
        self._processed_count = 0
        self._last_poll: Optional[str] = None
        self._last_error: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(BEACON_EMAIL)

    def start(self):
        """Start the email poller background thread."""
        if not BEACON_EMAIL:
            logger.info("Email poller not configured (set BEACON_EMAIL)")
            return

        if self._running:
            logger.warning("Email poller already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="email-poller"
        )
        self._thread.start()
        logger.info(
            f"✅ Email poller started for {BEACON_EMAIL} "
            f"(interval={POLL_INTERVAL}s, senders={SENDER_FILTERS})"
        )

    def stop(self):
        """Stop the email poller."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Email poller stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _poll_loop(self):
        """Main polling loop."""
        # Initial delay — let the app fully start up
        time.sleep(30)

        while self._running:
            try:
                self._check_inbox()
                self._last_poll = datetime.now(timezone.utc).isoformat()
                self._last_error = None
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Email poller error: {e}", exc_info=True)

            # Sleep in small increments so we can stop quickly
            for _ in range(POLL_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def _check_inbox(self):
        """Check Gmail inbox for new newsletter emails."""
        import requests

        credentials = self._get_gmail_credentials()
        if not credentials:
            logger.warning("Email poller: could not get Gmail credentials")
            return

        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        }

        # Build search query for unread emails from configured senders
        sender_query = " OR ".join(f"from:{s.strip()}" for s in SENDER_FILTERS if s.strip())
        query = f"is:unread ({sender_query})"

        logger.info(f"Email poller: searching for: {query}")

        # List matching messages
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages"
        params = {"q": query, "maxResults": 10}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Gmail API list failed: {e}")
            return

        messages = data.get("messages", [])
        if not messages:
            logger.info("Email poller: no new newsletter emails found")
            return

        logger.info(f"Email poller: found {len(messages)} new emails to process")

        # Ensure we have the ingested label
        label_id = self._get_or_create_label(headers)

        for msg_ref in messages:
            msg_id = msg_ref["id"]
            try:
                self._process_email(msg_id, headers, label_id)
                self._processed_count += 1
            except Exception as e:
                logger.error(f"Failed to process email {msg_id}: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Gmail API helpers
    # ------------------------------------------------------------------

    def _get_gmail_credentials(self) -> Optional[service_account.Credentials]:
        """Get Gmail API credentials using service account with domain-wide delegation."""
        try:
            import json

            sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if sa_json:
                sa_info = json.loads(sa_json)
                credentials = service_account.Credentials.from_service_account_info(
                    sa_info, scopes=GMAIL_SCOPES
                )
            else:
                # Fallback: load from file (local dev)
                from pathlib import Path
                sa_path = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "google-chat-bot-key.json"))
                if not sa_path.exists():
                    logger.error(f"Service account file not found: {sa_path}")
                    return None
                credentials = service_account.Credentials.from_service_account_file(
                    str(sa_path), scopes=GMAIL_SCOPES
                )

            # Impersonate the Beacon email address
            delegated = credentials.with_subject(BEACON_EMAIL)
            delegated.refresh(Request())

            return delegated

        except Exception as e:
            logger.error(f"Gmail credentials error: {e}")
            return None

    def _process_email(self, msg_id: str, headers: dict, label_id: Optional[str]):
        """Process a single email — extract HTML, parse, ingest."""
        import requests

        # Get full message
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
        params = {"format": "full"}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        message = resp.json()

        # Extract subject
        subject = ""
        sender = ""
        for header in message.get("payload", {}).get("headers", []):
            if header["name"].lower() == "subject":
                subject = header["value"]
            if header["name"].lower() == "from":
                sender = header["value"]

        logger.info(f"Processing email: '{subject}' from {sender}")

        # Extract HTML body
        html_content = self._extract_html_body(message.get("payload", {}))

        if not html_content:
            logger.warning(f"No HTML content found in email: {subject}")
            # Mark as read anyway so we don't re-process
            self._mark_processed(msg_id, headers, label_id)
            return

        # Classify + route automatically (no manual triage):
        #   dob_regulatory → KB (Pinecone)   event / market_news → BD module
        # A forwarded real-estate news email ("Columbus Circle…") is BD intel, not DOB
        # knowledge — it should land in the BD module, not pollute the filing KB.
        try:
            from bs4 import BeautifulSoup
            text_for_class = BeautifulSoup(html_content, "html.parser").get_text(" ", strip=True)
        except Exception:
            text_for_class = ""
        category = self._classify_email(subject, sender, text_for_class)

        if category in ("event", "market_news"):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._route_to_bd(category, subject, sender, text_for_class, date_str):
                self._mark_processed(msg_id, headers, label_id)
                logger.info(f"✅ Email routed to BD ({category}): '{subject}'")
                return
            # Routing not configured / failed — fall through to KB so nothing is lost.
            logger.info(f"  BD routing unavailable; keeping '{subject}' in KB as fallback")

        # DOB regulatory (or fallback): parse and ingest the body (text + linked PDFs)
        self._ingest_newsletter(subject, sender, html_content)

        # Also ingest any PDF attachments directly on the email
        self._ingest_attachments(message, subject, headers)

        # Mark as read and label
        self._mark_processed(msg_id, headers, label_id)

        logger.info(f"✅ Email ingested: '{subject}'")

    def _ingest_attachments(self, message: dict, subject: str, headers: dict):
        """Download and ingest PDF attachments from the email.

        Some agency emails attach PDFs directly (e.g., bulletins, notices)
        instead of linking to them. This catches those.
        """
        import requests as req
        import tempfile
        from pathlib import Path
        from ingestion.document_processor import DocumentProcessor

        if not self.retriever:
            return

        payload = message.get("payload", {})
        msg_id = message.get("id", "")
        parts = payload.get("parts", [])

        for part in parts:
            filename = part.get("filename", "")
            mime_type = part.get("mimeType", "")

            # Only process PDF attachments
            if not filename.lower().endswith(".pdf") and "pdf" not in mime_type.lower():
                continue

            body = part.get("body", {})
            attachment_id = body.get("attachmentId")

            if not attachment_id:
                continue

            logger.info(f"  Downloading PDF attachment: {filename}")

            try:
                # Download attachment via Gmail API
                att_url = (
                    f"https://gmail.googleapis.com/gmail/v1/users/me"
                    f"/messages/{msg_id}/attachments/{attachment_id}"
                )
                resp = req.get(att_url, headers=headers, timeout=30)
                resp.raise_for_status()
                att_data = resp.json().get("data", "")

                if not att_data:
                    continue

                # Decode base64 attachment
                pdf_bytes = base64.urlsafe_b64decode(att_data)

                # Skip huge files
                if len(pdf_bytes) > 20 * 1024 * 1024:
                    logger.warning(f"  Attachment too large ({len(pdf_bytes)} bytes): {filename}")
                    continue

                # Save to temp file and process
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name

                try:
                    processor = DocumentProcessor()
                    document = processor.process_pdf(
                        file_path=tmp_path,
                        source_type="service_notice",
                        metadata={
                            "title": f"{subject} - {filename}",
                            "ingested_from": "email_attachment",
                            "email_subject": subject,
                            "attachment_filename": filename,
                            "jurisdiction": "NYC",
                        },
                    )
                    document.title = f"{subject} - {filename}"

                    count = self.retriever.vector_store.upsert_chunks(document.chunks)
                    self._processed_count += 1
                    logger.info(f"  ✅ Attachment ingested: '{filename}' → {count} chunks")

                finally:
                    try:
                        Path(tmp_path).unlink()
                    except OSError:
                        pass

            except Exception as e:
                logger.error(f"  Failed to ingest attachment '{filename}': {e}")

    def _extract_html_body(self, payload: dict) -> str:
        """Extract HTML body from Gmail message payload.

        Gmail messages can be structured in different ways:
        - Simple: payload.body has the content
        - Multipart: payload.parts contains the content parts
        """
        # Check if the payload itself has HTML
        if payload.get("mimeType") == "text/html":
            body_data = payload.get("body", {}).get("data", "")
            if body_data:
                return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

        # Check parts (multipart messages)
        parts = payload.get("parts", [])
        for part in parts:
            mime_type = part.get("mimeType", "")

            if mime_type == "text/html":
                body_data = part.get("body", {}).get("data", "")
                if body_data:
                    return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

            # Nested multipart (e.g., multipart/alternative inside multipart/mixed)
            if mime_type.startswith("multipart/"):
                nested = self._extract_html_body(part)
                if nested:
                    return nested

        # Fallback: try plain text
        for part in parts:
            if part.get("mimeType") == "text/plain":
                body_data = part.get("body", {}).get("data", "")
                if body_data:
                    text = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                    # Wrap plain text in basic HTML so the parser can handle it
                    return f"<html><body><pre>{text}</pre></body></html>"

        return ""

    def _ingest_newsletter(self, subject: str, sender: str, html_content: str):
        """Parse newsletter HTML and ingest into Pinecone KB.

        Full pipeline:
        1. Parse HTML → extract section updates with summaries
        2. Follow links → scrape page text + discover PDF links
        3. Download + ingest PDFs into Pinecone (the actual documents)
        4. Ingest text summaries as context
        5. Feed Content Intelligence engine
        """
        from content_engine.parser import DOBNewsletterParser
        from ingestion.document_processor import DocumentProcessor

        parser = DOBNewsletterParser()
        # Follow each story's primary link to pull the full article text (not just
        # the short newsletter blurb), so generation has real source material —
        # fewer confabulated fees/dates/code sections. _fetch_page_content is
        # bounded (10s timeout, 5000-char cap, fails soft) so a bad link can't
        # stall or crash ingestion.
        result = parser.parse_email(html_content, fetch_linked_pages=True)

        updates = result.get("updates", [])
        newsletter_date = result.get("newsletter_date", "unknown")

        if not updates:
            # The structured section-parser missed this email's format — common with
            # FORWARDED copies (Fwd: mangles the HTML it keys on) and changed newsletter
            # templates. Don't just ingest the summary text: the whole value of a DOB
            # newsletter is the documents it LINKS to. Harvest those links and follow
            # them to the actual bulletins/notices, then keep the summary as context.
            logger.info(f"No structured updates found in '{subject}' — harvesting links + raw fallback")
            harvested = self._harvest_and_ingest_links(html_content, subject, newsletter_date)
            self._ingest_raw_email(subject, sender, html_content, newsletter_date)
            if harvested:
                logger.info(f"  Followed {harvested} linked document(s) from '{subject}'")
            return

        logger.info(f"Parsed {len(updates)} updates from '{subject}' ({newsletter_date})")

        # Lazy-load the content engine. The poller is constructed with
        # content_engine=None (to avoid heavy init at app startup), and the
        # "lazy-load when needed" was never implemented — so newsletter stories were
        # ingested to the KB but NEVER turned into content candidates. Build it here.
        if self.content_engine is None:
            try:
                from content_engine.engine import ContentEngine
                self.content_engine = ContentEngine()
                logger.info("  Content engine lazy-loaded for candidate creation")
            except Exception as e:
                logger.warning(f"  Content engine unavailable, skipping candidates: {e}")

        # Preload existing pending candidate titles once, for dedup — so a
        # re-processed newsletter (e.g. after a redeploy) doesn't create duplicate
        # candidates. Mirrors the dedup already in /api/ingest-email (PR #41); the
        # poller creates candidates through its own path, which that fix did not cover.
        existing_titles = set()
        if self.content_engine:
            try:
                existing_titles = {
                    (c.title or "").strip().lower()
                    for c in self.content_engine.get_pending_candidates()
                }
            except Exception as e:
                logger.warning(f"  Candidate dedup preload failed: {e}")

        for update in updates:
            title = update.get("title", "Untitled Update")
            summary = update.get("summary", "")
            full_content = update.get("full_content", summary)
            category = update.get("category", "General")
            source_url = update.get("source_url", "")
            referenced_links = update.get("referenced_links", [])

            # Map category to source type
            category_to_type = {
                "Service Updates": "service_notice",
                "Local Laws": "policy_memo",
                "Buildings Bulletins": "technical_bulletin",
                "Hearings": "policy_memo",
                "Rules": "policy_memo",
                "Weather": "service_notice",
                "Code Notes": "building_code",
            }
            source_type = category_to_type.get(category, "service_notice")

            # --- 1) Ingest the text summary into Pinecone ---
            if self.retriever and full_content:
                try:
                    processor = DocumentProcessor()
                    md_content = f"""Title: {title}
Category: {category}
Date Issued: {newsletter_date}
Source: DOB Newsletter Email
Source URL: {source_url}
Type: {source_type}

# {title}

{full_content}
"""
                    document = processor.process_text(
                        text=md_content,
                        title=title,
                        source_type=source_type,
                        metadata={
                            "category": category,
                            "date_issued": newsletter_date,
                            "source_url": source_url,
                            "ingested_from": "email_poller",
                            "email_subject": subject,
                            "jurisdiction": "NYC",
                        },
                    )
                    count = self.retriever.vector_store.upsert_chunks(document.chunks)
                    logger.info(f"  Ingested text '{title}' → {count} chunks")

                except Exception as e:
                    logger.error(f"  Failed to ingest text '{title}': {e}")

            # --- 2) Download and ingest any referenced PDFs ---
            pdf_links = [link for link in referenced_links if link.lower().endswith(".pdf")]
            if pdf_links and self.retriever:
                for pdf_url in pdf_links:
                    try:
                        self._download_and_ingest_pdf(
                            pdf_url=pdf_url,
                            parent_title=title,
                            category=category,
                            newsletter_date=newsletter_date,
                            source_type=source_type,
                        )
                    except Exception as e:
                        logger.error(f"  Failed to ingest PDF {pdf_url}: {e}")

            # --- 3) Also check if the source_url itself is a PDF ---
            if source_url and source_url.lower().endswith(".pdf") and self.retriever:
                try:
                    self._download_and_ingest_pdf(
                        pdf_url=source_url,
                        parent_title=title,
                        category=category,
                        newsletter_date=newsletter_date,
                        source_type=source_type,
                    )
                except Exception as e:
                    logger.error(f"  Failed to ingest source PDF {source_url}: {e}")

            # --- 4) Feed Content Intelligence engine (dedup by title) ---
            if self.content_engine:
                norm_title = (title or "").strip().lower()
                if norm_title and norm_title in existing_titles:
                    logger.info(f"  Skipping duplicate candidate: '{title}'")
                else:
                    try:
                        candidate = self.content_engine.analyze_update(
                            title, summary or full_content[:500], source_url,
                            source_type="newsletter_email"
                        )
                        existing_titles.add(norm_title)
                        logger.info(f"  Content candidate: '{candidate.title}' ({candidate.priority})")
                    except Exception as e:
                        logger.error(f"  Content engine failed for '{title}': {e}")

    def _classify_email(self, subject: str, sender: str, text: str) -> str:
        """Classify an inbound email so it can be auto-routed. Returns one of:
        dob_regulatory | event | market_news | other. Defaults to dob_regulatory on
        any failure so we never silently drop regulatory content.
        """
        try:
            import anthropic
            from config import get_settings
            client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
            prompt = (
                "Classify this email into ONE category for a NYC permit-expediting firm.\n"
                "- dob_regulatory: official NYC DOB/FDNY/HPD/agency updates, bulletins, "
                "service notices, code or rule changes, filing-process changes\n"
                "- event: an industry event, conference, trade show, webinar, or meetup announcement\n"
                "- market_news: real-estate or construction market news, deals, transactions, "
                "leasing, or development announcements\n"
                "- other: anything else (low-value newsletter, personal, spam)\n\n"
                f"Sender: {sender}\nSubject: {subject}\nBody (first 1500 chars): {text[:1500]}\n\n"
                "Respond with ONLY the category word."
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            cat = msg.content[0].text.strip().lower()
            if cat in ("dob_regulatory", "event", "market_news", "other"):
                logger.info(f"Classified '{subject[:50]}' → {cat}")
                return cat
        except Exception as e:
            logger.warning(f"Email classify failed ('{subject[:40]}'), defaulting to dob_regulatory: {e}")
        return "dob_regulatory"

    def _route_to_bd(self, category: str, subject: str, sender: str, text: str, date: str) -> bool:
        """POST a classified BD signal (event / market_news) to Ordino so it lands in
        the BD module automatically — no manual triage. Uses the same shared-secret
        path as ordino_tools. Returns False if not configured or the POST fails (caller
        then falls back to KB so nothing is lost).
        """
        import requests
        supabase_url = os.getenv("SUPABASE_URL", "")
        beacon_key = os.getenv("BEACON_ANALYTICS_KEY", "")
        if not supabase_url or not beacon_key:
            return False
        try:
            resp = requests.post(
                f"{supabase_url}/functions/v1/bd-email-ingest",
                headers={"x-beacon-key": beacon_key, "Content-Type": "application/json"},
                json={
                    "signal_type": category,       # 'event' | 'market_news'
                    "title": subject,
                    "summary": text[:1000],
                    "sender": sender,
                    "date": date,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"  BD routing failed for '{subject}': {e}")
            return False

    def _harvest_and_ingest_links(self, html_content: str, subject: str, date: str) -> int:
        """Fallback when structured parsing fails: scan the email for links to the
        ACTUAL DOB documents (PDF bulletins/notices and buildings.nyc.gov pages) and
        ingest those, not just the summary. This is what makes 'read the newsletter'
        mean 'capture the documents it references'.
        """
        if not self.retriever:
            return 0
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception:
            return 0

        JUNK = ("unsubscribe", "twitter", "facebook", "linkedin", "instagram",
                "youtube", "/preferences", "subscriber", "googleapis", "mailto:",
                "list-manage", "campaign-archive")
        seen, pdf_links, page_links = set(), [], []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if not low.startswith("http") or href in seen or any(j in low for j in JUNK):
                continue
            seen.add(href)
            is_dob = ("buildings.nyc.gov" in low or "nyc.gov/site/buildings" in low
                      or "/assets/buildings/" in low or "nyc.gov/assets/buildings" in low)
            if low.split("?")[0].endswith(".pdf"):
                pdf_links.append(href)
            elif is_dob:
                page_links.append(href)

        count = 0
        # Follow direct PDF links — usually the bulletins/notices themselves.
        for url in pdf_links[:20]:
            try:
                self._download_and_ingest_pdf(
                    pdf_url=url, parent_title=subject, category="Newsletter Link",
                    newsletter_date=date, source_type="service_notice",
                )
                count += 1
            except Exception as e:
                logger.warning(f"  Link PDF ingest failed ({url}): {e}")

        # Follow DOB HTML pages — scrape their text and any PDFs they link to.
        if page_links:
            try:
                from content_engine.parser import DOBNewsletterParser
                from ingestion.document_processor import DocumentProcessor
                parser = DOBNewsletterParser()
                processor = DocumentProcessor()
            except Exception:
                return count
            for url in page_links[:15]:
                try:
                    content, links = parser._fetch_page_content(url)
                    if content and len(content) > 200:
                        document = processor.process_text(
                            text=content,
                            title=f"{subject} — {url.split('/')[-1] or 'linked page'}",
                            source_type="service_notice",
                            metadata={
                                "date_issued": date,
                                "source_url": url,
                                "ingested_from": "email_poller_link",
                                "parent_newsletter": subject,
                                "jurisdiction": "NYC",
                            },
                        )
                        self.retriever.vector_store.upsert_chunks(document.chunks)
                        count += 1
                    # PDFs discovered on the linked page
                    for nested in (links or []):
                        if nested.lower().split("?")[0].endswith(".pdf"):
                            try:
                                self._download_and_ingest_pdf(
                                    pdf_url=nested, parent_title=subject,
                                    category="Newsletter Link", newsletter_date=date,
                                    source_type="service_notice",
                                )
                                count += 1
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"  Link page ingest failed ({url}): {e}")
        return count

    def _ingest_raw_email(self, subject: str, sender: str, html_content: str, date: str):
        """Ingest a non-newsletter email as a raw document.

        For emails from agencies that aren't in DOB newsletter format
        (e.g., FDNY notices, HPD updates, ECB hearing notices).
        """
        if not self.retriever:
            return

        try:
            from bs4 import BeautifulSoup
            from ingestion.document_processor import DocumentProcessor

            # Extract text from HTML
            soup = BeautifulSoup(html_content, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()
            text_content = soup.get_text(separator="\n", strip=True)

            if len(text_content) < 50:
                logger.info(f"Email too short to ingest: '{subject}'")
                return

            processor = DocumentProcessor()
            md_content = f"""Title: {subject}
Source: Email from {sender}
Date: {date}
Type: email_digest

# {subject}

{text_content[:5000]}
"""
            # A forwarded/raw email is NOT an official DOB service notice — tag it
            # 'email_digest' so it can't masquerade as an authoritative notice in
            # retrieval (a real-estate news forward was previously ingested as a
            # 'service_notice' and polluted DOB answers).
            document = processor.process_text(
                text=md_content,
                title=subject,
                source_type="email_digest",
                metadata={
                    "date_issued": date,
                    "sender": sender,
                    "ingested_from": "email_poller",
                    "jurisdiction": "NYC",
                },
            )
            count = self.retriever.vector_store.upsert_chunks(document.chunks)
            logger.info(f"  Raw email ingested: '{subject}' → {count} chunks")

        except Exception as e:
            logger.error(f"  Failed to ingest raw email '{subject}': {e}")

    def _download_and_ingest_pdf(self, pdf_url: str, parent_title: str,
                                   category: str, newsletter_date: str,
                                   source_type: str):
        """Download a PDF from a URL and ingest it into Pinecone.

        This is the key piece — DOB newsletters link to actual PDFs
        (bulletins, service notices, code updates) that contain the
        real content Beacon needs to answer questions about.
        """
        import requests as req
        import tempfile
        from pathlib import Path
        from ingestion.document_processor import DocumentProcessor

        if not self.retriever:
            return

        logger.info(f"  Downloading PDF: {pdf_url}")

        try:
            # Download the PDF. nyc.gov returns 403 for the default requests
            # User-Agent, so send a browser UA (same as the parser's session).
            resp = req.get(
                pdf_url,
                timeout=30,
                stream=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            resp.raise_for_status()

            # Check it's actually a PDF
            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and not pdf_url.lower().endswith(".pdf"):
                logger.warning(f"  Not a PDF (content-type: {content_type}): {pdf_url}")
                return

            # Check file size — skip huge files (> 20MB)
            content_length = int(resp.headers.get("Content-Length", 0))
            if content_length > 20 * 1024 * 1024:
                logger.warning(f"  PDF too large ({content_length} bytes), skipping: {pdf_url}")
                return

            # Save to temp file
            # Save to a temp file whose basename is the REAL PDF filename, so the
            # doc's source_file becomes the notice's real name (e.g.
            # "permitrenewals_bizname-sn.pdf") instead of a random "tmpXXXX.pdf".
            # This makes docs identifiable AND makes re-ingesting the same PDF
            # idempotent (same source_file → manifest update, not a new duplicate).
            pdf_filename = pdf_url.split("/")[-1].split("?")[0] or "document.pdf"
            if not pdf_filename.lower().endswith(".pdf"):
                pdf_filename += ".pdf"
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", pdf_filename) or "document.pdf"
            tmp_dir = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, safe_name)
            with open(tmp_path, "wb") as tmp:
                for chunk in resp.iter_content(chunk_size=8192):
                    tmp.write(chunk)

            try:
                # Process the PDF
                processor = DocumentProcessor()
                document = processor.process_pdf(
                    file_path=tmp_path,
                    source_type=source_type,
                    metadata={
                        "title": f"{parent_title} - {pdf_filename}",
                        "category": category,
                        "date_issued": newsletter_date,
                        "source_url": pdf_url,
                        "ingested_from": "email_poller_pdf",
                        "parent_newsletter": parent_title,
                        "jurisdiction": "NYC",
                    },
                )

                # Override the title (process_pdf uses filename by default)
                document.title = f"{parent_title} - {pdf_filename}"

                # Upsert chunks into Pinecone
                count = self.retriever.vector_store.upsert_chunks(document.chunks)
                self._processed_count += 1
                logger.info(f"  ✅ PDF ingested: '{pdf_filename}' → {count} chunks "
                            f"({document.metadata.get('page_count', '?')} pages)")

            finally:
                # Clean up temp file + its dir
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
                try:
                    os.rmdir(os.path.dirname(tmp_path))
                except OSError:
                    pass

        except req.exceptions.Timeout:
            logger.warning(f"  PDF download timed out: {pdf_url}")
        except req.exceptions.HTTPError as e:
            logger.warning(f"  PDF download HTTP error ({e.response.status_code}): {pdf_url}")
        except Exception as e:
            logger.error(f"  PDF ingestion failed for {pdf_url}: {e}", exc_info=True)

    def _mark_processed(self, msg_id: str, headers: dict, label_id: Optional[str]):
        """Mark an email as read and apply the ingested label."""
        import requests

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/modify"
        body = {
            "removeLabelIds": ["UNREAD"],
        }
        if label_id:
            body["addLabelIds"] = [label_id]

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to mark email {msg_id} as processed: {e}")

    def _get_or_create_label(self, headers: dict) -> Optional[str]:
        """Get or create the 'Beacon-Ingested' label."""
        if self._label_id:
            return self._label_id

        import requests

        # List existing labels
        url = "https://gmail.googleapis.com/gmail/v1/users/me/labels"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            labels = resp.json().get("labels", [])

            for label in labels:
                if label.get("name") == INGESTED_LABEL:
                    self._label_id = label["id"]
                    return self._label_id

            # Create the label
            create_url = url
            body = {
                "name": INGESTED_LABEL,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
            resp = requests.post(create_url, headers=headers, json=body, timeout=10)
            resp.raise_for_status()
            self._label_id = resp.json().get("id")
            logger.info(f"Created Gmail label: {INGESTED_LABEL}")
            return self._label_id

        except Exception as e:
            logger.warning(f"Could not get/create Gmail label: {e}")
            return None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Get current status of the email poller."""
        return {
            "running": self._running,
            "email": BEACON_EMAIL,
            "sender_filters": SENDER_FILTERS,
            "poll_interval_seconds": POLL_INTERVAL,
            "last_poll": self._last_poll,
            "last_error": self._last_error,
            "emails_processed": self._processed_count,
        }
