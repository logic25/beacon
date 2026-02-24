"""
Unit tests for the LLM client module.
"""

import pytest
from unittest.mock import MagicMock, patch

from core.llm_client import (
    ClaudeClient,
    Message,
    ResponseFilter,
    DHCR_KEYWORDS,
    SYSTEM_PROMPT,
)


class TestResponseFilter:
    """Tests for ResponseFilter class."""

    def test_filter_removes_consultation_phrases(self):
        """Test that consultation phrases are replaced."""
        text = "You should consult with a lawyer about this matter."
        result = ResponseFilter.filter_response(text)
        assert "consult with" not in result.lower()
        assert "follow these exact" in result.lower()

    def test_filter_replaces_advisable_language(self):
        """Test that advisory language is made more direct."""
        text = "It's advisable to file the form early."
        result = ResponseFilter.filter_response(text)
        assert "advisable" not in result.lower()
        assert "must" in result.lower()

    def test_filter_removes_hedging(self):
        """Test that hedging language is removed."""
        text = "You might be required to submit additional documents."
        result = ResponseFilter.filter_response(text)
        assert "might be required" not in result.lower()
        assert "is required" in result.lower()

    def test_filter_preserves_normal_text(self):
        """Test that normal informative text is preserved."""
        text = "File Form ABC-123 with the Department of Buildings."
        result = ResponseFilter.filter_response(text)
        assert "File Form ABC-123" in result
        assert "Department of Buildings" in result

    def test_filter_removes_double_spaces(self):
        """Test that double spaces are cleaned up."""
        text = "This  is a  test  with  spaces."
        result = ResponseFilter.filter_response(text)
        assert "  " not in result

    def test_filter_removes_legal_disclaimers(self):
        """Test that legal disclaimers are removed."""
        text = "Here is the information. This is not legal advice."
        result = ResponseFilter.filter_response(text)
        assert "not legal advice" not in result


class TestClaudeClient:
    """Tests for ClaudeClient class."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.anthropic_api_key = "test-key"
        settings.claude_model = "claude-haiku-4-5-20251001"
        settings.claude_max_tokens = 1500
        settings.claude_temperature = 0.3
        return settings

    def test_is_dhcr_related_positive(self, mock_settings):
        """Test DHCR detection with relevant keywords."""
        with patch("llm_client.get_settings", return_value=mock_settings):
            with patch("llm_client.anthropic.Anthropic"):
                client = ClaudeClient(mock_settings)

        assert client._is_dhcr_related("What is DHCR?")
        assert client._is_dhcr_related("Tell me about rent stabilization")
        assert client._is_dhcr_related("How do I file for a rent overcharge?")
        assert client._is_dhcr_related("MCI increase questions")

    def test_is_dhcr_related_negative(self, mock_settings):
        """Test DHCR detection with unrelated text."""
        with patch("llm_client.get_settings", return_value=mock_settings):
            with patch("llm_client.anthropic.Anthropic"):
                client = ClaudeClient(mock_settings)

        assert not client._is_dhcr_related("What is zoning?")
        assert not client._is_dhcr_related("Tell me about building permits")
        assert not client._is_dhcr_related("How do I get a CO?")

    def test_build_system_prompt_without_dhcr(self, mock_settings):
        """Test system prompt building for non-DHCR queries."""
        with patch("llm_client.get_settings", return_value=mock_settings):
            with patch("llm_client.anthropic.Anthropic"):
                client = ClaudeClient(mock_settings)

        prompt = client._build_system_prompt("What is zoning?")
        assert "NYC real estate" in prompt
        assert "DHCR-related query" not in prompt

    def test_build_system_prompt_with_dhcr(self, mock_settings):
        """Test system prompt building for DHCR queries."""
        with patch("llm_client.get_settings", return_value=mock_settings):
            with patch("llm_client.anthropic.Anthropic"):
                client = ClaudeClient(mock_settings)

        prompt = client._build_system_prompt("Tell me about rent stabilization")
        assert "NYC real estate" in prompt
        assert "DHCR-related query" in prompt

    def test_convert_history(self, mock_settings):
        """Test conversion of Message objects to API format."""
        with patch("llm_client.get_settings", return_value=mock_settings):
            with patch("llm_client.anthropic.Anthropic"):
                client = ClaudeClient(mock_settings)

        history = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]

        result = client._convert_history(history)

        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there!"}

    @patch("llm_client.anthropic.Anthropic")
    def test_get_response_success(self, mock_anthropic, mock_settings):
        """Test successful response from Claude."""
        # Set up mock response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Here is the information you need.")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        with patch("llm_client.get_settings", return_value=mock_settings):
            client = ClaudeClient(mock_settings)

        history = [Message(role="user", content="What is zoning?")]
        result = client.get_response("What is zoning?", history)

        assert "information" in result.lower()
        mock_client.messages.create.assert_called_once()

    @patch("llm_client.anthropic.Anthropic")
    def test_get_response_filters_output(self, mock_anthropic, mock_settings):
        """Test that response filtering is applied."""
        # Set up mock response with text that should be filtered
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text="You should consult with a lawyer.")
        ]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        with patch("llm_client.get_settings", return_value=mock_settings):
            client = ClaudeClient(mock_settings)

        history = [Message(role="user", content="Help me")]
        result = client.get_response("Help me", history)

        assert "consult with" not in result.lower()


class TestMessage:
    """Tests for Message dataclass."""

    def test_message_creation(self):
        """Test creating a Message."""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"


class TestDHCRKeywords:
    """Tests for DHCR keyword set."""

    def test_keywords_are_lowercase(self):
        """Verify all keywords are lowercase for matching."""
        for keyword in DHCR_KEYWORDS:
            assert keyword == keyword.lower(), f"Keyword '{keyword}' is not lowercase"

    def test_keywords_not_empty(self):
        """Verify keywords set is not empty."""
        assert len(DHCR_KEYWORDS) > 0


class TestSystemPrompt:
    """Tests for system prompt content."""

    def test_prompt_contains_key_topics(self):
        """Verify system prompt mentions key NYC real estate topics."""
        assert "zoning" in SYSTEM_PROMPT.lower()
        assert "dhcr" in SYSTEM_PROMPT.lower()
        assert "rent stabilization" in SYSTEM_PROMPT.lower()
        assert "building" in SYSTEM_PROMPT.lower()

    def test_prompt_discourages_consultation(self):
        """Verify prompt discourages external consultation advice."""
        assert "never suggest consulting" in SYSTEM_PROMPT.lower()
        assert "you are the expert" in SYSTEM_PROMPT.lower()
