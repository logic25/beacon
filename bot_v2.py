"""
NYC Real Estate Expert Bot for Google Chat.
Powered by Claude (Anthropic) - Haiku or Sonnet models.

This bot provides authoritative guidance on NYC real estate regulations,
including DHCR, rent stabilization, zoning, and building codes.

Features:
- RAG retrieval from document knowledge base
- NYC Open Data live property lookups
- Semantic response caching
- Rate limiting and cost controls
- Common objections knowledge base
- Team knowledge capture (/correct, /tip)
"""

import logging
import sys
import threading
import time
from typing import Any

from flask import Flask, Response, jsonify, request

from config import Settings, get_settings
from google_chat import GoogleChatClient
from llm_client import ClaudeClient
from session_manager import SessionManager

# RAG imports (optional - graceful degradation if not configured)
try:
    from retriever import Retriever
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

# NYC Open Data imports (optional)
try:
    from nyc_open_data import NYCOpenDataClient, extract_address_from_query
    OPEN_DATA_AVAILABLE = True
except ImportError:
    OPEN_DATA_AVAILABLE = False

# Knowledge capture imports (optional)
try:
    from knowledge_capture import KnowledgeBase
    KNOWLEDGE_CAPTURE_AVAILABLE = True
except ImportError:
    KNOWLEDGE_CAPTURE_AVAILABLE = False

# Response caching (optional)
try:
    from response_cache import SemanticCache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

# Rate limiting and cost control (optional)
try:
    from rate_limiter import (
        UsageTracker, is_off_topic, get_off_topic_response,
        calculate_cost, get_tracker
    )
    RATE_LIMITER_AVAILABLE = True
except ImportError:
    RATE_LIMITER_AVAILABLE = False

# Objections knowledge base (optional)
try:
    from objections import ObjectionsKB, get_objections_response
    OBJECTIONS_AVAILABLE = True
except ImportError:
    OBJECTIONS_AVAILABLE = False

# Zoning analyzer (optional)
try:
    from zoning import ZoningAnalyzer
    ZONING_AVAILABLE = True
except ImportError:
    ZONING_AVAILABLE = False

# Plan reader capabilities (optional)
try:
    from plan_reader import get_capabilities_response as get_plan_capabilities
    PLAN_READER_AVAILABLE = True
except ImportError:
    PLAN_READER_AVAILABLE = False


def setup_logging(settings: Settings) -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


# Initialize Flask app
app = Flask(__name__)

# Initialize components (will be set up in main)
settings: Settings | None = None
claude_client: ClaudeClient | None = None
chat_client: GoogleChatClient | None = None
session_manager: SessionManager | None = None
retriever: "Retriever | None" = None
nyc_data_client: "NYCOpenDataClient | None" = None
knowledge_base: "KnowledgeBase | None" = None
response_cache: "SemanticCache | None" = None
usage_tracker: "UsageTracker | None" = None
objections_kb: "ObjectionsKB | None" = None
zoning_analyzer: "ZoningAnalyzer | None" = None
logger = logging.getLogger(__name__)


# Slash command definitions
SLASH_COMMANDS = {
    "/correct": "Flag a correction - Usage: /correct <what was wrong> | <correct answer>",
    "/tip": "Add a quick tip - Usage: /tip <your tip>",
    "/lookup": "Look up a property - Usage: /lookup <address>, <borough>",
    "/zoning": "Full zoning analysis - Usage: /zoning <address>, <borough>",
    "/objections": "Common objections - Usage: /objections <filing type>",
    "/plans": "Plan reading capabilities - What AI can analyze",
    "/help": "Show available commands",
    "/stats": "Show knowledge base and usage statistics",
    "/usage": "Show your usage stats",
}


