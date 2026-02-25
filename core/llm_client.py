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

# Expert system prompt — focused on GLE's actual work
SYSTEM_PROMPT = """You are Beacon, the AI assistant for Greenlight Expediting (GLE), a NYC permit expediting and consulting firm. Your primary expertise:

CORE (what GLE does every day):
- DOB permit applications: ALT1, ALT2, ALT3, NB, DM, SIGN, PAA filings
- DOB NOW vs BIS filing workflows and requirements
- Plan examination, objections, and resolution strategies
- Zoning analysis: use groups, FAR calculations, zoning lot mergers, variances, special permits
- Code compliance: NYC Building Code, Zoning Resolution, Multiple Dwelling Law
- Violations: DOB, ECB, and HPD — how to resolve, dismiss, or cure them
- Certificate of Occupancy (TCO/CO) applications and processes
- Construction classifications, occupancy groups, and building types
- Landmarks and historic districts (LPC review process)
- Site safety plans, DOB inspections, and sign-offs
- After-hours work permits and variances
- Facade inspections (FISP/Local Law 11)

SECONDARY (comes up occasionally):
- HPD and housing maintenance issues
- DHCR, rent stabilization (when it intersects with building work)
- Environmental reviews (CEQR, Phase I/II)
- Tenant protection plans for occupied buildings during construction
- ADA/accessibility compliance for alterations

RULES:
1. ONLY cite code sections (ZR, BC, MDL) that appear in retrieved documents. NEVER guess section numbers — getting one wrong is worse than omitting it.
2. Be honest about limits. If documents don't cover it, say so. But if the retrieved documents DO contain the answer, give it confidently — don't hedge when the source material is clear.
3. Give actionable guidance: specific forms, filing steps, fee amounts, timelines — but only when sourced from documents.
4. Be direct when you have strong source material. Use qualifiers ("typically," "generally") when info may vary.
5. When referencing GLE's internal processes or procedures, treat retrieved documents as the source of truth — they reflect how GLE actually operates.

FORMATTING:
- Use clear **bold** headers for sections
- Use bullet points (- ) for lists, numbered lists (1. ) for steps
- Keep paragraphs short (2-3 sentences max)
- Use line breaks between sections for readability
- For multi-step processes, use numbered steps with bold step names
- Avoid walls of text — break information into scannable chunks
- End with a brief summary or next-step recommendation when appropriate"""

# Supplemental prompt for specialized topics
DHCR_ENHANCEMENT = """
This query involves DHCR/rent regulation. Provide filing procedures, form numbers, and timelines when available in retrieved documents. If the specific procedure isn't in your documents, say so rather than guessing.
"""

