"""
Claude LLM client for generating responses.
Handles all interactions with the Anthropic API.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

from config import Settings, get_settings

logger = logging.getLogger(__name__)


def _format_for_google_chat(text: str) -> str:
    """Format text for Google Chat's limited markdown support."""
    # Convert ## headers to *bold*
    text = re.sub(r'^###+\s*(.+)$', r'*\1*', text, flags=re.MULTILINE)
    
    # Convert **bold** to *bold*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    
    # Remove --- dividers
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    
    # Convert tables to simple text (remove pipe formatting)
    text = re.sub(r'\|', ' ', text)
    
    # Fix bullet points
    text = re.sub(r'^\s*[-\*]\s+', '• ', text, flags=re.MULTILINE)
    
    # Remove excess blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

# Expert system prompt for NYC real estate
SYSTEM_PROMPT = """You are a knowledgeable expert in NYC real estate regulation, including:
- NYC permit expediting
- Zoning codes and building codes
- Housing Maintenance Code (HMC) and Multiple Dwelling Law (MDL)
- DHCR (Division of Housing and Community Renewal) regulations and procedures
- Rent stabilization and rent control laws
- Tenant and landlord rights
- Real estate transaction requirements
- Department of Buildings (DOB) procedures
- All other NYC and NYS housing-related regulations

IMPORTANT RULES:

1. ONLY cite specific code sections, ZR sections, or regulation numbers that appear in retrieved documents.
   - NEVER invent, guess, or recall section numbers from memory
   - If no document provides a specific section number, say "per the Zoning Resolution" or "under DOB requirements" without fabricating a section number
   - If you are unsure which section applies, say so clearly — e.g., "The relevant ZR section is not in my current reference materials"
   - Getting a section number WRONG is far worse than omitting it

2. Be honest about the limits of your knowledge:
   - If retrieved documents do not contain the answer, say "I don't have specific documentation on this topic" rather than guessing
   - It is OK to say "I'm not certain" or "based on my understanding" when you lack high-confidence source material
   - Partial answers with honest caveats are better than confidently wrong answers

3. Provide procedural guidance when you have it:
   - Specific forms and application numbers (only when sourced from documents)
   - Filing requirements and fee structures (only when verified)
   - Step-by-step processes
   - Relevant deadlines and timelines

4. Act as a helpful resource:
   - Provide comprehensive information from your retrieved documents
   - Offer specific, actionable guidance when supported by sources
   - Detail exact procedural steps for compliance or filing when documented
   - Ensure all responses are coherent and properly structured

5. Use confident but calibrated language:
   - Be direct and clear when you have strong source material
   - Use appropriate qualifiers ("typically," "generally") when information may vary by situation
   - Present verified information as facts; present inferences as inferences

Remember: Your value comes from accuracy, not false confidence. A correct answer with caveats is infinitely more useful than a wrong answer stated with certainty."""

DHCR_ENHANCEMENT = """
For this DHCR-related query:

1. Focus on DHCR regulations, procedures, and rent stabilization/control laws.
2. Provide filing procedures, forms (with form numbers), and timelines when available in retrieved documents.
3. Include specific citations to relevant sections of rent stabilization laws ONLY when found in retrieved documents.
4. Give clear guidance on tenant rights and landlord obligations based on your source material.
5. If the specific DHCR procedure or form number is not in your documents, say so rather than guessing.
"""

# Keywords that indicate DHCR-related queries
DHCR_KEYWORDS: set[str] = {
    "dhcr", "division of housing", "rent stabilization", "rent control",
    "rent regulated", "overcharge", "lease renewal", "preferential rent",
    "legal regulated rent", "fair market rent", "apartment registration",
    "vacancy allowance", "major capital improvement", "individual apartment improvement",
    "mci", "iai", "rent increase", "rent reduction", "emergency tenant protection act",
    "etpa", "harassment", "tenant complaint", "housing court", "eviction"
}


@dataclass
class Message:
    """Represents a conversation message."""
    role: str  # "user" or "assistant"
    content: str


class ResponseFilter:
    """Filters response quality — light touch only.

    Previously this aggressively replaced hedging language with definitive claims,
    which caused dangerous false confidence (e.g., "may need to" → "need to").
    Now it only cleans up formatting and removes truly unhelpful filler phrases.
    Honest uncertainty is preserved because wrong-with-confidence is worse than right-with-caveats.
    """

    # Only remove truly unhelpful filler — NOT hedging language
    REPLACEMENTS: dict[str, str] = {
        "this is not legal advice": "",
        "i am an ai language model": "",
        "as an ai": "",
    }

    # No hedging pattern replacements — uncertainty language is valuable and accurate
    HEDGING_PATTERNS: list[tuple[str, str]] = []

    @classmethod
    def filter_response(cls, text: str) -> str:
        """Apply light formatting filters. Preserves hedging and uncertainty."""
        result = text

        # Apply minimal phrase replacements (just filler removal)
        for phrase, replacement in cls.REPLACEMENTS.items():
            result = re.sub(
                re.escape(phrase), replacement, result, flags=re.IGNORECASE
            )

        # Clean up any double spaces
        result = re.sub(r"  +", " ", result)

        return result.strip()