def initialize_app() -> None:
    """Initialize all application components."""
    global settings, claude_client, chat_client, session_manager
    global retriever, nyc_data_client, knowledge_base
    global response_cache, usage_tracker, objections_kb, zoning_analyzer

    settings = get_settings()
    setup_logging(settings)

    logger.info("Initializing application components...")

    claude_client = ClaudeClient(settings)
    chat_client = GoogleChatClient(settings)
    session_manager = SessionManager(settings)

    # Initialize knowledge capture
    if KNOWLEDGE_CAPTURE_AVAILABLE:
        try:
            knowledge_base = KnowledgeBase()
            logger.info("âœ… Knowledge capture initialized")
        except Exception as e:
            logger.warning(f"Knowledge capture initialization failed: {e}")
            knowledge_base = None

    # Initialize response cache
    if CACHE_AVAILABLE:
        try:
            response_cache = SemanticCache(
                voyage_api_key=settings.voyage_api_key if hasattr(settings, 'voyage_api_key') else None
            )
            logger.info("âœ… Response cache initialized")
        except Exception as e:
            logger.warning(f"Response cache initialization failed: {e}")
            response_cache = None

    # Initialize rate limiter/usage tracker
    if RATE_LIMITER_AVAILABLE:
        try:
            usage_tracker = get_tracker()
            logger.info("âœ… Rate limiter initialized")
        except Exception as e:
            logger.warning(f"Rate limiter initialization failed: {e}")
            usage_tracker = None

    # Initialize objections KB
    if OBJECTIONS_AVAILABLE:
        try:
            objections_kb = ObjectionsKB()
            logger.info("âœ… Objections KB initialized")
        except Exception as e:
            logger.warning(f"Objections KB initialization failed: {e}")
            objections_kb = None

    # Initialize RAG retriever if configured
    if settings.rag_enabled and RAG_AVAILABLE and settings.pinecone_api_key:
        try:
            retriever = Retriever(settings=settings)
            logger.info("âœ… RAG retriever initialized")
        except Exception as e:
            logger.warning(f"RAG initialization failed: {e}")
            retriever = None
    else:
        if not settings.rag_enabled:
            logger.info("RAG is disabled in settings")
        elif not RAG_AVAILABLE:
            logger.info("RAG dependencies not installed")
        else:
            logger.info("RAG not configured (missing Pinecone API key)")

    # Initialize NYC Open Data client
    if OPEN_DATA_AVAILABLE:
        try:
            nyc_data_client = NYCOpenDataClient(settings)
            logger.info("âœ… NYC Open Data client initialized")
        except Exception as e:
            logger.warning(f"NYC Open Data initialization failed: {e}")
            nyc_data_client = None

    # Initialize zoning analyzer
    if ZONING_AVAILABLE:
        try:
            zoning_analyzer = ZoningAnalyzer()
            logger.info("âœ… Zoning analyzer initialized")
        except Exception as e:
            logger.warning(f"Zoning analyzer initialization failed: {e}")
            zoning_analyzer = None

    logger.info(f"Bot initialized with model: {settings.claude_model}")


