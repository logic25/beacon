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

# Google Chat API scopes
SCOPES = [
    "https://www.googleapis.com/auth/chat.bot",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.messages.create",
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

    def _get_credentials(self) -> Optional[service_account.Credentials]:
        """Get and refresh Google credentials.

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
                        sa_info, scopes=SCOPES
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
                    str(service_account_path), scopes=SCOPES
                )

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

    def send_message(self, space_name: str, text: str) -> MessageResult:
        """Send a message to a Google Chat space.

        Args:
            space_name: The space identifier (e.g., "spaces/ABC123")
            text: Message text to send

        Returns:
            MessageResult with success status and message name
        """
        url = f"{self.BASE_URL}/{space_name}/messages"

        try:
            response = self._make_request("POST", url, {"text": text})

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

        url = f"{self.BASE_URL}/{message_name}"

        try:
            response = self._make_request("PUT", url, {"text": text})

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

    def send_typing_indicator(self, space_name: str) -> MessageResult:
        """Send a temporary 'processing' message that will be updated.

        Args:
            space_name: The space identifier

        Returns:
            MessageResult with the temporary message name
        """
        return self.send_message(space_name, "Processing your request...")
