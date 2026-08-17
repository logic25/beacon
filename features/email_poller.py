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
from datetime import datetime, timedelta, timezone
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
# EMAIL_SENDER_FILTERS AUGMENTS the defaults (union), it does NOT replace them. This is
# deliberate: the env var previously overrode DEFAULT_SENDERS entirely, so a single typo
# there (e.g. "no-noreply@newsletters.nyc.gov") silently dropped the real DOB sender
# noreply@newsletters.nyc.gov and every "Buildings News Update" went un-ingested. Union +
# de-dup means a bad env entry is harmless noise and a core DOB sender can never be lost.
_env_senders = os.getenv("EMAIL_SENDER_FILTERS", "")
SENDER_FILTERS = list(dict.fromkeys(
    s.strip() for s in f"{DEFAULT_SENDERS},{_env_senders}".split(",") if s.strip()
))

# "Forward-to-teach": emails GLE staff FORWARD to beacon@ (from the company domain) are
# ingested as general KB docs — body text + PDF attachments — regardless of the DOB
# newsletter format. This is the "I forward it and Beacon learns it" path Manny/Chris
# asked for. Restricted to the company domain(s) so random inbound to beacon@ (spam,
# lists) can never poison the KB — only a trusted staffer's forward teaches Beacon.
TRUSTED_FORWARD_DOMAINS = list(dict.fromkeys(
    d.strip().lower() for d in os.getenv(
        "BEACON_TRUSTED_FORWARD_DOMAINS", "greenlightexpediting.com"
    ).split(",") if d.strip()
))

# BD / market-intel newsletters. beacon@ can subscribe DIRECTLY to these; the poller
# fetches them and the classifier routes them to the BD module (market_news / event) —
# NOT the permitting KB. So Manny can unsubscribe personally and let Beacon aggregate.
# Augmentable via EMAIL_BD_SENDERS (union, same pattern as EMAIL_SENDER_FILTERS).
DEFAULT_BD_SENDERS = (
    "bisnow.com,commercialobserver.com,credaily.com,therealdeal.com,"
    "pincusco.com,crainsnewyork.com"
)
_env_bd = os.getenv("EMAIL_BD_SENDERS", "")
BD_SENDERS = list(dict.fromkeys(
    s.strip() for s in f"{DEFAULT_BD_SENDERS},{_env_bd}".split(",") if s.strip()
))

# Gmail API scopes needed for reading + labeling
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