def handle_slash_command(command: str, args: str, user_id: str, space_name: str) -> str | None:
    """Handle slash commands from users."""
    command = command.lower().strip()

    if command == "/help":
        lines = ["ðŸ“‹ **Available Commands:**"]
        for cmd, desc in SLASH_COMMANDS.items():
            lines.append(f"  `{cmd}` - {desc}")
        return "\n".join(lines)

    elif command == "/correct":
        if not knowledge_base:
            return "âš ï¸ Knowledge capture is not configured."

        if "|" not in args:
            return "âŒ Usage: `/correct <what was wrong> | <correct answer>`\n\nExample: `/correct Claude said MCI is 6% | MCI increases are capped at 2% since 2019`"

        parts = args.split("|", 1)
        wrong = parts[0].strip()
        correct = parts[1].strip()

        if not wrong or not correct:
            return "âŒ Please provide both the wrong response and the correct answer."

        # Detect topics
        topics = []
        topic_keywords = {
            "DOB": ["dob", "building", "permit", "violation", "certificate"],
            "DHCR": ["dhcr", "rent", "stabiliz", "mci", "iai", "lease"],
            "Zoning": ["zoning", "use group", "far", "setback", "variance"],
            "HPD": ["hpd", "housing", "habitability"],
        }
        combined = (wrong + " " + correct).lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                topics.append(topic)

        entry = knowledge_base.add_correction(wrong, correct, topics=topics or ["General"])
        logger.info(f"Correction captured by {user_id}: {entry.entry_id}")

        return f"âœ… **Correction captured!**\n\n**Wrong:** {wrong[:100]}{'...' if len(wrong) > 100 else ''}\n**Correct:** {correct[:150]}{'...' if len(correct) > 150 else ''}\n\nTopics: {', '.join(topics or ['General'])}"

    elif command == "/tip":
        if not knowledge_base:
            return "âš ï¸ Knowledge capture is not configured."

        if not args.strip():
            return "âŒ Usage: `/tip <your tip>`\n\nExample: `/tip Always check BIS for the latest CO before filing`"

        topics = []
        topic_keywords = {
            "DOB": ["dob", "building", "permit", "violation", "bis"],
            "DHCR": ["dhcr", "rent", "tenant", "landlord"],
            "Zoning": ["zoning", "use", "variance"],
        }
        for topic, keywords in topic_keywords.items():
            if any(kw in args.lower() for kw in keywords):
                topics.append(topic)

        entry = knowledge_base.add_tip(args.strip(), topics=topics or ["General"])
        logger.info(f"Tip captured by {user_id}: {entry.entry_id}")

        return f"âœ… **Tip captured!** Thanks for sharing your knowledge.\n\nðŸ’¡ {args.strip()}"

    elif command == "/lookup":
        if not nyc_data_client:
            return "âš ï¸ NYC Open Data is not configured."

        if "," not in args:
            return "âŒ Usage: `/lookup <address>, <borough>`\n\nExample: `/lookup 123 Main Street, Brooklyn`"

        parts = args.rsplit(",", 1)
        address = parts[0].strip()
        borough = parts[1].strip()

        if not address or not borough:
            return "âŒ Please provide both address and borough."

        try:
            property_info = nyc_data_client.get_property_info(address, borough)
            return property_info.to_context_string()
        except Exception as e:
            logger.error(f"Property lookup failed: {e}")
            return f"âŒ Could not find property: {address}, {borough}"

    elif command == "/zoning":
        if not zoning_analyzer:
            return "âš ï¸ Zoning analyzer is not configured."

        if "," not in args:
            return "âŒ Usage: `/zoning <address>, <borough>`\n\nExample: `/zoning 2410 White Plains Rd, Bronx`"

        parts = args.rsplit(",", 1)
        address = parts[0].strip()
        borough = parts[1].strip()

        if not address or not borough:
            return "âŒ Please provide both address and borough."

        try:
            analysis = zoning_analyzer.analyze(address, borough)
            return analysis.to_report()
        except Exception as e:
            logger.error(f"Zoning analysis failed: {e}")
            return f"âŒ Zoning analysis failed for: {address}, {borough}\n\nError: {str(e)[:100]}"

    elif command == "/objections":
        if not objections_kb:
            return "âš ï¸ Objections knowledge base is not configured."

        if not args.strip():
            return "âŒ Usage: `/objections <filing type>`\n\nExamples:\n  `/objections ALT1`\n  `/objections ALT2`\n  `/objections NB`\n  `/objections DM`"

        filing_type = args.strip().upper()
        return get_objections_response(filing_type)

    elif command == "/plans":
        if PLAN_READER_AVAILABLE:
            return get_plan_capabilities()
        else:
            return "âš ï¸ Plan reader module is not available."

    elif command == "/stats":
        lines = ["ðŸ“Š **Bot Statistics:**"]

        if knowledge_base:
            stats = knowledge_base.get_stats()
            lines.append(f"\n**Knowledge Base:**")
            lines.append(f"  Total entries: {stats['total_entries']}")
            for entry_type, count in stats.get('by_type', {}).items():
                lines.append(f"  - {entry_type}: {count}")

        if retriever:
            try:
                rag_stats = retriever.vector_store.get_stats()
                lines.append(f"\n**RAG Documents:** {rag_stats.get('total_vectors', 0)}")
            except Exception:
                pass

        if response_cache:
            try:
                cache_stats = response_cache.get_cache_stats()
                lines.append(f"\n**Response Cache:**")
                lines.append(f"  Cached responses: {cache_stats['total_entries']}")
                lines.append(f"  Cache hits: {cache_stats['total_hits']}")
            except Exception:
                pass

        if usage_tracker:
            try:
                daily = usage_tracker.get_daily_totals()
                lines.append(f"\n**Today's Usage:**")
                lines.append(f"  Requests: {daily['total_requests']}")
                lines.append(f"  Tokens: {daily['total_tokens']:,}")
                lines.append(f"  Cost: ${daily['total_cost']:.4f}")
                lines.append(f"  Active users: {daily['active_users']}")
            except Exception:
                pass

        # Top questions
        if response_cache:
            try:
                top = response_cache.get_top_questions(5)
                if top:
                    lines.append(f"\n**Top Questions:**")
                    for i, q in enumerate(top, 1):
                        lines.append(f"  {i}. ({q['count']}x) {q['question'][:50]}...")
            except Exception:
                pass

        lines.append(f"\n**Model:** {settings.claude_model}")
        lines.append(f"**NYC Open Data:** {'âœ…' if nyc_data_client else 'âŒ'}")
        lines.append(f"**Zoning Analyzer:** {'âœ…' if zoning_analyzer else 'âŒ'}")

        return "\n".join(lines)

    elif command == "/usage":
        if not usage_tracker:
            return "âš ï¸ Usage tracking is not configured."

        usage = usage_tracker.get_usage_summary(user_id)
        return f"""ðŸ“ˆ **Your Usage Today:**

  Requests: {usage['requests_today']}
  Remaining: {usage['requests_remaining_today']}
  Tokens used: {usage['tokens_today']:,}
  Cost: ${usage['cost_today']:.4f}

Daily limits: 100 requests, 100K tokens"""

    return None  # Not a recognized command


