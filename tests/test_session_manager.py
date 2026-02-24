"""
Unit tests for the session manager module.
"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.session_manager import Session, SessionManager
from core.llm_client import Message


class TestSession:
    """Tests for Session class."""

    def test_session_creation(self):
        """Test creating a new session."""
        session = Session(session_id="test_session")
        assert session.session_id == "test_session"
        assert session.chat_history == []
        assert session.last_active > 0

    def test_add_message(self):
        """Test adding a message to session."""
        session = Session(session_id="test")
        session.add_message("user", "Hello")

        assert len(session.chat_history) == 1
        assert session.chat_history[0].role == "user"
        assert session.chat_history[0].content == "Hello"

    def test_add_message_updates_last_active(self):
        """Test that adding a message updates last_active."""
        session = Session(session_id="test")
        old_time = session.last_active

        time.sleep(0.01)  # Small delay
        session.add_message("user", "Hello")

        assert session.last_active >= old_time

    def test_add_message_trims_history(self):
        """Test that history is trimmed when exceeding max."""
        session = Session(session_id="test")

        # Add more messages than max
        for i in range(15):
            session.add_message("user", f"Message {i}", max_history=10)

        assert len(session.chat_history) == 10
        # Should have the last 10 messages
        assert session.chat_history[0].content == "Message 5"
        assert session.chat_history[-1].content == "Message 14"

    def test_to_dict(self):
        """Test converting session to dictionary."""
        session = Session(session_id="test")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi!")

        result = session.to_dict()

        assert result["session_id"] == "test"
        assert len(result["chat_history"]) == 2
        assert result["chat_history"][0] == {"role": "user", "content": "Hello"}
        assert "last_active" in result

    def test_from_dict(self):
        """Test creating session from dictionary."""
        data = {
            "session_id": "test",
            "chat_history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ],
            "last_active": 12345.0,
        }

        session = Session.from_dict(data)

        assert session.session_id == "test"
        assert len(session.chat_history) == 2
        assert session.chat_history[0].role == "user"
        assert session.last_active == 12345.0


class TestSessionManager:
    """Tests for SessionManager class."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings with temp file."""
        settings = MagicMock()
        settings.session_file = tempfile.mktemp(suffix=".json")
        settings.max_history_length = 10
        settings.session_ttl_hours = 24
        return settings

    def test_get_or_create_session_new(self, mock_settings):
        """Test creating a new session."""
        manager = SessionManager(mock_settings)

        session = manager.get_or_create_session("user1", "space1")

        assert session.session_id == "user1_space1"
        assert session.chat_history == []

    def test_get_or_create_session_existing(self, mock_settings):
        """Test getting an existing session."""
        manager = SessionManager(mock_settings)

        # Create session
        session1 = manager.get_or_create_session("user1", "space1")
        session1.add_message("user", "Hello")

        # Get same session
        session2 = manager.get_or_create_session("user1", "space1")

        assert session2 is session1
        assert len(session2.chat_history) == 1

    def test_add_user_message(self, mock_settings):
        """Test adding a user message."""
        manager = SessionManager(mock_settings)

        session = manager.add_user_message("user1", "space1", "Hello")

        assert len(session.chat_history) == 1
        assert session.chat_history[0].role == "user"
        assert session.chat_history[0].content == "Hello"

    def test_add_assistant_message(self, mock_settings):
        """Test adding an assistant message."""
        manager = SessionManager(mock_settings)

        session = manager.add_assistant_message("user1", "space1", "Hi!")

        assert len(session.chat_history) == 1
        assert session.chat_history[0].role == "assistant"
        assert session.chat_history[0].content == "Hi!"

    def test_save_and_load_sessions(self, mock_settings):
        """Test persisting and loading sessions."""
        # Create manager and add data
        manager1 = SessionManager(mock_settings)
        manager1.add_user_message("user1", "space1", "Hello")
        manager1.add_assistant_message("user1", "space1", "Hi!")
        manager1.save_sessions()

        # Create new manager, should load existing data
        manager2 = SessionManager(mock_settings)

        session = manager2.get_or_create_session("user1", "space1")
        assert len(session.chat_history) == 2

    def test_cleanup_expired_sessions(self, mock_settings):
        """Test cleaning up expired sessions."""
        mock_settings.session_ttl_hours = 0  # Expire immediately

        manager = SessionManager(mock_settings)
        manager.add_user_message("user1", "space1", "Hello")

        # Small delay to ensure session is "expired"
        time.sleep(0.1)

        removed = manager.cleanup_expired_sessions()

        assert removed == 1
        # New session should be empty
        session = manager.get_or_create_session("user1", "space1")
        assert len(session.chat_history) == 0

    def test_session_file_not_found(self, mock_settings):
        """Test handling missing session file gracefully."""
        mock_settings.session_file = "/nonexistent/path/sessions.json"

        # Should not raise, just start with empty sessions
        manager = SessionManager(mock_settings)
        assert manager._sessions == {}

    def test_concurrent_access(self, mock_settings):
        """Test thread-safe access to sessions."""
        import threading

        manager = SessionManager(mock_settings)
        errors = []

        def add_messages(user_num):
            try:
                for i in range(10):
                    manager.add_user_message(f"user{user_num}", "space1", f"msg{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_messages, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Should have 5 sessions, each with 10 messages
        assert len(manager._sessions) == 5