class ClaudeClient:
    """Client for interacting with Claude API."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the Claude client.

        Args:
            settings: Application settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        self.filter = ResponseFilter()

    def _is_dhcr_related(self, text: str) -> bool:
        """Check if the text is related to DHCR topics."""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in DHCR_KEYWORDS)

    def _build_system_prompt(self, user_message: str) -> str:
        """Build the system prompt, adding DHCR enhancement if relevant."""
        prompt = SYSTEM_PROMPT
        if self._is_dhcr_related(user_message):
            prompt += "\n\n" + DHCR_ENHANCEMENT
        return prompt

    def _convert_history(self, history: list[Message]) -> list[dict[str, str]]:
        """Convert Message objects to Anthropic API format."""
        return [{"role": msg.role, "content": msg.content} for msg in history]

    def get_response(
        self,
        user_message: str,
        conversation_history: list[Message],
        rag_context: Optional[str] = None,
        rag_sources: Optional[list[dict]] = None,
    ) -> str:
        """Get a response from Claude, optionally with RAG context.

        Args:
            user_message: The current user message.
            conversation_history: Previous messages in the conversation.
            rag_context: Optional retrieved document context.
            rag_sources: Optional list of source documents for citations.

        Returns:
            The assistant's response text (with citations if sources provided).

        Raises:
            anthropic.APIError: If the API call fails.
        """
        try:
            system_prompt = self._build_system_prompt(user_message)

            # Add RAG instructions to system prompt if context is provided
            if rag_context:
                system_prompt += self._build_rag_instructions()

            messages = self._convert_history(conversation_history)

            # Enhance the last user message with RAG context
            if rag_context and messages:
                messages = self._inject_rag_context(messages, rag_context)

            logger.info(
                f"Sending request to Claude ({self.settings.claude_model}) "
                f"with {len(messages)} messages, RAG: {bool(rag_context)}"
            )

            response = self.client.messages.create(
                model=self.settings.claude_model,
                max_tokens=self.settings.claude_max_tokens,
                temperature=self.settings.claude_temperature,
                system=system_prompt,
                messages=messages,
            )

            # Extract text from response
            raw_response = response.content[0].text

            # Apply response filtering
            filtered_response = self.filter.filter_response(raw_response)
            
            # Format for Google Chat (strip unsupported markdown)
            formatted_response = _format_for_google_chat(filtered_response)

            # Add source citations if available
            if rag_sources:
                formatted_response += self._format_citations(rag_sources)

            logger.info(
                f"Received response: {len(formatted_response)} chars, "
                f"usage: {response.usage.input_tokens} in / {response.usage.output_tokens} out"
            )

            return formatted_response

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting Claude response: {e}")
            return "I apologize, but I encountered an error processing your request. Please try again."

    def _build_rag_instructions(self) -> str:
        """Build RAG-specific instructions for the system prompt."""
        return """

DOCUMENT RETRIEVAL CONTEXT:
You have been provided with documents from our internal knowledge base. Follow these rules strictly:

CRITICAL: Do NOT manually add source citations or references (like "Source: Document 1" or "📚 Source:") in your response. The system automatically appends sources after your answer.

CRITICAL: NEVER fabricate or guess regulation section numbers (ZR sections, Building Code sections, MDL sections, etc.). Only mention a specific section number if it appears verbatim in the retrieved documents below. If no document provides the section number, describe the regulation without citing a number.

1. **When documents are HIGH relevance (>80% match):**
   - Base your answer primarily on the document content
   - Use the specific details, section numbers, and procedures found in the documents
   - This is proprietary GLE knowledge — trust it over general knowledge

2. **When documents are MODERATE relevance (60-80% match):**
   - The documents may be partially relevant — use what applies and note what doesn't
   - Do NOT fill in gaps by inventing details — say "the retrieved documents cover X but not Y"
   - You can provide general context but clearly distinguish it from sourced information

3. **When documents are LOW relevance (<60% match):**
   - The retrieval system found weak matches — these may not actually answer the question
   - Tell the user what you found and that it may not directly address their question
   - Do NOT ignore the documents and substitute your own knowledge as if it were sourced
   - Say something like: "My reference documents don't directly address this. Based on general knowledge..."

4. **Your retrieved documents are the PRIMARY source of truth.**
   - If documents contradict your general knowledge, trust the documents (they may reflect GLE-specific procedures)
   - If documents don't cover the topic, be transparent about that gap
   - NEVER present general training knowledge as if it came from retrieved documents

5. **Section number rules:**
   - Only cite ZR, BC, MDL, or other code sections that appear in the retrieved text
   - If you know a regulation exists but can't find the section number in documents, say "the applicable ZR section" without guessing the number
   - Double-check any section number you're about to cite — is it actually in the documents below?
"""

    def _inject_rag_context(
        self,
        messages: list[dict[str, str]],
        context: str,
    ) -> list[dict[str, str]]:
        """Inject RAG context into the conversation messages.

        Args:
            messages: Current conversation messages
            context: Retrieved document context

        Returns:
            Messages with RAG context injected
        """
        if not messages:
            return messages

        # Get the last user message
        last_msg = messages[-1]
        if last_msg["role"] != "user":
            return messages

        # Create enhanced message with context
        enhanced_content = f"""Here are relevant documents from our knowledge base:

{context}

---

Based on the above documents and your expertise, please answer my question:

{last_msg['content']}"""

        # Return messages with enhanced last message
        return messages[:-1] + [{"role": "user", "content": enhanced_content}]

    def _format_citations(self, sources: list[dict]) -> str:
        """Format source citations for Google Chat.

        Args:
            sources: List of source document dictionaries

        Returns:
            Formatted citation string for Google Chat
        """
        if not sources:
            return ""

        lines = ["\n\n📚 *Sources:*"]

        for i, source in enumerate(sources, 1):
            # Clean filename for display
            filename = source.get('file', 'Unknown')
            display_name = filename.replace('.md', '').replace('_', ' ').title()
            
            line = f"• [{i}] {display_name}"
            
            source_type = source.get("type", "document")
            line += f" — {source_type.replace('_', ' ').title()}"
            
            if source.get("relevance"):
                line += f" ({source['relevance']} match)"
                
            lines.append(line)

        return "\n".join(lines)