def process_message_async(
    user_id: str,
    space_name: str,
    user_message: str,
    temp_message_name: str | None,
) -> None:
    """Process a message in a background thread."""
    try:
        # Small delay to ensure temp message is sent
        time.sleep(0.3)

        # === RATE LIMITING CHECK ===
        if usage_tracker and RATE_LIMITER_AVAILABLE:
            allowed, limit_msg = usage_tracker.check_limits(user_id)
            if not allowed:
                if temp_message_name:
                    chat_client.update_message(temp_message_name, f"âš ï¸ {limit_msg}")
                else:
                    chat_client.send_message(space_name, f"âš ï¸ {limit_msg}")
                return

        # === OFF-TOPIC FILTER (FREE - no API call) ===
        if RATE_LIMITER_AVAILABLE:
            off_topic, reason = is_off_topic(user_message)
            if off_topic:
                logger.info(f"Off-topic message blocked: {reason}")
                response = get_off_topic_response()
                if temp_message_name:
                    chat_client.update_message(temp_message_name, response)
                else:
                    chat_client.send_message(space_name, response)
                return

        # === CHECK CACHE FIRST ===
        cached_response = None
        if response_cache and CACHE_AVAILABLE:
            cached_response = response_cache.get(user_message)
            if cached_response:
                logger.info(f"Cache hit for: {user_message[:50]}...")
                if temp_message_name:
                    chat_client.update_message(temp_message_name, cached_response)
                else:
                    chat_client.send_message(space_name, cached_response)
                return

        # === GET CONVERSATION HISTORY ===
        session = session_manager.get_or_create_session(user_id, space_name)

        # === GATHER CONTEXT ===
        rag_context = None
        rag_sources = None
        property_context = None
        objections_context = None

        # NYC Open Data property lookup (if address detected)
        if nyc_data_client is not None and OPEN_DATA_AVAILABLE:
            try:
                address_info = extract_address_from_query(user_message)
                if address_info:
                    address, borough = address_info
                    logger.info(f"Detected property query: {address}, {borough}")
                    property_info = nyc_data_client.get_property_info(address, borough)
                    property_context = property_info.to_context_string()
            except Exception as e:
                logger.warning(f"Property lookup failed: {e}")

        # Objections context (if filing type mentioned)
        if objections_kb and OBJECTIONS_AVAILABLE:
            filing_types = ["ALT1", "ALT2", "ALT3", "NB", "DM", "SIGN", "PAA"]
            msg_upper = user_message.upper()
            for ft in filing_types:
                if ft in msg_upper or f"ALT {ft[-1]}" in msg_upper:
                    try:
                        objections = objections_kb.get_objections_for_filing(ft)
                        if objections:
                            objections_context = f"Common {ft} objections:\n"
                            for obj in objections[:3]:
                                objections_context += f"- {obj.objection} (Resolve: {obj.typical_resolution})\n"
                    except Exception as e:
                        logger.warning(f"Objections lookup failed: {e}")
                    break

        # RAG retrieval
        if retriever is not None:
            try:
                retrieval_result = retriever.retrieve(
                    query=user_message,
                    top_k=settings.rag_top_k,
                    min_score=settings.rag_min_score,
                )
                if retrieval_result.num_results > 0:
                    rag_context = retrieval_result.context
                    rag_sources = retrieval_result.sources
                    logger.info(f"Retrieved {retrieval_result.num_results} documents")
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

        # Combine all context
        combined_context = None
        context_parts = []
        if property_context:
            context_parts.append(f"LIVE PROPERTY DATA:\n{property_context}")
        if objections_context:
            context_parts.append(f"RELEVANT OBJECTIONS:\n{objections_context}")
        if rag_context:
            context_parts.append(f"RELEVANT DOCUMENTS:\n{rag_context}")
        if context_parts:
            combined_context = "\n\n---\n\n".join(context_parts)

        # === GET RESPONSE FROM CLAUDE ===
        ai_response = claude_client.get_response(
            user_message=user_message,
            conversation_history=session.chat_history,
            rag_context=combined_context,
            rag_sources=rag_sources,
        )

        # === TRACK USAGE ===
        if usage_tracker and RATE_LIMITER_AVAILABLE:
            # Estimate tokens (rough: 4 chars per token)
            input_tokens = len(user_message + (combined_context or "")) // 4
            output_tokens = len(ai_response) // 4
            cost = calculate_cost(settings.claude_model, input_tokens, output_tokens)

            usage_tracker.record_usage(
                user_id=user_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                feature="chat"
            )

        # === CACHE RESPONSE ===
        if response_cache and CACHE_AVAILABLE:
            response_cache.set(user_message, ai_response)

        # === STORE IN SESSION ===
        session_manager.add_assistant_message(user_id, space_name, ai_response)

        # === SEND RESPONSE ===
        if temp_message_name:
            result = chat_client.update_message(temp_message_name, ai_response)
            if not result.success:
                logger.warning(f"Failed to update message: {result.error}")
                chat_client.send_message(space_name, ai_response)
        else:
            chat_client.send_message(space_name, ai_response)

    except Exception as e:
        logger.exception(f"Error in background processing: {e}")
        error_msg = "I apologize, but I encountered an error. Please try again."

        if temp_message_name:
            chat_client.update_message(temp_message_name, error_msg)
        else:
            chat_client.send_message(space_name, error_msg)


