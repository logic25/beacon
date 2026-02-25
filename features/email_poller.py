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
# Default: DOB Buildings News
DEFAULT_SENDERS = "noreply@buildings.nyc.gov,no-reply@buildings.nyc.gov,buildings@nyc.gov"
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

        # Parse and ingest using the existing pipeline
        self._ingest_newsletter(subject, sender, html_content)

        # Mark as read and label
        self._mark_processed(msg_id, headers, label_id)

        logger.info(f"✅ Email ingested: '{subject}'")

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
        """Parse newsletter HTML and ingest into Pinecone KB."""
        from content_engine.parser import DOBNewsletterParser
        from ingestion.document_processor import DocumentProcessor

        parser = DOBNewsletterParser()
        result = parser.parse_email(html_content)

        updates = result.get("updates", [])
        newsletter_date = result.get("newsletter_date", "unknown")

        if not updates:
            logger.info(f"No structured updates found in '{subject}' — ingesting as raw document")
            # Ingest the whole email as a single document
            self._ingest_raw_email(subject, sender, html_content, newsletter_date)
            return

        logger.info(f"Parsed {len(updates)} updates from '{subject}' ({newsletter_date})")

        for update in updates:
            title = update.get("title", "Untitled Update")
            summary = update.get("summary", "")
            full_content = update.get("full_content", summary)
            category = update.get("category", "General")
            source_url = update.get("source_url", "")

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

            # Ingest into Pinecone
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
                        },
                    )
                    count = self.retriever.vector_store.upsert_chunks(document.chunks)
                    logger.info(f"  Ingested '{title}' → {count} chunks")

                except Exception as e:
                    logger.error(f"  Failed to ingest '{title}': {e}")

            # Feed Content Intelligence engine
            if self.content_engine:
                try:
                    candidate = self.content_engine.analyze_update(
                        title, summary or full_content[:500], source_url,
                        source_type="newsletter_email"
                    )
                    logger.info(f"  Content candidate: '{candidate.title}' ({candidate.priority})")
                except Exception as e:
                    logger.error(f"  Content engine failed for '{title}': {e}")

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
Type: service_notice

# {subject}

{text_content[:5000]}
"""
            document = processor.process_text(
                text=md_content,
                title=subject,
                source_type="service_notice",
                metadata={
                    "date_issued": date,
                    "sender": sender,
                    "ingested_from": "email_poller",
                },
            )
            count = self.retriever.vector_store.upsert_chunks(document.chunks)
            logger.info(f"  Raw email ingested: '{subject}' → {count} chunks")

        except Exception as e:
            logger.error(f"  Failed to ingest raw email '{subject}': {e}")

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
