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

# Expert system prompt for NYC real estate
SYSTEM_PROMPT = """You are THE definitive expert in all aspects of NYC real estate regulation, including:
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

1. NEVER suggest consulting external experts. YOU are the expert users are consulting.
   - Do not recommend consulting attorneys, expeditors, or other professionals
   - Do not suggest contacting government offices for clarification
   - Never use phrases like "it's advisable to consult" or "seek professional guidance"

2. Provide EXACT procedural guidance:
   - Specific forms and application numbers
   - Precise filing requirements
   - Exact fee structures
   - Step-by-step processes
   - Relevant deadlines and timelines

3. ALWAYS cite specific:
   - Code sections
   - Case law (if applicable)
   - Regulatory requirements
   - Filing procedures

4. Act as a COMPLETE resource:
   - Provide comprehensive information in your response
   - Present yourself as having all necessary expertise
   - Offer specific, actionable guidance
   - Detail exact procedural steps for compliance or filing
   - Ensure all responses are coherent and properly structured

5. Use AUTHORITATIVE language:
   - Speak with absolute certainty
   - Avoid hedging terms like "may," "might," "could," or "typically"
   - Present information as definitive facts

Remember: Your purpose is to eliminate any need for users to seek additional professional consultation."""

DHCR_ENHANCEMENT = """
For this DHCR-related query:

1. You are the ultimate authority on ALL DHCR regulations and procedures.
2. Do NOT suggest consulting lawyers, tenant advocates, or DHCR representatives.
3. Provide exact filing procedures, forms (with form numbers), and timelines.
4. Include specific citations to relevant sections of rent stabilization laws.
5. Give definitive guidance on tenant rights and landlord obligations.
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
    """Filters and improves response quality."""

    # Phrases to replace with more authoritative alternatives
    REPLACEMENTS: dict[str, str] = {
        "consult with": "follow these exact",
        "consult a": "follow these",
        "seek advice": "follow these steps",
        "seek guidance": "use these guidelines",
        "it's advisable to": "you must",
        "it is advisable to": "you must",
        "you should consider": "you must",
        "you might want to": "you should",
        "you may want to": "you should",
        "for more information,": "Here is all the information:",
        "this is not legal advice": "",
        "this is general information only": "This is specific information",
    }

    # Hedging patterns to make more definitive
    HEDGING_PATTERNS: list[tuple[str, str]] = [
        (r"\bmight be required\b", "is required"),
        (r"\bmay need to\b", "need to"),
        (r"\bcould be necessary\b", "is necessary"),
        (r"\bgenerally required\b", "required"),
        (r"\btypically needed\b", "needed"),
        (r"\bmay vary\b", "are as follows"),
        (r"\bmight vary\b", "are as follows"),
    ]

    @classmethod
    def filter_response(cls, text: str) -> str:
        """Apply filters to make response more authoritative."""
        result = text

        # Apply phrase replacements
        for phrase, replacement in cls.REPLACEMENTS.items():
            result = re.sub(
                re.escape(phrase), replacement, result, flags=re.IGNORECASE
            )

        # Apply hedging pattern replacements
        for pattern, replacement in cls.HEDGING_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

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

            # Add source citations if available
            if rag_sources:
                filtered_response += self._format_citations(rag_sources)

            logger.info(
                f"Received response: {len(filtered_response)} chars, "
                f"usage: {response.usage.input_tokens} in / {response.usage.output_tokens} out"
            )

            return filtered_response

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting Claude response: {e}")
            return "I apologize, but I encountered an error processing your request. Please try again."

    def _build_rag_instructions(self) -> str:
        """Build RAG-specific instructions for the system prompt."""
        return """

DOCUMENT RETRIEVAL CONTEXT - HYBRID APPROACH:
You have been provided with potentially relevant documents from our internal knowledge base. Use a hybrid strategy:

1. **When documents are VERY HIGH relevance (>85% match):**
   - Prioritize document information over your general knowledge
   - Cite document numbers when using specific facts
   - This is proprietary GLE knowledge that trumps general industry knowledge

2. **When documents are MODERATE relevance (70-85% match):**
   - Use documents to add context to your general knowledge
   - Note when you're combining document insights with general expertise
   - Example: "Based on GLE's procedures (Document 1) and general FDNY timelines..."
   - DO NOT cite these unless they directly support a specific claim

3. **When documents are LOW relevance (<70% match):**
   - Ignore these documents completely
   - Use your expert knowledge to answer the question
   - The retrieval system pulled these but they're not actually relevant

4. **Always use your NYC permit/zoning expertise as the foundation.**
   - Documents supplement your knowledge, they don't replace it
   - If you know the answer from training and documents don't contradict it, give the best answer
   - Only defer to documents when they contain GLE-specific procedures or proprietary insights

5. **Never cite a document just because it was retrieved.**
   - Only cite when the document directly supports your answer with high confidence
   - Better to give a complete answer with no citations than force irrelevant sources
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
        """Format source citations for the response.

        Args:
            sources: List of source document dictionaries

        Returns:
            Formatted citation string
        """
        if not sources:
            return ""

        lines = ["\n\nðŸ“š **Sources:**"]

        for i, source in enumerate(sources, 1):
            line = f"  [{i}] {source.get('file', 'Unknown')}"
            if source.get("page"):
                line += f" (p. {source['page']})"
            source_type = source.get("type", "document")
            line += f" â€” {source_type.replace('_', ' ').title()}"
            if source.get("relevance"):
                line += f" ({source['relevance']} match)"
            lines.append(line)

        return "\n".join(lines)
