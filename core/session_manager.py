"""
Session management for conversation history.
Handles persistence and cleanup of user sessions.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import Settings, get_settings
from core.llm_client import Message

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a user conversation session."""

    session_id: str
    chat_history: list[Message] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str, max_history: int = 10) -> None:
        """Add a message to the chat history.

        Args:
            role: Message role ("user" or "assistant")
            content: Message content
            max_history: Maximum number of messages to retain
        """
        self.chat_history.append(Message(role=role, content=content))
        self.last_active = time.time()

        # Trim history if needed
        if len(self.chat_history) > max_history:
            self.chat_history = self.chat_history[-max_history:]

    def to_dict(self) -> dict:
        """Convert session to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "chat_history": [
                {"role": msg.role, "content": msg.content}
                for msg in self.chat_history
            ],
            "last_active": self.last_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """Create session from dictionary."""
        session = cls(session_id=data["session_id"])
        session.chat_history = [
            Message(role=msg["role"], content=msg["content"])
            for msg in data.get("chat_history", [])
        ]
        session.last_active = data.get("last_active", time.time())
        return session


class SessionManager:
    """Manages user conversation sessions with persistence."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the session manager.

        Args:
            settings: Application settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._load_sessions()

    def _get_session_path(self) -> Path:
        """Get the path to the sessions file."""
        return Path(self.settings.session_file)

    def _load_sessions(self) -> None:
        """Load sessions from persistent storage."""
        path = self._get_session_path()
        if not path.exists():
            logger.info("No existing sessions file found")
            return

        try:
            with path.open("r") as f:
                data = json.load(f)

            with self._lock:
                for session_id, session_data in data.items():
                    # Add session_id to data if not present (migration)
                    session_data["session_id"] = session_id
                    self._sessions[session_id] = Session.from_dict(session_data)

            logger.info(f"Loaded {len(self._sessions)} sessions from {path}")

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing sessions file: {e}")
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")

    def save_sessions(self) -> None:
        """Save sessions to persistent storage."""
        path = self._get_session_path()

        try:
            with self._lock:
                data = {
                    session_id: session.to_dict()
                    for session_id, session in self._sessions.items()
                }

            with path.open("w") as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(data)} sessions to {path}")

        except Exception as e:
            logger.error(f"Error saving sessions: {e}")

    def get_or_create_session(self, user_id: str, space_name: str) -> Session:
        """Get an existing session or create a new one.

        Args:
            user_id: User identifier
            space_name: Chat space identifier

        Returns:
            The user's session
        """
        session_id = f"{user_id}_{space_name}"

        with self._lock:
            if session_id not in self._sessions:
                logger.info(f"Creating new session: {session_id}")
                self._sessions[session_id] = Session(session_id=session_id)
            else:
                # Update last active time
                self._sessions[session_id].last_active = time.time()

            return self._sessions[session_id]

    def add_user_message(
        self, user_id: str, space_name: str, content: str
    ) -> Session:
        """Add a user message to their session.

        Args:
            user_id: User identifier
            space_name: Chat space identifier
            content: Message content

        Returns:
            The updated session
        """
        session = self.get_or_create_session(user_id, space_name)
        session.add_message(
            role="user",
            content=content,
            max_history=self.settings.max_history_length,
        )
        return session

    def add_assistant_message(
        self, user_id: str, space_name: str, content: str
    ) -> Session:
        """Add an assistant message to a session.

        Args:
            user_id: User identifier
            space_name: Chat space identifier
            content: Message content

        Returns:
            The updated session
        """
        session = self.get_or_create_session(user_id, space_name)
        session.add_message(
            role="assistant",
            content=content,
            max_history=self.settings.max_history_length,
        )
        self.save_sessions()  # Persist after assistant response
        return session

    def cleanup_expired_sessions(self) -> int:
        """Remove sessions that have exceeded their TTL.

        Returns:
            Number of sessions removed
        """
        ttl_seconds = self.settings.session_ttl_hours * 3600
        cutoff = time.time() - ttl_seconds
        removed = 0

        with self._lock:
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if session.last_active < cutoff
            ]

            for session_id in expired:
                del self._sessions[session_id]
                removed += 1

        if removed > 0:
            logger.info(f"Cleaned up {removed} expired sessions")
            self.save_sessions()

        return removed
