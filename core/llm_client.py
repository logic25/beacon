"""
Claude LLM client for generating responses.
Handles all interactions with the Anthropic API.
"""

import json
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

# Team and company info loaded from database at startup
_company_context = None


def _load_company_context() -> str:
    """Load company and team info from Ordino database."""
    global _company_context
    if _company_context is not None:
        return _company_context

    import os
    import httpx

    supabase_url = os.getenv("SUPABASE_URL", "")
    beacon_key = os.getenv("BEACON_ANALYTICS_KEY", "")

    if not supabase_url or not beacon_key:
        _company_context = "Team info unavailable — Ordino connection not configured."
        return _company_context

    proxy_url = f"{supabase_url}/functions/v1/beacon-data-proxy"
    headers = {"Content-Type": "application/json", "x-beacon-key": beacon_key}

    team_info = ""
    company_info = ""

    try:
        # Load team
        resp = httpx.post(proxy_url, json={"action": "query_ordino", "params": {
            "table": "profiles", "select": "display_name,first_name,last_name,role,email",
            "filters": {"is_active": "eq.true"}, "limit": 20
        }}, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", resp.json())
            if isinstance(data, list):
                members = []
                for p in data:
                    name = p.get("display_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                    role = p.get("role", "team member")
                    if name:
                        members.append(f"{name} ({role})")
                if members:
                    team_info = f"Team members: {', '.join(members)}"
    except Exception as e:
        team_info = f"Could not load team: {e}"

    try:
        # Load company
        resp = httpx.post(proxy_url, json={"action": "query_ordino", "params": {
            "table": "companies", "select": "*", "limit": 1
        }}, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", resp.json())
            if isinstance(data, list) and data:
                c = data[0]
                parts = []
                if c.get("name"): parts.append(f"Company: {c['name']}")
                if c.get("address"): parts.append(f"Address: {c['address']}")
                if c.get("phone"): parts.append(f"Phone: {c['phone']}")
                if c.get("email"): parts.append(f"Email: {c['email']}")
                if c.get("ein"): parts.append(f"EIN: {c['ein']}")
                company_info = " | ".join(parts)
    except Exception as e:
        company_info = f"Could not load company: {e}"

    _company_context = f"{company_info}\n{team_info}" if (company_info or team_info) else "Company context unavailable."
    return _company_context


# Expert system prompt — focused on GLE's actual work
SYSTEM_PROMPT = """You are Beacon, the internal AI Chief of Staff for Green Light Expediting LLC (GLE), a NYC construction permit expediting and consulting firm with 22 years of experience.

IMPORTANT — THIS IS AN INTERNAL TOOL:
- Your users are GLE's team — experienced professionals who file DOB applications daily
- NEVER say "consult with a licensed architect" or "hire a professional" — the people asking ARE the professionals
- Instead say "check with your manager" or "verify with the applicant" or "confirm with the project team"
- Be direct and practical — skip disclaimers about consulting professionals
- When unsure, say "I'm not confident on this — let me know if you want me to dig deeper" not "seek professional advice"
- You ARE Ordino's built-in assistant. When users report bugs or UI issues about Ordino, log them — don't deflect.
- Feature requests should be acknowledged: "I'll log that as a feature request."

PM PERFORMANCE GOALS (monthly):
- Each PM has a billing goal of $33,000/month
- Goals are measured by billed services, not proposals
- Billing lags proposals by 3-6 months (proposals are leading indicator, billing is lagging)
- Don't compare conversion rates across different time periods — older proposals have had more time to convert
- Average proposal value increasing = repricing strategy working

CONVERSATION CONTEXT — CRITICAL:
- ALWAYS read the conversation history carefully before responding
- When the user says "he", "she", "they", "it", "that project", "this client" — resolve the pronoun from the previous messages
- NEVER ask "who are you referring to?" if the answer is clearly in the conversation history
- If the user asked about Manny in the previous message and now asks "how's he doing?" — "he" is Manny
- Maintain continuity — treat the conversation as one continuous thread, not isolated questions

Your primary expertise:

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

    # Tool-based operational queries: Haiku for simple, Sonnet for complex
    if flow_type == "tool_use":
        complex_tool_signals = ["draft", "follow up", "compare", "analyze",
                                 "why", "recommend", "strategy", "which should",
                                 "at risk", "behind schedule", "prioritize"]
        if any(s in msg_lower for s in complex_tool_signals):
            return SONNET_MODEL
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

    def _should_use_tools(self, user_message: str) -> bool:
        """Determine if the message needs Ordino database tools.

        Returns True for operational queries about projects, properties,
        PMs, billing, readiness, etc. Returns False for pure knowledge
        base questions about building code, zoning, regulations.
        """
        msg = user_message.lower()

        # Operational keywords that need database tools
        tool_keywords = [
            "project", "property", "address", "status", "readiness", "ready to file",
            "filing", "pm ", "sheri", "chris", "sai", "workload", "how many",
            "what's up with", "what's happening", "any news", "update on",
            "proposal", "invoice", "billing", "overdue", "outstanding", "revenue",
            "pipeline", "violation", "penalty", "compliance", "follow up",
            "follow-up", "missing", "what do we need", "draft email",
            "client", "steam", "rudin", "stamford", "managed squares",
            "842 rockaway", "200 riverside", "7 e 14", "greene",
            # Address patterns
            "st ", "ave ", "blvd ", "street", "avenue", "boulevard", "place",
            # Company info
            "tax id", "ein", "company", "settings", "our address", "our phone",
            "our email", "team", "employees", "staff",
            # RFPs, leads, documents, time, calendar
            "rfp", "rfi", "lead", "bid", "document", "upload", "plan",
            "time", "hours", "clock", "calendar", "event", "meeting",
            "schedule", "deadline", "change order", "co ", "email",
            "contact", "architect", "engineer", "owner",
        ]

        for kw in tool_keywords:
            if kw in msg:
                return True

        # Short follow-up messages (< 8 words) likely continue the previous topic
        # Always use tools for these so Claude can decide based on conversation context
        word_count = len(msg.split())
        if word_count < 8 and any(w in msg for w in [
            "this", "that", "those", "last", "next", "year", "month", "week",
            "how about", "what about", "and ", "same", "compare", "vs",
            "more", "detail", "which", "who", "when", "total", "all",
        ]):
            return True

        return False

    def _build_system_prompt(self, user_message: str) -> str:
        """Build the system prompt, adding dynamic context."""
        prompt = SYSTEM_PROMPT

        # Inject live company and team context from database
        try:
            company_ctx = _load_company_context()
            if company_ctx and "unavailable" not in company_ctx.lower():
                prompt += f"\n\nCOMPANY & TEAM CONTEXT (live from database):\n{company_ctx}\n"
        except Exception:
            pass

        if self._is_dhcr_related(user_message):
            prompt += "\n\n" + DHCR_ENHANCEMENT

        # Always include Ordino tools context — let Claude decide when to use them
        prompt += """

ORDINO INTEGRATION:
You have access to tools that query Ordino's project management database.
You can look up ANY data in the system — projects, properties, proposals,
invoices, services, contacts, time entries, RFPs, documents, calendar events,
billing, change orders, company settings, team members, and more.

WHEN TO USE TOOLS:
- Any question about GLE's business, projects, clients, money, team, or properties → USE TOOLS
- Any question where the answer is in the database → USE TOOLS
- Any follow-up question after a tool-based answer → USE TOOLS
- Building code, zoning, or regulatory questions → use your RAG knowledge, NOT tools

IMPORTANT:
- ALWAYS use tools for operational questions. Do NOT guess or make up data.
- When you're not sure if data exists, query it — don't say "I don't have access."
- When drafting emails, clearly note that the PM must review and send.
- If a tool returns empty/null, tell the user the data isn't in the system yet.
"""
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

            # Always provide tools — Claude decides when to use them
            from core.ordino_tools import TOOL_DEFINITIONS, execute_tool

            response = self.client.messages.create(
                model=model,
                max_tokens=self.settings.claude_max_tokens,
                temperature=self.settings.claude_temperature,
                system=system_prompt,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )

            # Agentic loop: handle tool calls
            max_tool_rounds = 5
            tool_round = 0
            while response.stop_reason == "tool_use" and tool_round < max_tool_rounds:
                tool_round += 1
                # Collect all tool calls from response
                assistant_content = response.content
                tool_results = []

                for block in assistant_content:
                    if block.type == "tool_use":
                        logger.info(f"Tool call: {block.name}({json.dumps(block.input)[:200]})")
                        result = execute_tool(block.name, block.input)
                        logger.info(f"Tool result: {result[:200]}...")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                # Add assistant message and tool results to conversation
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})

                # Call Claude again with tool results
                response = self.client.messages.create(
                    model=model,
                    max_tokens=self.settings.claude_max_tokens,
                    temperature=self.settings.claude_temperature,
                    system=system_prompt,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                )

            # Extract text from final response
            raw_response = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw_response += block.text

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