@app.route("/", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[Response, int] | tuple[str, int]:
    """Handle incoming webhooks from Google Chat."""
    try:
        data: dict[str, Any] = request.get_json() or {}

        logger.debug(f"Received webhook: {str(data)[:500]}...")

        message_data = data.get("message", {})
        user_message = message_data.get("text", "").strip()

        if not user_message:
            logger.warning("Received empty message")
            return "", 204

        user_data = data.get("user", {})
        user_id = user_data.get("name") or user_data.get("email", "unknown")
        space_name = data.get("space", {}).get("name", "")

        if not space_name:
            logger.error("No space name in webhook data")
            return jsonify({"error": "Missing space name"}), 400

        logger.info(f"Processing message from {user_id} in {space_name}")

        # Check for slash commands first
        if user_message.startswith("/"):
            parts = user_message.split(maxsplit=1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""

            response = handle_slash_command(command, args, user_id, space_name)
            if response:
                chat_client.send_message(space_name, response)
                return "", 204

        # Add user message to session
        session_manager.add_user_message(user_id, space_name, user_message)

        # Send temporary "processing" message
        temp_result = chat_client.send_typing_indicator(space_name)
        temp_message_name = temp_result.message_name if temp_result.success else None

        # Process in background thread
        thread = threading.Thread(
            target=process_message_async,
            args=(user_id, space_name, user_message, temp_message_name),
            daemon=True,
        )
        thread.start()

        return "", 204

    except Exception as e:
        logger.exception(f"Error in webhook handler: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health_check() -> tuple[Response, int]:
    """Health check endpoint."""
    health_data = {
        "status": "healthy",
        "model": settings.claude_model if settings else "not initialized",
        "features": {
            "rag": retriever is not None,
            "nyc_open_data": nyc_data_client is not None,
            "cache": response_cache is not None,
            "rate_limiter": usage_tracker is not None,
            "objections_kb": objections_kb is not None,
            "zoning_analyzer": zoning_analyzer is not None,
        }
    }

    if retriever is not None:
        try:
            stats = retriever.vector_store.get_stats()
            health_data["rag_documents"] = stats.get("total_vectors", 0)
        except Exception:
            health_data["rag_documents"] = "unknown"

    return jsonify(health_data), 200


@app.route("/analytics", methods=["GET"])
def analytics() -> tuple[Response, int]:
    """Analytics endpoint for dashboard."""
    analytics_data = {
        "status": "ok",
    }

    if usage_tracker:
        analytics_data["usage"] = usage_tracker.get_daily_totals()

    if response_cache:
        analytics_data["cache"] = response_cache.get_cache_stats()
        analytics_data["top_questions"] = response_cache.get_top_questions(20)

    return jsonify(analytics_data), 200


@app.route("/", methods=["GET"])
def index() -> tuple[Response, int]:
    """Root endpoint."""
    return jsonify({
        "name": "Beacon - NYC Real Estate Expert",
        "status": "running",
        "model": settings.claude_model if settings else "not initialized",
        "commands": list(SLASH_COMMANDS.keys()),
    }), 200


def main() -> None:
    """Main entry point."""
    initialize_app()

    import socket
    port = settings.port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("localhost", port)) == 0:
            logger.warning(f"Port {port} is in use, trying {port + 1}")
            port = port + 1

    logger.info(f"Starting server on port {port}")
    logger.info(f"Using Claude model: {settings.claude_model}")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=settings.debug,
        threaded=True,
    )


if __name__ == "__main__":
    main()
