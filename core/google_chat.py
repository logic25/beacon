"""
Google Chat API client for sending and updating messages.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from config import Settings, get_settings

logger = logging.getLogger(__name__)

# Google Chat API scopes.
# App auth (service account, no subject) — used for SENDING/updating messages.
SCOPES = [
    "https://www.googleapis.com/auth/chat.bot",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.messages.create",
]

# User-auth read scope — used with domain-wide delegation (impersonating
# BEACON_EMAIL) to LIST/READ messages in a space. spaces.messages.list is NOT
# available to pure app auth (returns 403 "insufficient authentication
# scopes"); reading requires acting as a member of the space. The impersonated
# user (BEACON_EMAIL) must therefore be a MEMBER of any space we read.
READ_SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
]


class GoogleChatError(Exception):
    """Custom exception for Google Chat API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class MessageResult:
    """Result of a message operation."""

    success: bool
    message_name: Optional[str] = None
    error: Optional[str] = None


class GoogleChatClient:
    """Client for interacting with Google Chat API."""

    BASE_URL = "https://chat.googleapis.com/v1"

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the Google Chat client.

        Args:
            settings: Application settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()
        self._credentials: Optional[service_account.Credentials] = None

    def _load_sa_credentials(
        self, scopes: list, subject: Optional[str] = None
    ) -> Optional[service_account.Credentials]:
        """Build and refresh service-account credentials for the given scopes.

        Args:
            scopes: OAuth scopes to request.
            subject: If set, impersonate this user via domain-wide delegation.

        Returns:
            Valid credentials or None if unavailable.
        """
        try:
            import json
            import os

            # First try: load from environment variable (Railway/production)
            sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if sa_json:
                try:
                    sa_info = json.loads(sa_json)
                    credentials = service_account.Credentials.from_service_account_info(
                        sa_info, scopes=scopes
                    )
                    logger.debug("Loaded credentials from GOOGLE_SERVICE_ACCOUNT_JSON env var")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
                    return None
            else:
                # Fallback: load from file (local development)
                service_account_path = Path(self.settings.google_service_account_file)

                if not service_account_path.exists():
                    logger.error(f"Service account file not found: {service_account_path}")
                    return None

                credentials = service_account.Credentials.from_service_account_file(
                    str(service_account_path), scopes=scopes
                )

            # Impersonate a user (domain-wide delegation) when a subject is given
            if subject:
                credentials = credentials.with_subject(subject)

            # Refresh to ensure valid token
            credentials.refresh(Request())

            if not credentials.token:
                logger.error("No token available in credentials")
                return None

            logger.debug(f"Token refreshed, expires: {credentials.expiry}")
            return credentials

        except Exception as e:
            logger.error(f"Error getting Google credentials: {e}")
            return None

    def _get_credentials(self) -> Optional[service_account.Credentials]:
        """App-auth credentials (chat.bot) — used for sending/updating messages."""
        return self._load_sa_credentials(SCOPES)

    def _get_read_credentials(self) -> Optional[service_account.Credentials]:
        """Impersonated user-auth credentials for reading/listing messages.

        Requires BEACON_EMAIL set + domain-wide delegation of
        chat.messages.readonly to the service account. Returns None when
        BEACON_EMAIL is unset so callers can fall back to app auth.
        """
        import os

        beacon_email = os.environ.get("BEACON_EMAIL", "")
        if not beacon_email:
            return None
        return self._load_sa_credentials(READ_SCOPES, subject=beacon_email)

    def _make_request(
        self,
        method: str,
        url: str,
        payload: Optional[dict] = None,
    ) -> requests.Response:
        """Make an authenticated request to Google Chat API.

        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            url: Full URL to request
            payload: Optional JSON payload

        Returns:
            Response object

        Raises:
            GoogleChatError: If authentication fails or request errors
        """
        # Reading messages (GET, e.g. spaces.messages.list) needs impersonated
        # user auth (chat.messages.readonly via DWD); sending/updating uses app
        # auth (chat.bot). Fall back to app auth if read creds are unavailable.
        credentials = None
        if method.upper() == "GET":
            credentials = self._get_read_credentials()
        if credentials is None:
            credentials = self._get_credentials()
        if not credentials:
            raise GoogleChatError("Failed to get Google credentials")

        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        }

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        return response

    def send_message(self, space_name: str, text: str, thread_name: str | None = None) -> MessageResult:
        """Send a message to a Google Chat space.

        Args:
            space_name: The space identifier (e.g., "spaces/ABC123")
            text: Message text to send
            thread_name: Optional thread name to reply in-thread (for group spaces)

        Returns:
            MessageResult with success status and message name
        """
        url = f"{self.BASE_URL}/{space_name}/messages"

        # If thread_name is provided, reply in that thread
        if thread_name:
            url += "?messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        payload: dict = {"text": text}
        if thread_name:
            payload["thread"] = {"name": thread_name}

        try:
            response = self._make_request("POST", url, payload)

            if response.status_code == 200:
                message_name = response.json().get("name")
                logger.info(f"Message sent successfully: {message_name}")
                return MessageResult(success=True, message_name=message_name)

            logger.error(f"Send message failed: {response.status_code} - {response.text}")
            return MessageResult(
                success=False,
                error=f"HTTP {response.status_code}: {response.text}",
            )

        except GoogleChatError as e:
            logger.error(f"Google Chat error sending message: {e}")
            return MessageResult(success=False, error=str(e))
        except requests.RequestException as e:
            logger.error(f"Request error sending message: {e}")
            return MessageResult(success=False, error=str(e))

    def update_message(self, message_name: str, text: str) -> MessageResult:
        """Update an existing message in Google Chat.

        Args:
            message_name: The full message name to update
            text: New message text

        Returns:
            MessageResult with success status
        """
        if not message_name:
            return MessageResult(success=False, error="No message name provided")

        url = f"{self.BASE_URL}/{message_name}?updateMask=text"

        try:
            response = self._make_request("PATCH", url, {"text": text})

            if response.status_code == 200:
                logger.info(f"Message updated successfully: {message_name}")
                return MessageResult(success=True, message_name=message_name)

            logger.error(f"Update message failed: {response.status_code} - {response.text}")
            return MessageResult(
                success=False,
                error=f"HTTP {response.status_code}: {response.text}",
            )

        except GoogleChatError as e:
            logger.error(f"Google Chat error updating message: {e}")
            return MessageResult(success=False, error=str(e))
        except requests.RequestException as e:
            logger.error(f"Request error updating message: {e}")
            return MessageResult(success=False, error=str(e))

    def send_typing_indicator(self, space_name: str, thread_name: str | None = None) -> MessageResult:
        """Send a temporary 'processing' message that will be updated.

        Args:
            space_name: The space identifier
            thread_name: Optional thread name to reply in-thread

        Returns:
            MessageResult with the temporary message name
        """
        return self.send_message(space_name, "🔍 Thinking...", thread_name=thread_name)