# Nested Beacon/* label tree — the beacon@ inbox becomes a pipeline dashboard you can
# eyeball. Gmail nests on "/". An email can carry MORE than one (a DOB newsletter that
# both lands in the KB and spawns a content candidate = Beacon/KB + Beacon/Content).
# Watch two: a pile-up in Beacon/Failed = something's breaking; Beacon/Content going
# quiet = the content engine stalled (this label alone would have flagged the 29d outage).
INGESTED_LABEL = "Beacon/KB"            # ingested into the knowledge base
FAILED_LABEL = "Beacon/Failed"         # threw during ingest — surfaces for review (the alarm)
BD_LABEL = "Beacon/BD"                  # parent; Signal/Event children carry the real routing
BD_SIGNAL_LABEL = "Beacon/BD/Signal"   # routed to BD as market news (Bisnow/CO/TRD)
BD_EVENT_LABEL = "Beacon/BD/Event"     # routed to BD as an industry event
CONTENT_LABEL = "Beacon/Content"       # produced a content candidate (fed the content engine)
SKIPPED_LABEL = "Beacon/Skipped"       # deliberately dropped as low-value ('other')
TAUGHT_LABEL = "Beacon/Taught"         # internal staff forward Beacon learned from (teach path)
BACKFILLED_LABEL = "Beacon/Backfilled"  # audit-only: re-processed by the one-time content backfill


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
        self._label_ids: dict = {}  # label name -> id (cached across polls)
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

        # Build search query for unread emails from configured senders. BD newsletters are
        # fetched here too — the classifier routes them to the BD module, not the KB, so
        # beacon@ can subscribe to Bisnow/CO/CRE Daily/etc. and they auto-file as BD intel.
        all_senders = list(dict.fromkeys(SENDER_FILTERS + BD_SENDERS))
        sender_query = " OR ".join(f"from:{s.strip()}" for s in all_senders if s.strip())
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
        else:
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

        # Second pass: internal forwards (GLE staff teaching Beacon what they email in).
        self._check_forwarded(headers)

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

        # A trusted staffer's forward always gets the general "teach" path (body + attachments
        # + link crawl), even though their address is also in the main sender filter (manny@ is
        # in EMAIL_SENDER_FILTERS) — otherwise the newsletter parser grabs it here and drops the
        # body text. This must run before the newsletter path below.
        sender_l = sender.lower()
        if any(f"@{d}" in sender_l or sender_l.endswith(d) for d in TRUSTED_FORWARD_DOMAINS):
            taught_label = self._get_or_create_label(headers, TAUGHT_LABEL)
            self._handle_forward(msg_id, message, subject, sender, headers, taught_label)
            return

        # Extract HTML body
        html_content = self._extract_html_body(message.get("payload", {}))

        if not html_content:
            logger.warning(f"No HTML content found in email: {subject}")
            # Mark as read anyway so we don't re-process. Nothing was ingested, so it's
            # Skipped, not KB — keep the dashboard honest.
            self._mark_processed(msg_id, headers, self._labels(headers, SKIPPED_LABEL))
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

        # Official DOB / nyc.gov agency newsletters are KNOWLEDGE — force them to the KB even
        # if the classifier saw event-ish content (e.g. a "Buildings News Update" digest that
        # mentions "DOB in Your Community" events) OR dismissed it as low-value 'other'. Haiku
        # sometimes mislabels a Buildings News Update digest as 'other'; the 'other' skip below
        # was then silently dropping it — which flat-lined the content engine for ~29 days.
        # Only the BD-sender feed (Bisnow etc.) and staff forwards are BD-eligible; official DOB
        # mail must never route to the BD module NOR be dropped on a misclassification.
        if "nyc.gov" in sender_l and category in ("event", "market_news", "other"):
            logger.info(f"  Forcing nyc.gov newsletter to KB (classifier said {category}): '{subject}'")
            category = "dob_regulatory"

        # 'other' = promos, personal mail, low-value newsletters. Skip entirely so they
        # never land in the permitting KB. (dob_regulatory still defaults to the KB below.)
        if category == "other":
            self._mark_processed(msg_id, headers, self._labels(headers, SKIPPED_LABEL))
            logger.info(f"⏭️  Skipped (other/low-value): '{subject}'")
            return

        if category in ("event", "market_news"):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._route_to_bd(category, subject, sender, text_for_class, date_str):
                bd_label = self._get_or_create_label(
                    headers, BD_SIGNAL_LABEL if category == "market_news" else BD_EVENT_LABEL)
                self._mark_processed(msg_id, headers, bd_label)
                logger.info(f"✅ Email routed to BD ({category}): '{subject}'")
                return
            # Routing not configured / failed — fall through to KB so nothing is lost.
            logger.info(f"  BD routing unavailable; keeping '{subject}' in KB as fallback")

        # DOB regulatory (or fallback): parse and ingest the body (text + linked PDFs).
        # Wrap the whole ingest so a single email that throws can NEVER get stranded in a
        # silent retry loop: on failure we still mark it processed, but with a distinct
        # 'Beacon-Ingest-Failed' label so it surfaces for review instead of re-failing
        # every poll forever.
        try:
            candidates_made = self._ingest_newsletter(subject, sender, html_content)
            # Also ingest any PDF attachments directly on the email
            self._ingest_attachments(message, subject, headers)
        except Exception as e:
            self._last_error = f"ingest failed for '{subject}': {e}"
            logger.error(f"❌ Ingest failed for '{subject}', marking failed: {e}", exc_info=True)
            failed_label = self._get_or_create_label(headers, FAILED_LABEL)
            self._mark_processed(msg_id, headers, failed_label)
            return

        # Notify GLE staff in Ordino that new KB content landed — once per email
        # (never per chunk), so the notification bell stays low-noise.
        if self.analytics_db:
            try:
                self.analytics_db.notify_ingest(
                    title=f"KB updated: {subject}",
                    body=f"Beacon ingested a DOB/regulatory email from {sender}.",
                    link="/documents",
                )
            except Exception as e:
                logger.warning(f"KB ingest notify failed for '{subject}': {e}")

        # Mark as read and label: Beacon/KB always, + Beacon/Content if this newsletter
        # actually spawned a content candidate (so "Content went quiet" is a real signal).
        kb_names = [INGESTED_LABEL] + ([CONTENT_LABEL] if candidates_made else [])
        self._mark_processed(msg_id, headers, self._labels(headers, *kb_names))

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

                # Save to a temp file NAMED with the real attachment filename so the
                # source_file Beacon cites is meaningful (not tmpXXXX.pdf). Sanitize to
                # a safe basename and keep the .pdf suffix.
                import re as _re
                safe_name = _re.sub(r"[^A-Za-z0-9._ +-]", "_", os.path.basename(filename)).strip() or "attachment.pdf"
                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"
                tmp_dir = tempfile.mkdtemp()
                tmp_path = os.path.join(tmp_dir, safe_name)
                with open(tmp_path, "wb") as _fh:
                    _fh.write(pdf_bytes)

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
                        p = Path(tmp_path)
                        p.unlink(missing_ok=True)
                        p.parent.rmdir()  # remove the now-empty per-attachment temp dir
                    except OSError:
                        pass

            except Exception as e:
                logger.error(f"  Failed to ingest attachment '{filename}': {e}")

    # ------------------------------------------------------------------
    # Forward-to-teach: GLE staff forward any email to beacon@ → KB
    # ------------------------------------------------------------------

    def _check_forwarded(self, headers: dict):
        """Second inbox pass: emails FORWARDED by GLE staff to beacon@.

        Anything a trusted staffer forwards in is treated as "teach Beacon this" —
        we ingest the body text + PDF attachments as a general KB doc, no DOB-newsletter
        format required. Restricted to TRUSTED_FORWARD_DOMAINS so only staff can teach.
        """
        import requests
        if not TRUSTED_FORWARD_DOMAINS:
            return

        # from:(domain) catches forwards INTO beacon@; exclude beacon's own address so a
        # notification/self-copy can never loop back in.
        dom_query = " OR ".join(f"from:{d}" for d in TRUSTED_FORWARD_DOMAINS)
        query = f"is:unread ({dom_query})"
        if BEACON_EMAIL:
            query += f" -from:{BEACON_EMAIL}"

        logger.info(f"Email poller (forwards): searching for: {query}")
        try:
            # Higher cap than the newsletter pass: when staff bulk-backfill by marking a
            # stack of old forwards unread, we want to clear them in a cycle or two, not
            # 10/hour. Configurable via BEACON_FORWARD_BATCH.
            batch = int(os.getenv("BEACON_FORWARD_BATCH", "25"))
            resp = requests.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers, params={"q": query, "maxResults": batch}, timeout=30,
            )
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
        except Exception as e:
            logger.error(f"Gmail forward-list failed: {e}")
            return

        if not messages:
            logger.info("Email poller (forwards): none found")
            return

        logger.info(f"Email poller (forwards): {len(messages)} to process")
        taught_label = self._get_or_create_label(headers, TAUGHT_LABEL)
        for msg_ref in messages:
            try:
                self._process_forwarded_email(msg_ref["id"], headers, taught_label)
                self._processed_count += 1
            except Exception as e:
                logger.error(f"Failed to process forward {msg_ref['id']}: {e}", exc_info=True)

    def _process_forwarded_email(self, msg_id: str, headers: dict, taught_label: Optional[str]):
        """Ingest a staff-forwarded email as a general KB doc (body + attachments)."""
        import requests
        resp = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
            headers=headers, params={"format": "full"}, timeout=30,
        )
        resp.raise_for_status()
        message = resp.json()

        subject, sender = "", ""
        for h in message.get("payload", {}).get("headers", []):
            if h["name"].lower() == "subject": subject = h["value"]
            if h["name"].lower() == "from": sender = h["value"]

        # Defense-in-depth: re-verify the sender domain (search filter is not enough on
        # its own — a spoofed display name shouldn't be able to teach the KB).
        sender_l = sender.lower()
        if not any(f"@{d}" in sender_l or sender_l.endswith(d) for d in TRUSTED_FORWARD_DOMAINS):
            logger.warning(f"Forward from untrusted sender, skipping: {sender}")
            self._mark_processed(msg_id, headers, taught_label)
            return

        self._handle_forward(msg_id, message, subject, sender, headers, taught_label)

    def _handle_forward(self, msg_id: str, message: dict, subject: str, sender: str,
                        headers: dict, taught_label: Optional[str]):
        """Ingest a forwarded email as a general KB doc (body + attachments + nyc.gov links).

        Shared by the forward pass AND the main pass: because a trusted staffer's address can
        also be in the main sender filter (e.g. manny@ is in EMAIL_SENDER_FILTERS), the main
        pass would otherwise grab the forward first and run the DOB-newsletter parser on it,
        dropping the body text. Routing all staff forwards here guarantees the full treatment.
        """
        logger.info(f"Processing forward: '{subject}' from {sender}")

        html_content = self._extract_html_body(message.get("payload", {}))
        try:
            from bs4 import BeautifulSoup
            text_for_class = BeautifulSoup(html_content or "", "html.parser").get_text(" ", strip=True)
        except Exception:
            text_for_class = ""

        # A forwarded event / market-news item is BD intel, not permitting knowledge —
        # route it to the BD module, same as the primary path. Everything else the staffer
        # forwarded is treated as teach-the-KB intent (we do NOT drop 'other' here: unlike
        # nyc.gov mail, a human deliberately sent this in).
        category = self._classify_email(subject, sender, text_for_class)
        if category in ("event", "market_news"):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._route_to_bd(category, subject, sender, text_for_class, date_str):
                bd_label = self._get_or_create_label(
                    headers, BD_SIGNAL_LABEL if category == "market_news" else BD_EVENT_LABEL)
                self._mark_processed(msg_id, headers, bd_label)
                logger.info(f"✅ Forward routed to BD ({category}): '{subject}'")
                return

        ingested_any = False
        try:
            if self._ingest_forwarded_text(subject, sender, text_for_class, category):
                ingested_any = True
            # PDF attachments (bulletins, notices, rule PDFs) — the common case for forwards.
            before = self._processed_count
            self._ingest_attachments(message, subject, headers)
            if self._processed_count > before:
                ingested_any = True
            # Crawl any nyc.gov links in the forward too (e.g. Manny forwarding a DOB
            # newsletter → follow its links, same as the direct newsletter path).
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content or "", "html.parser")
                seen_l = set()
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "nyc.gov" not in href.lower() or href.lower().endswith(".pdf"):
                        continue
                    if href in seen_l:
                        continue
                    seen_l.add(href)
                    if len(seen_l) > 4:
                        break
                    self._crawl_and_ingest_page(
                        href, subject, category,
                        datetime.now(timezone.utc).strftime("%Y-%m-%d"), "service_notice")
                    ingested_any = True
            except Exception as e:
                logger.warning(f"  forward link-crawl failed: {e}")
        except Exception as e:
            self._last_error = f"forward ingest failed for '{subject}': {e}"
            logger.error(f"❌ Forward ingest failed for '{subject}': {e}", exc_info=True)
            failed_label = self._get_or_create_label(headers, FAILED_LABEL)
            self._mark_processed(msg_id, headers, failed_label)
            return

        if ingested_any and self.analytics_db:
            try:
                self.analytics_db.notify_ingest(
                    title=f"KB updated: {subject}",
                    body=f"Beacon learned a forwarded email from {sender}.",
                    link="/documents",
                )
            except Exception as e:
                logger.warning(f"KB ingest notify failed for '{subject}': {e}")

        self._mark_processed(msg_id, headers, taught_label)
        logger.info(f"✅ Forward learned: '{subject}' (body={ingested_any})")

    def _ingest_forwarded_text(self, subject: str, sender: str, text: str, category: str) -> bool:
        """Ingest a forwarded email's body text as a general KB doc. Returns True if ingested."""
        if not self.retriever:
            return False
        # Skip thin bodies — a bare "FYI" forward with only a PDF attachment shouldn't create
        # an empty text doc (the attachment path handles the substance).
        if not text or len(text.strip()) < 200:
            return False
        from ingestion.document_processor import DocumentProcessor
        # Clean subject → a meaningful KB title (drop Fwd:/Re: prefixes).
        title = re.sub(r"^(?:\s*(?:fwd?|re|fw)\s*:\s*)+", "", subject, flags=re.I).strip() or "Forwarded Email"
        source_type = "service_notice" if category == "dob_regulatory" else "reference"
        processor = DocumentProcessor()
        document = processor.process_text(
            text=text,
            title=title,
            source_type=source_type,
            metadata={
                "title": title,
                "ingested_from": "staff_forward",
                "forwarded_by": sender,
                "category": category,
                "jurisdiction": "NYC",
            },
        )
        count = self.retriever.vector_store.upsert_chunks(document.chunks)
        logger.info(f"  ✅ Forward body ingested: '{title}' → {count} chunks")
        return count > 0

    def _crawl_and_ingest_page(self, url: str, parent_title: str, category: str,
                               newsletter_date: str, source_type: str):
        """Fetch a linked HTML page (nyc.gov only) and ingest its text into the KB.

        This is how linked newsletter content actually gets learned — the email body only
        carries a blurb + a link. Restricted to official nyc.gov hosts (SSRF-guarded via
        net_guard) so we never follow tracking/ad/third-party links embedded in the email.
        """
        if not self.retriever or not url:
            return
        u = url.strip()
        if not u.lower().startswith("http") or u.lower().endswith(".pdf"):
            return
        from urllib.parse import urlparse
        host = (urlparse(u).hostname or "").lower()
        if not (host == "nyc.gov" or host.endswith(".nyc.gov")):
            return  # only crawl official NYC pages
        try:
            from core import net_guard
            resp = net_guard.safe_get(u, timeout=15, headers={"User-Agent": "BeaconKB/1.0"})
            ctype = resp.headers.get("content-type", "").lower()
            if resp.status_code != 200 or "html" not in ctype:
                return
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
                tag.decompose()
            page_title = (soup.title.get_text(strip=True) if soup.title else "") or parent_title
            text = soup.get_text(" ", strip=True)
            if len(text) < 300:  # thin/redirect/landing page — nothing to learn
                return
            from ingestion.document_processor import DocumentProcessor
            title = f"{parent_title} — {page_title}"[:120]
            document = DocumentProcessor().process_text(
                text=text, title=title, source_type=source_type,
                metadata={"category": category, "date_issued": newsletter_date,
                          "source_url": u, "ingested_from": "newsletter_link_crawl",
                          "jurisdiction": "NYC"},
            )
            count = self.retriever.vector_store.upsert_chunks(document.chunks)
            logger.info(f"  ✅ Crawled linked page '{page_title[:50]}' → {count} chunks")
        except Exception as e:
            logger.warning(f"  Skipped/failed crawl {u}: {e}")

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
        # Forwarded copies (especially from Gmail mobile) wrap the newsletter in a
        # gmail_quote container and prepend a "Forwarded message" attribution block,
        # hiding the font-size section headings the parser keys on. Pre-clean to the
        # original newsletter body first; no-op for non-forwarded mail, so the working
        # path stays untouched.
        clean_html = self._preclean_forwarded_html(html_content)
        try:
            result = parser.parse_email(clean_html, fetch_linked_pages=True)
        except Exception as e:
            # The structured parser crashed on this email's markup (heavy DOB NOW
            # newsletters have exercised edge cases the simple recaps don't). Never let
            # that lose the whole email — fall back to harvesting its linked documents
            # plus the raw text, exactly like the no-updates path below, AND still
            # create a content candidate so a DOB newsletter always reaches the content
            # pipeline, not only the KB.
            logger.error(f"Newsletter parser crashed on '{subject}', using harvest+raw fallback: {e}")
            harvested_texts: list = []
            harvested = self._harvest_and_ingest_links(
                html_content, subject, "unknown", collect_texts=harvested_texts)
            self._ingest_raw_email(subject, sender, html_content, "unknown")
            if harvested:
                logger.info(f"  Followed {harvested} linked document(s) from '{subject}' (fallback)")
            summary_text = "\n\n".join(t for t in harvested_texts if t).strip() \
                or self._email_text(html_content)
            return self._create_fallback_candidate(subject, summary_text)

        updates = result.get("updates", [])
        newsletter_date = result.get("newsletter_date", "unknown")

        if not updates:
            # The structured section-parser missed this email's format — common with
            # FORWARDED copies (Fwd: mangles the HTML it keys on) and changed newsletter
            # templates. Don't just ingest the summary text: the whole value of a DOB
            # newsletter is the documents it LINKS to. Harvest those links and follow
            # them to the actual bulletins/notices, keep the summary as context, AND
            # (the fix) still create a content candidate — a DOB newsletter must reach
            # the content pipeline regardless of HTML format, not only the KB. This is
            # exactly the step that silently stopped ~2026-07-08 (return 0 here ingested
            # to the KB but produced no Beacon/Content candidate).
            logger.info(f"No structured updates found in '{subject}' — harvesting links + raw + candidate fallback")
            harvested_texts: list = []
            harvested = self._harvest_and_ingest_links(
                html_content, subject, newsletter_date, collect_texts=harvested_texts)
            self._ingest_raw_email(subject, sender, html_content, newsletter_date)
            if harvested:
                logger.info(f"  Followed {harvested} linked document(s) from '{subject}'")
            # Best available text: the followed article text if we captured any, else
            # the raw email text stripped of HTML.
            summary_text = "\n\n".join(t for t in harvested_texts if t).strip() \
                or self._email_text(html_content)
            return self._create_fallback_candidate(subject, summary_text)

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

        candidates_made = 0
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

            # --- 3b) Crawl linked nyc.gov HTML pages — the ACTUAL content behind the blurb.
            # The email body only carries a summary + a link (e.g. the EBC newsletter points
            # to training pages/FAQs); without this the linked substance is never learned.
            if self.retriever:
                crawl_urls = []
                if source_url and not source_url.lower().endswith(".pdf"):
                    crawl_urls.append(source_url)
                crawl_urls += [l for l in referenced_links if l and not l.lower().endswith(".pdf")]
                seen_u = set()
                for cu in crawl_urls:
                    if cu in seen_u:
                        continue
                    seen_u.add(cu)
                    if len(seen_u) > 4:  # cap per update — avoid crawling every tracking link
                        break
                    try:
                        self._crawl_and_ingest_page(cu, title, category, newsletter_date, source_type)
                    except Exception as e:
                        logger.error(f"  crawl failed {cu}: {e}")

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
                        candidates_made += 1
                        logger.info(f"  Content candidate: '{candidate.title}' ({candidate.priority})")
                    except Exception as e:
                        logger.error(f"  Content engine failed for '{title}': {e}")

        return candidates_made

    # ------------------------------------------------------------------
    # Format-resilient fallback helpers (forwarded / re-templated newsletters)
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_fwd(subject: str) -> str:
        """Strip leading Fwd:/Fw:/Re: boilerplate a forward accumulates, so the
        content candidate gets the real newsletter subject as its title."""
        s = (subject or "").strip()
        while True:
            m = re.match(r"^\s*(fwd?|fw|re)\s*:\s*", s, re.I)
            if not m:
                break
            s = s[m.end():]
        return s.strip()

    def _preclean_forwarded_html(self, html_content: str) -> str:
        """Unwrap Gmail's forwarded-message wrapper so the structured newsletter
        parser sees the ORIGINAL newsletter markup.

        Forwarding a DOB newsletter (especially from Gmail mobile) nests the original
        inside a <div class="gmail_quote"> and prepends a "---------- Forwarded
        message ----------" attribution block (div.gmail_attr). Both add noise the
        section-parser keys off (font-size headings, the date line), so it extracts
        zero structured updates and the email only reaches the KB, never the content
        pipeline. Unwrap to the forwarded body.

        No-op (returns the input unchanged) when there is no Gmail forward wrapper, so
        the working non-forwarded path is untouched.
        """
        if not html_content:
            return html_content
        if "gmail_quote" not in html_content and "Forwarded message" not in html_content:
            return html_content
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            # Drop the "---------- Forwarded message ----------" attribution header(s).
            for attr in soup.select("div.gmail_attr, .gmail_attr"):
                attr.decompose()
            # Promote the forwarded body: the original newsletter lives inside the
            # gmail_quote container.
            quote = soup.select_one("div.gmail_quote, blockquote.gmail_quote")
            if quote is not None:
                inner = quote.decode_contents()
                if inner and len(inner) > 200:
                    return inner
            return str(soup)
        except Exception as e:
            logger.warning(f"Forwarded-HTML pre-clean failed, using original: {e}")
            return html_content

    def _email_text(self, html_content: str) -> str:
        """Raw email text stripped of HTML — the last-resort source text for a
        fallback content candidate when no linked article text was captured."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content or "", "html.parser")
            for t in soup(["script", "style"]):
                t.decompose()
            return soup.get_text(separator="\n", strip=True)
        except Exception:
            return ""

    def _create_fallback_candidate(self, subject: str, text: str,
                                   source_url: str = "") -> int:
        """Create a content candidate from a newsletter the structured parser couldn't
        break into sections (forwarded copies, changed DOB templates).

        This is the core of the fix: a DOB/nyc.gov newsletter must ALWAYS yield at
        least one content candidate regardless of HTML format. Deduped by title so a
        re-processed email doesn't duplicate. Returns candidates created (0 or 1).
        """
        # Lazy-load the content engine (the poller is constructed with
        # content_engine=None to avoid heavy init at startup), mirroring the
        # structured path.
        if self.content_engine is None:
            try:
                from content_engine.engine import ContentEngine
                self.content_engine = ContentEngine()
                logger.info("  Content engine lazy-loaded for fallback candidate creation")
            except Exception as e:
                logger.warning(f"  Content engine unavailable, skipping fallback candidate: {e}")
                return 0
        if not self.content_engine:
            return 0

        title = self._strip_fwd(subject) or "DOB Newsletter Update"
        summary = (text or "").strip()
        if len(summary) < 40:
            # Nothing substantive to analyze — don't manufacture an empty candidate.
            logger.info(f"  Fallback candidate skipped (insufficient text) for '{subject}'")
            return 0

        # Title dedup against existing pending candidates (mirrors the structured path,
        # so re-processing after a redeploy doesn't create duplicates).
        try:
            existing_titles = {
                (c.title or "").strip().lower()
                for c in self.content_engine.get_pending_candidates()
            }
        except Exception as e:
            logger.warning(f"  Fallback dedup preload failed: {e}")
            existing_titles = set()
        if title.strip().lower() in existing_titles:
            logger.info(f"  Skipping duplicate fallback candidate: '{title}'")
            return 0

        try:
            candidate = self.content_engine.analyze_update(
                title, summary[:2000], source_url, source_type="newsletter_email"
            )
            logger.info(f"  Fallback content candidate: '{candidate.title}' ({candidate.priority})")
            return 1
        except Exception as e:
            logger.error(f"  Fallback content engine failed for '{subject}': {e}")
            return 0

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

    def _is_official_dob_source(self, text: str, raw_html: str = "") -> bool:
        """Conservative test: does this email clearly ORIGINATE from an official NYC DOB /
        nyc.gov source? Used ONLY by the content backfill to rescue genuine DOB newsletters
        that arrive FORWARDED (sender=manny@), where the live nyc.gov sender-force can't see
        the real source. Deliberately narrow: it keys on a distinctive SOURCE signal — the
        official nyc.gov newsletter sender domain or the "Buildings News Update" masthead —
        NOT a mere mention of "DOB"/"Department of Buildings" (a Bisnow market-news forward
        that names the agency must NOT qualify). Checks the raw (pre-clean) HTML too, so the
        forwarded "From: … <noreply@newsletters.nyc.gov>" attribution line still counts even
        after _preclean_forwarded_html strips it out of the classifier text.
        """
        blob = f"{text or ''} {raw_html or ''}".lower()
        strong = (
            "newsletters.nyc.gov",   # official DOB newsletter sender domain
            "buildings.nyc.gov",     # DOB official sender domain
            "buildings@nyc.gov",     # DOB official sender address
            "buildings news update",  # the DOB email-newsletter masthead
        )
        return any(s in blob for s in strong)

    @staticmethod
    def _strip_fwd(s: str) -> str:
        return re.sub(r"^(?:\s*(?:fwd?|re|fw)\s*:\s*)+", "", s or "", flags=re.I).strip()

    def _extract_event_fields(self, subject: str, text: str) -> dict:
        """LLM-extract clean event details from a (usually forwarded) email so BD events
        aren't named 'Fwd: ...' with no date/venue. Returns
        {is_event, name, date, location, host, url}. is_event=False means this is NOT a
        single concrete event (a newsletter digest, market report, bundle) → the caller
        downgrades it to market_news instead of creating a junk event row.
        """
        import json as _json
        default = {"is_event": True, "name": self._strip_fwd(subject),
                   "date": None, "location": None, "host": None, "url": None}
        try:
            import anthropic
            from config import get_settings
            client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
            prompt = (
                "Extract details for ONE industry event from this email (often a forward).\n"
                'Return STRICT JSON: {"is_event": bool, "name": str, "date": "YYYY-MM-DD"|null, '
                '"location": str|null, "host": str|null, "url": str|null}\n'
                "- is_event=false if this is NOT one concrete event (a newsletter digest, a market "
                "report, a general announcement, or multiple events bundled together).\n"
                "- name = the REAL event name, never the raw subject line, no 'Fwd:'/'Re:'.\n"
                "- date = the event's start date if stated, else null. location = venue/area if stated.\n\n"
                f"Subject: {subject}\nBody (first 2000 chars): {text[:2000]}\n\nJSON only."
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=250, temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = re.sub(r"^```(?:json)?|```$", "", msg.content[0].text.strip(), flags=re.I | re.M).strip()
            parsed = _json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("name"):
                return {**default, **parsed}
        except Exception as e:
            logger.warning(f"Event extract failed for '{subject[:40]}': {e}")
        return default

    def _clean_bd_summary(self, subject: str, text: str) -> str:
        """A clean 1-2 sentence summary of a forwarded market-news email — stripping the GLE
        signature, contact block, and 'Forwarded message' headers so the BD signal card is
        READABLE instead of a raw forward blob. Falls back to trimmed raw text on any failure.
        """
        fallback = " ".join((text or "").split())[:400]
        try:
            import anthropic
            from config import get_settings
            client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
            prompt = (
                "Summarize the actual real-estate news in this forwarded email in 1-2 tight sentences. "
                "IGNORE the sender's signature, contact block, and 'Forwarded message'/'From:' headers. "
                "Name the key parties, buildings, and dollar figures. No preamble, no 'This email'.\n\n"
                f"Subject: {subject}\nBody: {text[:2500]}"
            )
            msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=180,
                                         temperature=0, messages=[{"role": "user", "content": prompt}])
            out = msg.content[0].text.strip()
            return out or fallback
        except Exception as e:
            logger.warning(f"BD summary clean failed for '{subject[:40]}': {e}")
            return fallback

    def _route_to_bd(self, category: str, subject: str, sender: str, text: str, date: str) -> bool:
        """POST a classified BD signal (event / market_news) to Ordino's BD module. For
        events we first EXTRACT clean fields (real name/date/venue) instead of dumping the
        raw 'Fwd: ...' subject — and if it isn't really a single event, downgrade it to
        market_news so the Events list doesn't fill with junk rows. Returns False if not
        configured or the POST fails (caller then falls back to KB so nothing is lost).
        """
        import requests
        supabase_url = os.getenv("SUPABASE_URL", "")
        beacon_key = os.getenv("BEACON_ANALYTICS_KEY", "")
        if not supabase_url or not beacon_key:
            return False

        title = self._strip_fwd(subject)
        location = None
        source_url = None
        if category == "event":
            ev = self._extract_event_fields(subject, text)
            if not ev.get("is_event", True):
                category = "market_news"  # not a real event → don't create an event row
                title = ev.get("name") or title
                logger.info(f"  Downgraded non-event to market_news: '{title}'")
            else:
                title = ev.get("name") or title
                date = ev.get("date") or date
                location = ev.get("location")
                source_url = ev.get("url")

        try:
            resp = requests.post(
                f"{supabase_url}/functions/v1/bd-email-ingest",
                headers={"x-beacon-key": beacon_key, "Content-Type": "application/json"},
                json={
                    "signal_type": category,       # 'event' | 'market_news'
                    "title": title,
                    "summary": self._clean_bd_summary(subject, text),
                    "sender": sender,
                    "date": date,
                    "location": location,
                    "source_url": source_url,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"  BD routing failed for '{subject}': {e}")
            return False

    def _harvest_and_ingest_links(self, html_content: str, subject: str, date: str,
                                  collect_texts: list = None) -> int:
        """Fallback when structured parsing fails: scan the email for links to the
        ACTUAL DOB documents (PDF bulletins/notices and buildings.nyc.gov pages) and
        ingest those, not just the summary. This is what makes 'read the newsletter'
        mean 'capture the documents it references'.

        collect_texts: when a list is passed, the text of each followed DOB HTML page
        is appended to it so the caller can reuse it as the source text for a fallback
        content candidate (harvested article text preferred over raw email text).
        Default None keeps the original behavior for all other callers.
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
                        if collect_texts is not None:
                            collect_texts.append(content)
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
            # SSRF guard: pdf_url comes from links in untrusted inbound email, so validate
            # the host (and every redirect hop) resolves to a public IP before fetching.
            # nyc.gov returns 403 for the default requests User-Agent, so send a browser UA.
            from core.net_guard import safe_get
            resp = safe_get(
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

    def _mark_processed(self, msg_id: str, headers: dict, label_id):
        """Mark an email as read and apply one or more labels. `label_id` may be a single
        label id or a list of ids (e.g. Beacon/KB + Beacon/Content for a newsletter)."""
        import requests

        ids = [label_id] if isinstance(label_id, str) else list(label_id or [])
        ids = [i for i in ids if i]
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/modify"
        body = {
            "removeLabelIds": ["UNREAD"],
        }
        if ids:
            body["addLabelIds"] = ids

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to mark email {msg_id} as processed: {e}")

    def _labels(self, headers: dict, *names) -> list:
        """Resolve label names → ids (creating each as needed), dropping any that fail."""
        return [lid for lid in (self._get_or_create_label(headers, n) for n in names) if lid]

    def backfill_labels(self) -> dict:
        """One-time: remap the OLD flat labels onto the new Beacon/* tree. NON-DESTRUCTIVE —
        ADDS the new label and leaves the old one, so it's fully reversible (delete the old
        labels by hand once you've eyeballed the result). Exact remap only: the Signal/Event
        and Content granularity was never recorded historically, so BD stays under the parent
        Beacon/BD; new mail gets the precise split going forward.
        """
        import requests
        creds = self._get_gmail_credentials()
        if not creds:
            return {"error": "could not get Gmail credentials"}
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}

        remap = {
            "Beacon-Ingested": INGESTED_LABEL,      # -> Beacon/KB
            "Beacon-BD": BD_LABEL,                   # -> Beacon/BD (parent)
            "Beacon-Ingest-Failed": FAILED_LABEL,    # -> Beacon/Failed
            "Beacon-Taught": TAUGHT_LABEL,           # -> Beacon/Taught
        }

        try:
            labels = requests.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/labels",
                headers=headers, timeout=15).json().get("labels", [])
        except Exception as e:
            return {"error": f"list labels failed: {e}"}
        name_to_id = {l.get("name"): l.get("id") for l in labels}

        def _msg_ids(label_id):
            ids, page = [], None
            while True:
                params = {"labelIds": label_id, "maxResults": 500}
                if page:
                    params["pageToken"] = page
                r = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                 headers=headers, params=params, timeout=20).json()
                ids += [m["id"] for m in r.get("messages", [])]
                page = r.get("nextPageToken")
                if not page:
                    break
            return ids

        # Case-insensitive name → id (to detect a distinct real label already at the new name).
        lname_to = {(n or "").lower(): (n, i) for n, i in name_to_id.items()}
        summary = {}
        for old_name, new_name in remap.items():
            old_id = name_to_id.get(old_name)
            if not old_id:
                summary[old_name] = {"mapped_to": new_name, "note": "old label absent"}
                continue
            existing = lname_to.get(new_name.lower())
            existing_id = existing[1] if (existing and existing[1] != old_id) else None
            try:
                if existing_id:
                    # A distinct real label already lives at the new name (e.g. Beacon/KB I
                    # created earlier). Add it to old's messages, then delete the old label.
                    ids = _msg_ids(old_id)
                    for i in range(0, len(ids), 1000):
                        requests.post(
                            "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify",
                            headers=headers,
                            json={"ids": ids[i:i + 1000], "addLabelIds": [existing_id]},
                            timeout=30).raise_for_status()
                    requests.delete(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{old_id}",
                        headers=headers, timeout=15)
                    summary[old_name] = {"merged_into": new_name, "messages": len(ids)}
                else:
                    # Rename old → new. Moves its messages + nests it, and sidesteps the
                    # '-'/'/' separator collision (Gmail treats Beacon-BD == Beacon/BD).
                    r = requests.patch(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{old_id}",
                        headers=headers, json={"name": new_name}, timeout=15)
                    if r.ok:
                        summary[old_name] = {"renamed_to": new_name}
                    else:
                        summary[old_name] = {"error": f"rename {r.status_code}: {r.text[:140]}"}
            except Exception as e:
                summary[old_name] = {"error": str(e)}
            logger.info(f"[label-backfill] {old_name}: {summary[old_name]}")

        # Pre-create the full Beacon/* tree so every label shows in the sidebar immediately
        # (even empty), and the BD/Signal + BD/Event children make Gmail nest the tree
        # (collapsible Beacon ▸ BD ▸ …). Lets you see the structure + set a Beacon/Failed
        # filter before any traffic arrives.
        for lbl in (INGESTED_LABEL, CONTENT_LABEL, BD_LABEL, BD_SIGNAL_LABEL, BD_EVENT_LABEL,
                    SKIPPED_LABEL, FAILED_LABEL, TAUGHT_LABEL):
            self._get_or_create_label(headers, lbl)

        labels2 = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/labels",
            headers=headers, timeout=15).json().get("labels", [])
        beacon_labels = sorted(
            (l.get("name") for l in labels2 if (l.get("name") or "").lower().startswith("beacon")))
        return {"remap": summary, "existing_beacon_labels": beacon_labels}

    def _get_or_create_label(self, headers: dict, name: str = INGESTED_LABEL) -> Optional[str]:
        """Get or create a Gmail label by name (cached per name across polls)."""
        if name in self._label_ids:
            return self._label_ids[name]

        import requests

        # List existing labels
        url = "https://gmail.googleapis.com/gmail/v1/users/me/labels"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            labels = resp.json().get("labels", [])

            def _match(label_list):
                for label in label_list:
                    if (label.get("name") or "").strip().lower() == name.strip().lower():
                        self._label_ids[name] = label["id"]
                        return self._label_ids[name]
                return None

            hit = _match(labels)
            if hit:
                return hit

            # Create the label
            body = {
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            if resp.status_code == 409:
                # Already exists — differing case, or a nested parent that labels.list omitted.
                # Re-list and match case-insensitively to recover the id.
                hit = _match(requests.get(url, headers=headers, timeout=10).json().get("labels", []))
                if hit:
                    return hit
                logger.warning(f"Label {name!r} returned 409 but not found on re-list")
                return None
            resp.raise_for_status()
            self._label_ids[name] = resp.json().get("id")
            logger.info(f"Created Gmail label: {name}")
            return self._label_ids[name]

        except Exception as e:
            logger.warning(f"Could not get/create Gmail label {name!r}: {e}")
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

    # ------------------------------------------------------------------
    # Content backfill (one-time, re-runnable)
    # ------------------------------------------------------------------
    # WHY this exists: the live poll only ever queries `is:unread (from:...)`. Once an
    # email is read + labeled it never matches again, so it is never re-processed. PR #57
    # FIXED the parser (_ingest_newsletter → _preclean_forwarded_html / fallback
    # candidate), but fix-forward only — every newsletter received + labeled during the
    # content-candidate freeze stays missed. This walks that backlog (read state ignored)
    # back through the SAME fixed content path so those candidates are finally recovered.
    #
    # SAFETY: read-only w.r.t. mail — it NEVER sends, forwards, replies, or clears UNREAD.
    # The only Gmail write is an optional Beacon/Backfilled audit label (add-only).
    # IDEMPOTENT: candidate creation dedups by title inside _ingest_newsletter /
    # _create_fallback_candidate, so a re-run creates no duplicates (they land in
    # skipped_dupe instead). Content-only by CLASSIFICATION, not just by sender: the
    # SENDER_FILTERS query also catches manny@'s forwards (manny@ is in EMAIL_SENDER_FILTERS),
    # and most of those are Bisnow CRE-news / event / marketing forwards that were ALREADY
    # BD-routed when first seen live. So each message is re-run through the SAME classify gate
    # _process_email applies — only dob_regulatory reaches _ingest_newsletter; event/market_news
    # are skipped (never re-routed to BD → no duplicate signals) and 'other' is dropped. The
    # teach-path (_handle_forward) is never invoked here, so no duplicate KB/teach writes.
    def backfill_content(self, after: Optional[str] = None, dry_run: bool = False) -> dict:
        """Re-process already-received DOB/nyc.gov newsletters through the fixed content
        pipeline so the backlog since the freeze finally yields content candidates —
        CONTENT ONLY, by replicating _process_email's classification gate so the Bisnow /
        event / marketing forwards that share manny@'s sender filter never pollute the KB.

        Args:
            after:   Gmail date floor. None → auto-detect from the most recent content
                     candidate minus a 3-day safety buffer, floored at 2026-06-01.
                     Explicit value accepts YYYY/MM/DD, YYYY-MM-DD, or ISO.
            dry_run: when True, classify each message and report the clean would_ingest
                     list (dob_regulatory subjects) — create/label nothing.

        Returns a tally dict: {window_after, dry_run, scanned, candidates_created,
        skipped_bd, skipped_other, skipped_dupe, failed}, plus a would_ingest subject list
        on a dry_run.
        """
        import requests

        creds = self._get_gmail_credentials()
        if not creds:
            return {"error": "could not get Gmail credentials", "scanned": 0,
                    "candidates_created": 0, "skipped_dupe": 0, "failed": 0}
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}

        after_date = self._backfill_after_date(after)

        # SAME content senders the live poller keys on (DOB / nyc.gov newsletters). No
        # `is:unread` — we WANT already-read+labeled mail. BD senders / staff forwards are
        # excluded on purpose (they don't feed the content pipeline).
        sender_query = " OR ".join(f"from:{s.strip()}" for s in SENDER_FILTERS if s.strip())
        query = f"({sender_query}) after:{after_date}"
        logger.info(f"[content-backfill] query: {query} (dry_run={dry_run})")

        # 1) Fully paginate the match set (ALL messages, read or unread — no 10-cap).
        msg_ids = self._list_all_message_ids(headers, query)
        logger.info(f"[content-backfill] {len(msg_ids)} message(s) match the window")

        # 2) Fetch each once (we need subject/sender/html anyway) and sort oldest→newest by
        #    internalDate BEFORE processing, so candidates are created in chronological order.
        fetched = []
        failed = 0
        for mid in msg_ids:
            try:
                r = requests.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                    headers=headers, params={"format": "full"}, timeout=30)
                r.raise_for_status()
                m = r.json()
                fetched.append((int(m.get("internalDate", "0") or 0), mid, m))
            except Exception as e:
                failed += 1
                logger.warning(f"[content-backfill] fetch failed for {mid}: {e}")
        fetched.sort(key=lambda t: t[0])  # oldest → newest

        tally = {
            "window_after": after_date,
            "dry_run": dry_run,
            "scanned": 0,
            "candidates_created": 0,
            "skipped_bd": 0,      # event / market_news — already BD-routed live; not re-ingested
            "skipped_other": 0,   # low-value 'other' — dropped, never touches the KB
            "skipped_dupe": 0,    # dob_regulatory but produced no NEW candidate (title dedup / thin text)
            "failed": failed,
        }
        would_ingest = []  # dry_run: subjects that classify as dob_regulatory (the clean content list)

        backfill_label = None
        if not dry_run:
            backfill_label = self._get_or_create_label(headers, BACKFILLED_LABEL)

        for _internal_ms, mid, message in fetched:
            subject, sender = "", ""
            for h in message.get("payload", {}).get("headers", []):
                n = (h.get("name") or "").lower()
                if n == "subject":
                    subject = h.get("value", "")
                elif n == "from":
                    sender = h.get("value", "")
            tally["scanned"] += 1

            # Extract + PRE-CLEAN the HTML first, so a forwarded DOB newsletter classifies and
            # parses on its ORIGINAL content, not the Gmail forward wrapper. Keep the raw HTML
            # for the official-source check (the forwarded "From:" line lives in the wrapper
            # _preclean strips out).
            raw_html = self._extract_html_body(message.get("payload", {}))
            html_content = self._preclean_forwarded_html(raw_html)

            # Classifier text — same construction as live _process_email.
            try:
                from bs4 import BeautifulSoup
                text_for_class = BeautifulSoup(html_content or "", "html.parser").get_text(" ", strip=True)
            except Exception:
                text_for_class = ""

            # SAME classify gate the live poller applies — replicated here (never call
            # _process_email; it drives live behavior). This is the whole fix: the backfill
            # must ingest CONTENT ONLY, not the BD / marketing forwards that share manny@'s
            # sender filter.
            category = self._classify_email(subject, sender, text_for_class)

            # Force official DOB / nyc.gov agency mail to the KB even if the classifier saw
            # event-ish content or dismissed it as 'other'. Live keys on the SENDER being
            # nyc.gov; here genuine DOB content is often FORWARDED (sender=manny@), so the
            # sender-based force misses it — extend it CONSERVATIVELY to a clear official
            # source signal in the (pre-clean) body.
            sender_l = sender.lower()
            if "nyc.gov" in sender_l and category in ("event", "market_news", "other"):
                logger.info(f"[content-backfill] nyc.gov sender → KB (classifier said {category}): '{subject}'")
                category = "dob_regulatory"
            elif category in ("event", "market_news", "other") and \
                    self._is_official_dob_source(text_for_class, raw_html):
                logger.info(f"[content-backfill] forwarded official DOB source → KB "
                            f"(classifier said {category}): '{subject}'")
                category = "dob_regulatory"

            # 'other' = promos / personal / low-value — drop; never touches the permitting KB.
            if category == "other":
                tally["skipped_other"] += 1
                logger.info(f"[content-backfill] skipped (other): '{subject}'")
                continue

            # event / market_news = BD signals ALREADY routed to the BD module when first seen
            # live. Do NOT re-route (that would create DUPLICATE BD signals) and do NOT ingest
            # (KB pollution). Just skip for the content backfill.
            if category in ("event", "market_news"):
                tally["skipped_bd"] += 1
                logger.info(f"[content-backfill] skipped (BD {category}, already routed live): '{subject}'")
                continue

            # dob_regulatory → CONTENT. This is the clean list the operator eyeballs on a dry_run.
            would_ingest.append(subject)

            if dry_run:
                continue

            if not html_content:
                # Nothing parseable — count as a no-op skip, never a failure.
                tally["skipped_dupe"] += 1
                continue

            try:
                # Reuse PR #57's FIXED content path directly (NOT _process_email): parses,
                # KB-ingests, and creates content candidates deduped by title. Returns the
                # count of NEW candidates.
                made = self._ingest_newsletter(subject, sender, html_content) or 0
            except Exception as e:
                tally["failed"] += 1
                logger.error(f"[content-backfill] ingest failed for '{subject}': {e}",
                             exc_info=True)
                continue

            if made > 0:
                tally["candidates_created"] += made
            else:
                # Processed cleanly but produced no NEW candidate — already present (title
                # dedup) on a re-run, or too little text. Idempotency lands re-runs here.
                tally["skipped_dupe"] += 1

            # Optional read-only audit label (add-only; never clears UNREAD, never sends).
            if backfill_label:
                self._add_label_only(mid, headers, backfill_label)

        if dry_run:
            tally["would_ingest"] = would_ingest

        # Surface the recovery once in Ordino (the receiving /content handler ships in a
        # separate PR; this is a no-op until then, never an error).
        if not dry_run and tally["candidates_created"] > 0 and self.analytics_db:
            try:
                self.analytics_db.notify_ingest(
                    title=f"Content backfill: {tally['candidates_created']} candidate(s) recovered",
                    body=(f"Re-processed {tally['scanned']} newsletter(s) received since "
                          f"{after_date} through the fixed parser — "
                          f"{tally['candidates_created']} new content candidate(s), "
                          f"{tally['skipped_dupe']} already present."),
                    link="/content",
                )
            except Exception as e:
                logger.warning(f"[content-backfill] notify_ingest failed: {e}")

        logger.info(f"[content-backfill] done: {tally}")
        return tally

    def _list_all_message_ids(self, headers: dict, query: str) -> list:
        """Return every message id matching `query`, fully paginated via nextPageToken
        (500/page; no 10-cap). Ignores read/unread state — the query controls that."""
        import requests
        ids, page = [], None
        while True:
            params = {"q": query, "maxResults": 500}
            if page:
                params["pageToken"] = page
            try:
                r = requests.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    headers=headers, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.error(f"[content-backfill] list failed: {e}")
                break
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        return ids

    def _add_label_only(self, msg_id: str, headers: dict, label_id: Optional[str]):
        """Add a single label WITHOUT touching read/unread state — an audit trail only.
        Distinct from _mark_processed (which clears UNREAD): the backfill must stay
        read-only w.r.t. mail state."""
        import requests
        if not label_id:
            return
        try:
            requests.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/modify",
                headers=headers, json={"addLabelIds": [label_id]}, timeout=10,
            ).raise_for_status()
        except Exception as e:
            logger.warning(f"[content-backfill] audit-label failed for {msg_id}: {e}")

    def _backfill_after_date(self, after: Optional[str]) -> str:
        """Resolve the Gmail `after:` date (YYYY/MM/DD).

        Explicit `after` wins (YYYY/MM/DD, YYYY-MM-DD, or ISO). Otherwise auto-detect:
        the most recent content candidate date minus a 3-day safety buffer, floored at
        2026-06-01 so we never scan the whole inbox."""
        floor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        if after:
            dt = self._parse_ts(after)
            if dt is not None:
                return dt.strftime("%Y/%m/%d")
            # Last resort — accept an already-Gmail-shaped string as-is.
            s = str(after).strip().replace("-", "/")
            return s or floor.strftime("%Y/%m/%d")
        latest = self._latest_candidate_date()
        start = (latest - timedelta(days=3)) if latest else floor
        if start < floor:
            start = floor
        return start.strftime("%Y/%m/%d")

    def _latest_candidate_date(self) -> Optional[datetime]:
        """Most recent content_candidates.created_at across ALL statuses (tz-aware UTC),
        via the same analytics call the content scheduler's staleness watchdog uses.
        Returns None when the analytics store is unavailable or has no candidates."""
        adb = self.analytics_db
        if adb is None or not hasattr(adb, "get_content_candidates"):
            return None
        try:
            # status=None → no server-side status filter → all statuses count as "created".
            rows = adb.get_content_candidates(status=None, limit=1000) or []
        except Exception as e:
            logger.warning(f"[content-backfill] latest-candidate lookup failed: {e}")
            return None
        latest = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            dt = self._parse_ts(r.get("created_at"))
            if dt and (latest is None or dt > latest):
                latest = dt
        return latest

    @staticmethod
    def _parse_ts(ts) -> Optional[datetime]:
        """Parse an ISO-ish timestamp (or YYYY/MM/DD) to tz-aware UTC; naive input is
        assumed UTC. Returns None on failure."""
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace("/", "-"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