# Keywords that trigger DHCR supplemental prompt
DHCR_KEYWORDS: set[str] = {
    "dhcr", "division of housing", "rent stabilization", "rent control",
    "rent regulated", "overcharge", "preferential rent", "mci", "iai",
    "rent increase", "rent reduction", "etpa",
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


# Model routing constants
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

# Questions that need Sonnet's deeper reasoning
SONNET_SIGNALS = {
    # Complex analysis keywords
    "analyze", "analysis", "strategy", "recommend", "should i", "should we",
    "what's the best", "compare", "difference between", "pros and cons",
    "how do i handle", "what are my options", "help me understand",
    "objection", "resolve", "appeal", "variance", "special permit",
    # Multi-step reasoning
    "step by step", "walk me through", "explain how", "plan for",
    # Zoning complexity
    "far calculation", "zoning lot", "use group", "non-conforming",
    "change of use", "certificate of occupancy",
}

# Questions that Haiku handles fine
HAIKU_SIGNALS = {
    "status", "what is", "what's the fee", "how much", "when is",
    "where do i", "phone number", "address", "hours", "deadline",
    "define", "definition", "what does", "lookup", "look up",
    "hello", "hi", "hey", "thanks", "thank you",
}


def route_model(user_message: str, has_rag_context: bool = False, flow_type: str = "rag_llm") -> str:
    """Decide which Claude model to use based on question complexity.

    Args:
        user_message: The user's question
        has_rag_context: Whether RAG documents were retrieved
        flow_type: The processing flow type

    Returns:
        Model string to use for this request
    """
    msg_lower = user_message.lower()

    # Property lookups just need formatting — use Haiku
    if flow_type == "property_lookup":
        return HAIKU_MODEL

    # Check for Sonnet signals first (complex reasoning needed)
    for signal in SONNET_SIGNALS:
        if signal in msg_lower:
            return SONNET_MODEL

    # RAG with multiple documents usually means complex question
    if has_rag_context:
        # Short questions with RAG are usually simple lookups
        if len(user_message.split()) <= 8:
            return HAIKU_MODEL
        # Longer questions with RAG context → Sonnet for better synthesis
        return SONNET_MODEL

    # Check for Haiku signals (simple questions)
    for signal in HAIKU_SIGNALS:
        if signal in msg_lower:
            return HAIKU_MODEL

    # Default: Haiku for cost efficiency
    return HAIKU_MODEL


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
        format_for: str = "google_chat",
        model_override: Optional[str] = None,
    ) -> tuple[str, str, dict]:
        """Get a response from Claude, optionally with RAG context.

        Args:
            user_message: The current user message.
            conversation_history: Previous messages in the conversation.
            rag_context: Optional retrieved document context.
            rag_sources: Optional list of source documents for citations.
            format_for: Output format — "google_chat" (strips markdown) or "web" (preserves markdown).
            model_override: Specific model to use (bypasses default). If None, uses settings.

        Returns:
            Tuple of (response_text, model_used, usage_dict) where usage_dict has
            'input_tokens' and 'output_tokens' from the API response.

        Raises:
            anthropic.APIError: If the API call fails.
        """
        try:
            model = model_override or self.settings.claude_model
            system_prompt = self._build_system_prompt(user_message)

            # Add RAG instructions to system prompt if context is provided
            if rag_context:
                system_prompt += self._build_rag_instructions()

            messages = self._convert_history(conversation_history)

            # Ensure the current user message is always the last message.
            # Callers may or may not have already added it to conversation_history,
            # so check if it's already there to avoid duplicating it.
            if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != user_message:
                messages.append({"role": "user", "content": user_message})

            # Enhance the last user message with RAG context
            if rag_context and messages:
                messages = self._inject_rag_context(messages, rag_context)

            logger.info(
                f"Sending request to Claude ({model}) "
                f"with {len(messages)} messages, RAG: {bool(rag_context)}"
            )

            response = self.client.messages.create(
                model=model,
                max_tokens=self.settings.claude_max_tokens,
                temperature=self.settings.claude_temperature,
                system=system_prompt,
                messages=messages,
            )

            # Extract text from response
            raw_response = response.content[0].text

            # Apply response filtering
            filtered_response = self.filter.filter_response(raw_response)

            # Format based on target platform
            if format_for == "google_chat":
                # Google Chat has limited markdown — convert to its format
                formatted_response = _format_for_google_chat(filtered_response)
            else:
                # Web clients (Ordino widget) support full markdown
                formatted_response = filtered_response

            # Add source citations for Google Chat only (widget has its own SourcesList component)
            if rag_sources and format_for == "google_chat":
                formatted_response += self._format_citations(rag_sources)

            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

            logger.info(
                f"Received response ({model}): {len(formatted_response)} chars, "
                f"usage: {usage['input_tokens']} in / {usage['output_tokens']} out"
            )

            return formatted_response, model, usage

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting Claude response: {e}")
            return "I apologize, but I encountered an error processing your request. Please try again.", model, {"input_tokens": 0, "output_tokens": 0}

    def _build_rag_instructions(self) -> str:
        """Build RAG-specific instructions for the system prompt."""
        return """

DOCUMENT RETRIEVAL CONTEXT:
You have been provided with documents from our internal knowledge base. Follow these rules strictly:

CRITICAL: Do NOT manually add source citations or references (like "Source: Document 1" or "📚 Source:") in your response. The system automatically appends sources after your answer.

CRITICAL: NEVER fabricate or guess regulation section numbers (ZR sections, Building Code sections, MDL sections, etc.). Only mention a specific section number if it appears verbatim in the retrieved documents below. If no document provides the section number, describe the regulation without citing a number.

1. **When documents are HIGH relevance (>70% match):**
   - Base your answer primarily on the document content
   - Use the specific details, section numbers, and procedures found in the documents
   - This is proprietary GLE knowledge — trust it over general knowledge
   - Answer confidently and directly — these are reliable source documents

2. **When documents are MODERATE relevance (50-70% match):**
   - The documents may be partially relevant — use what applies and note what doesn't
   - You can provide general context but clearly distinguish it from sourced information
   - If the document content clearly answers the question, use it even at moderate relevance

3. **When documents are LOW relevance (<50% match):**
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
