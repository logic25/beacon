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
import json
from datetime import datetime
from typing import Any

from flask import Flask, redirect, url_for, Response, jsonify, request
from flask_cors import CORS

from config import Settings, get_settings
from core.google_chat import GoogleChatClient
from core.llm_client import ClaudeClient
from core.session_manager import SessionManager

# RAG imports (optional - graceful degradation if not configured)
try:
    from core.retriever import Retriever
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

# NYC Open Data imports (optional)
try:
    from features.nyc_open_data import NYCOpenDataClient, extract_address_from_query
    OPEN_DATA_AVAILABLE = True
except ImportError:
    OPEN_DATA_AVAILABLE = False

# Knowledge capture imports (optional)
try:
    from features.knowledge_capture import KnowledgeBase
    KNOWLEDGE_CAPTURE_AVAILABLE = True
except ImportError:
    KNOWLEDGE_CAPTURE_AVAILABLE = False

# Response caching (optional)
try:
    from core.response_cache import SemanticCache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

# Rate limiting and cost control (optional)
try:
    from core.rate_limiter import (
        UsageTracker, is_off_topic, get_off_topic_response,
        calculate_cost, get_tracker
    )
    RATE_LIMITER_AVAILABLE = True
except ImportError:
    RATE_LIMITER_AVAILABLE = False

# Objections knowledge base (optional)
try:
    from features.objections import ObjectionsKB, get_objections_response
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
    from features.plan_reader import get_capabilities_response as get_plan_capabilities
    PLAN_READER_AVAILABLE = True
except ImportError:
    PLAN_READER_AVAILABLE = False

# Analytics and Dashboard (optional)
# Prefer Supabase for persistence; fall back to SQLite
SUPABASE_ANALYTICS = False
try:
    from analytics.analytics import AnalyticsDB, Interaction, get_analytics_db
    from features.dashboard import add_dashboard_routes
    ANALYTICS_AVAILABLE = True
except Exception as e:
    ANALYTICS_AVAILABLE = False
    import logging
    logging.error(f"Failed to import analytics/dashboard: {e}", exc_info=True)

try:
    from analytics.analytics_supabase import SupabaseAnalyticsDB
    SUPABASE_ANALYTICS_AVAILABLE = True
except ImportError:
    SUPABASE_ANALYTICS_AVAILABLE = False

# Content Intelligence (optional)
try:
    from analytics.content_routes import content_bp
    CONTENT_INTELLIGENCE_AVAILABLE = True
except ImportError:
    CONTENT_INTELLIGENCE_AVAILABLE = False


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

# Configure Flask secret key for sessions (required for OAuth)
import os
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-in-production')

# Enable CORS for web API endpoints (Ordino dashboard calls /api/chat)
ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', '*').split(',')
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}}, supports_credentials=True)

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
analytics_db: "AnalyticsDB | None" = None
logger = logging.getLogger(__name__)


# Admin whitelist for /correct (only these users can apply corrections immediately)
# Everyone else uses /suggest which logs for review but doesn't inject into retrieval
ADMIN_EMAILS = {
    "manny@greenlightexpediting.com",
    "chris@greenlightexpediting.com",
}


# Slash command definitions
SLASH_COMMANDS = {
    "/correct": "Flag a correction (admin only) - Usage: /correct <what was wrong> | <correct answer>",
    "/suggest": "Suggest a correction for review - Usage: /suggest <what was wrong> | <correct answer>",
    "/tip": "Add a quick tip - Usage: /tip <your tip>",
    "/lookup": "Look up a property - Usage: /lookup <address>, <borough>",
    "/zoning": "Full zoning analysis - Usage: /zoning <address>, <borough>",
    "/objections": "Common objections - Usage: /objections <filing type>",
    "/plans": "Plan reading capabilities - What AI can analyze",
    "/help": "Show available commands",
    "/stats": "Show knowledge base and usage statistics",
    "/usage": "Show your usage stats",
    "/feedback": "Suggest a new feature or improvement - Usage: /feedback <your idea>",
}


def initialize_app() -> None:
    """Initialize all application components."""
    global settings, claude_client, chat_client, session_manager
    global retriever, nyc_data_client, knowledge_base
    global response_cache, usage_tracker, objections_kb, zoning_analyzer
    global analytics_db

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
            logger.info("✅ Knowledge capture initialized")
        except Exception as e:
            logger.warning(f"Knowledge capture initialization failed: {e}")
            knowledge_base = None

    # Initialize response cache
    if CACHE_AVAILABLE:
        try:
            response_cache = SemanticCache(
                voyage_api_key=settings.voyage_api_key if hasattr(settings, 'voyage_api_key') else None
            )
            logger.info("✅ Response cache initialized")
        except Exception as e:
            logger.warning(f"Response cache initialization failed: {e}")
            response_cache = None

    # Initialize rate limiter/usage tracker
    if RATE_LIMITER_AVAILABLE:
        try:
            usage_tracker = get_tracker()
            logger.info("✅ Rate limiter initialized")
        except Exception as e:
            logger.warning(f"Rate limiter initialization failed: {e}")
            usage_tracker = None

    # Initialize objections KB
    if OBJECTIONS_AVAILABLE:
        try:
            objections_kb = ObjectionsKB()
            logger.info("✅ Objections KB initialized")
        except Exception as e:
            logger.warning(f"Objections KB initialization failed: {e}")
            objections_kb = None

    # Initialize RAG retriever if configured
    if settings.rag_enabled and RAG_AVAILABLE and settings.pinecone_api_key:
        try:
            retriever = Retriever(settings=settings)
            logger.info("✅ RAG retriever initialized")
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
            logger.info("✅ NYC Open Data client initialized")
        except Exception as e:
            logger.warning(f"NYC Open Data initialization failed: {e}")
            nyc_data_client = None

    # Initialize zoning analyzer
    if ZONING_AVAILABLE:
        try:
            zoning_analyzer = ZoningAnalyzer()
            logger.info("✅ Zoning analyzer initialized")
        except Exception as e:
            logger.warning(f"Zoning analyzer initialization failed: {e}")
            zoning_analyzer = None

    # Initialize analytics and dashboard
    # Prefer Supabase (persists across deploys) over SQLite (ephemeral)
    global SUPABASE_ANALYTICS
    beacon_analytics_key = settings.beacon_analytics_key if hasattr(settings, 'beacon_analytics_key') else ""
    if not beacon_analytics_key:
        import os
        beacon_analytics_key = os.getenv("BEACON_ANALYTICS_KEY", "")

    if SUPABASE_ANALYTICS_AVAILABLE and settings.supabase_url and beacon_analytics_key:
        try:
            analytics_db = SupabaseAnalyticsDB(settings.supabase_url, beacon_analytics_key)
            SUPABASE_ANALYTICS = True
            logger.info("✅ Supabase analytics initialized (persistent via edge function)")
        except Exception as e:
            logger.warning(f"Supabase analytics failed, falling back to SQLite: {e}")
            analytics_db = None

    if analytics_db is None and ANALYTICS_AVAILABLE:
        try:
            analytics_db = get_analytics_db()
            logger.info("✅ SQLite analytics initialized (ephemeral — set SUPABASE_URL and BEACON_ANALYTICS_KEY for persistence)")
        except Exception as e:
            logger.warning(f"Analytics initialization failed: {e}")
            analytics_db = None

    # Dashboard routes (works with either analytics backend)
    if analytics_db and ANALYTICS_AVAILABLE:
        try:
            add_dashboard_routes(app, analytics_db)
            logger.info("✅ Dashboard routes registered")
        except Exception as e:
            logger.warning(f"Dashboard routes failed: {e}")

    # Register Content Intelligence blueprint
    if CONTENT_INTELLIGENCE_AVAILABLE:
        try:
            app.register_blueprint(content_bp)
            logger.info("✅ Content Intelligence dashboard registered at /content-intelligence")
        except Exception as e:
            logger.warning(f"Content Intelligence registration failed: {e}")

    logger.info(f"Bot initialized with model: {settings.claude_model}")


def handle_slash_command(command: str, args: str, user_id: str, space_name: str, user_email: str = "", user_display_name: str = "") -> str | None:
    """Handle slash commands from users."""
    command = command.lower().strip()

    if command == "/help":
        lines = ["📋 **Available Commands:**"]
        for cmd, desc in SLASH_COMMANDS.items():
            lines.append(f"  `{cmd}` - {desc}")
        return "\n".join(lines)

    elif command == "/correct":
        if not knowledge_base:
            return "\u26a0\ufe0f Knowledge capture is not configured."

        # Check admin whitelist
        is_admin = user_email.lower() in ADMIN_EMAILS if user_email else False

        if not is_admin:
            return ("\u26d4 `/correct` is admin-only. Your correction won't take effect immediately.\n\n"
                    "Use `/suggest` instead \u2014 it logs your correction for admin review.\n\n"
                    "Usage: `/suggest <what was wrong> | <correct answer>`")

        if "|" not in args:
            return "\u274c Usage: `/correct <what was wrong> | <correct answer>`\n\nExample: `/correct Claude said MCI is 6% | MCI increases are capped at 2% since 2019`"

        parts = args.split("|", 1)
        wrong = parts[0].strip()
        correct = parts[1].strip()

        if not wrong or not correct:
            return "\u274c Please provide both the wrong response and the correct answer."

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
        logger.info(f"Correction captured by {user_email or user_id}: {entry.entry_id}")

        # Log to analytics
        if analytics_db and ANALYTICS_AVAILABLE:
            try:
                analytics_db.log_correction(
                    user_id=user_id,
                    user_name=user_display_name or user_email or "Unknown User",
                    wrong=wrong,
                    correct=correct,
                    topics=topics or ["General"],
                )
            except Exception as e:
                logger.error(f"Failed to log correction: {e}")

        return f"✅ **Correction captured!**\n\n**Wrong:** {wrong[:100]}{'...' if len(wrong) > 100 else ''}\n**Correct:** {correct[:150]}{'...' if len(correct) > 150 else ''}\n\nTopics: {', '.join(topics or ['General'])}"

    elif command == "/suggest":
        if not knowledge_base:
            return "\u26a0\ufe0f Knowledge capture is not configured."

        if "|" not in args:
            return ("\u274c Usage: `/suggest <what was wrong> | <correct answer>`\n\n"
                    "Example: `/suggest Beacon said the fee is $305 | The fee increased to $485 as of Feb 2, 2026`")

        parts = args.split("|", 1)
        wrong = parts[0].strip()
        suggested = parts[1].strip()

        if not wrong or not suggested:
            return "\u274c Please provide both the issue and your suggested correction."

        topics = []
        topic_keywords = {
            "DOB": ["dob", "building", "permit", "violation", "certificate"],
            "DHCR": ["dhcr", "rent", "stabiliz", "mci", "iai", "lease"],
            "Zoning": ["zoning", "use group", "far", "setback", "variance"],
            "HPD": ["hpd", "housing", "habitability"],
        }
        combined = (wrong + " " + suggested).lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                topics.append(topic)

        entry = knowledge_base.add_qa(
            question=f"SUGGESTION from {user_email or user_id}: {wrong}",
            answer=suggested,
            context="Pending admin review via /correct",
            topics=topics or ["General"],
            source="suggestion",
        )
        logger.info(f"Suggestion captured by {user_email or user_id}: {entry.entry_id}")

        # Log to analytics
        if analytics_db and ANALYTICS_AVAILABLE:
            try:
                # Auto-capture context from last interaction
                context_info = ""
                if analytics_db:
                    try:
                        recent = analytics_db.get_recent_conversations(limit=1, user_id=user_id)
                        if recent and len(recent) > 0:
                            last_q = recent[0]
                            context_info = (
                                f"\n\n─── CONTEXT ───\n"
                                f"Original Question: {last_q['question']}\n"
                                f"Beacon's Response: {last_q['response'][:300]}...\n"
                                f"───────────────"
                            )
                    except Exception as e:
                        logger.warning(f"Could not capture context: {e}")
                
                analytics_db.log_suggestion(
                    user_id=user_id,
                    user_name=user_display_name or user_email or "Unknown User",
                    wrong=wrong + context_info,
                    correct=suggested,
                    topics=topics or ["General"],
                )
            except Exception as e:
                logger.error(f"Failed to log suggestion: {e}")

        return (f"📝 **Suggestion logged for review!**\n\n"
                f"**Issue:** {wrong[:100]}{'...' if len(wrong) > 100 else ''}\n"
                f"**Suggested fix:** {suggested[:150]}{'...' if len(suggested) > 150 else ''}\n\n"
                f"An admin will review and approve this. Thanks for flagging it!")

    elif command == "/tip":
        if not knowledge_base:
            return "⚠️ Knowledge capture is not configured."

        if not args.strip():
            return "❌ Usage: `/tip <your tip>`\n\nExample: `/tip Always check BIS for the latest CO before filing`"

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

        return f"✅ **Tip captured!** Thanks for sharing your knowledge.\n\n💡 {args.strip()}"

    elif command == "/lookup":
        if not nyc_data_client:
            return "⚠️ NYC Open Data is not configured."

        if "," not in args:
            return "❌ Usage: `/lookup <address>, <borough>`\n\nExample: `/lookup 123 Main Street, Brooklyn`"

        parts = args.rsplit(",", 1)
        address = parts[0].strip()
        borough = parts[1].strip()

        if not address or not borough:
            return "❌ Please provide both address and borough."

        try:
            property_info = nyc_data_client.get_property_info(address, borough)
            return property_info.to_context_string()
        except Exception as e:
            logger.error(f"Property lookup failed: {e}")
            return f"❌ Could not find property: {address}, {borough}"

    elif command == "/zoning":
        if not zoning_analyzer:
            return "⚠️ Zoning analyzer is not configured."

        if "," not in args:
            return "❌ Usage: `/zoning <address>, <borough>`\n\nExample: `/zoning 2410 White Plains Rd, Bronx`"

        parts = args.rsplit(",", 1)
        address = parts[0].strip()
        borough = parts[1].strip()

        if not address or not borough:
            return "❌ Please provide both address and borough."

        try:
            analysis = zoning_analyzer.analyze(address, borough)
            return analysis.to_report()
        except Exception as e:
            logger.error(f"Zoning analysis failed: {e}")
            return f"❌ Zoning analysis failed for: {address}, {borough}\n\nError: {str(e)[:100]}"

    elif command == "/objections":
        if not objections_kb:
            return "⚠️ Objections knowledge base is not configured."

        if not args.strip():
            return "❌ Usage: `/objections <filing type>`\n\nExamples:\n  `/objections ALT1`\n  `/objections ALT2`\n  `/objections NB`\n  `/objections DM`"

        filing_type = args.strip().upper()
        return get_objections_response(filing_type)

    elif command == "/plans":
        if PLAN_READER_AVAILABLE:
            return get_plan_capabilities()
        else:
            return "⚠️ Plan reader module is not available."

    elif command == "/stats":
        lines = ["📊 **Bot Statistics:**"]

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
        lines.append(f"**NYC Open Data:** {'✅' if nyc_data_client else '❌'}")
        lines.append(f"**Zoning Analyzer:** {'✅' if zoning_analyzer else '❌'}")

        return "\n".join(lines)

    elif command == "/usage":
        if not usage_tracker:
            return "⚠️ Usage tracking is not configured."

        usage = usage_tracker.get_usage_summary(user_id)
        return f"""📈 **Your Usage Today:**

  Requests: {usage['requests_today']}
  Remaining: {usage['requests_remaining_today']}
  Tokens used: {usage['tokens_today']:,}
  Cost: ${usage['cost_today']:.4f}

Daily limits: 100 requests, 100K tokens"""

    elif command == "/feedback":
        if not analytics_db:
            return "⚠️ Feedback tracking is not configured."
        
        if not args.strip():
            return "❌ Usage: `/feedback <your feedback>`\n\nExample: `/feedback Can we add permit expiration dates to /lookup?`"
        
        try:
            from datetime import datetime
            feedback_id = analytics_db.log_feedback(
                user_id=user_id,
                user_name=user_display_name or user_email or "Unknown User",
                feedback=args.strip(),
            )
            logger.info(f"Feedback {feedback_id} captured from {user_id}")
            return f"✅ **Feedback received!** Thanks for helping us improve Beacon.\n\n💡 {args.strip()}"
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")
            return "❌ Sorry, couldn't save your feedback. Please try again."


    return None  # Not a recognized command


def process_message_async(
    user_id: str,
    user_display_name: str,
    space_name: str,
    user_message: str,
    temp_message_name: str | None,
) -> None:
    """Process a message in a background thread."""
    request_start_time = time.time()
    
    try:
        # Small delay to ensure temp message is sent
        time.sleep(0.3)

        # === RATE LIMITING CHECK ===
        if usage_tracker and RATE_LIMITER_AVAILABLE:
            allowed, limit_msg = usage_tracker.check_limits(user_id)
            if not allowed:
                if temp_message_name:
                    chat_client.update_message(temp_message_name, f"⚠️ {limit_msg}")
                else:
                    chat_client.send_message(space_name, f"⚠️ {limit_msg}")
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

        # === CHECK FOR PROPERTY LOOKUP (skip RAG/LLM — return data directly) ===
        is_property_query = False
        ai_response = None
        if nyc_data_client is not None and OPEN_DATA_AVAILABLE:
            try:
                address_info = extract_address_from_query(user_message)
                if address_info:
                    address, borough = address_info
                    logger.info(f"Detected property query: {address}, {borough}")
                    property_info = nyc_data_client.get_property_info(address, borough)
                    ai_response = property_info.to_context_string()
                    is_property_query = True
                    logger.info(f"Property lookup — no LLM call needed")
            except Exception as e:
                logger.warning(f"Property lookup failed: {e}")

        # === STANDARD RAG + LLM FLOW (only if not a property lookup) ===
        if not is_property_query:
            rag_context = None
            rag_sources = None
            objections_context = None

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
            if objections_context:
                context_parts.append(f"RELEVANT OBJECTIONS:\n{objections_context}")
            if rag_context:
                context_parts.append(f"RELEVANT DOCUMENTS:\n{rag_context}")
            if context_parts:
                combined_context = "\n\n---\n\n".join(context_parts)

            # === GET RESPONSE FROM CLAUDE ===
            from core.llm_client import route_model
            selected_model = route_model(user_message, has_rag_context=bool(combined_context))
            ai_response, model_used = claude_client.get_response(
                user_message=user_message,
                conversation_history=session.chat_history,
                rag_context=combined_context,
                rag_sources=rag_sources,
                model_override=selected_model,
            )
            logger.info(f"Model routing: {model_used} for '{user_message[:50]}...'")

        # === TRACK USAGE ===
        if usage_tracker and RATE_LIMITER_AVAILABLE:
            if is_property_query:
                # Property lookups are free (no LLM call)
                usage_tracker.record_usage(
                    user_id=user_id,
                    input_tokens=0,
                    output_tokens=0,
                    cost=0.0,
                    feature="property_lookup"
                )
            else:
                # Estimate tokens (rough: 4 chars per token)
                input_tokens = len(user_message + (combined_context or "")) // 4
                output_tokens = len(ai_response) // 4
                cost = calculate_cost(model_used, input_tokens, output_tokens)

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

        # === LOG TO ANALYTICS ===
        if analytics_db:
            try:
                from datetime import datetime

                # Calculate metrics
                response_time = int((time.time() - request_start_time) * 1000)
                has_sources = bool(rag_sources)

                # Estimate tokens (rough: 4 chars = 1 token)
                tokens_used = (len(user_message) + len(ai_response)) // 4

                # Estimate cost (Haiku: ~$0.25 per 1M input, ~$1.25 per 1M output)
                cost_usd = (tokens_used / 1_000_000) * 0.75

                interaction = Interaction(
                    timestamp=datetime.now().isoformat(),
                    user_id=user_id,
                    user_name=user_display_name or "Unknown User",
                    space_name=space_name or "DM",
                    question=user_message,
                    response=ai_response,
                    command=None,
                    answered=True,
                    response_length=len(ai_response),
                    had_sources=has_sources,
                    sources_used=json.dumps([s.get('file', '') for s in rag_sources]) if rag_sources else None,
                    tokens_used=tokens_used,
                    cost_usd=cost_usd,
                    response_time_ms=response_time,
                    confidence=None,
                    topic=None,  # Auto-categorized by analytics v2
                )

                analytics_db.log_interaction(interaction)
                logger.info(f"Logged interaction to analytics (backend={'supabase' if SUPABASE_ANALYTICS else 'sqlite'})")
            except Exception as e:
                logger.error(f"Failed to log analytics: {e}", exc_info=True)

        # === SEND RESPONSE ===
        if not ai_response:
            ai_response = "I wasn't able to generate a response. Please try again."

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
        user_email = user_data.get("email", "")
        user_display_name = user_data.get("displayName", user_email or "Unknown User")
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

            response = handle_slash_command(command, args, user_id, space_name, user_email=user_email, user_display_name=user_display_name)
            if response:
                # Log slash command to analytics
                if analytics_db:
                    try:
                        interaction = Interaction(
                            timestamp=datetime.now().isoformat(),
                            user_id=user_id,
                            user_name=user_display_name or user_email or "Unknown",
                            space_name=space_name,
                            question=user_message,
                            response=response[:500],  # Truncate for storage
                            command=command,
                            answered=True,
                            response_length=len(response),
                            had_sources=False,
                            sources_used=None,
                            tokens_used=0,
                            cost_usd=0.0,
                            response_time_ms=0,
                            confidence=None,
                            topic="COMMAND"
                        )
                        analytics_db.log_interaction(interaction)
                    except Exception as e:
                        logger.error(f"Failed to log slash command to analytics: {e}")
                
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
            args=(user_id, user_display_name, space_name, user_message, temp_message_name),
            daemon=True,
        )
        thread.start()

        return "", 204

    except Exception as e:
        logger.exception(f"Error in webhook handler: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Web API chat endpoint for Ordino's Ask Beacon widget.
    Processes questions synchronously (no Google Chat) and returns structured JSON.
    """
    request_start_time = time.time()

    try:
        data = request.get_json() or {}
        user_message = data.get("message", "").strip()
        user_id = data.get("user_id", "web-user")
        user_name = data.get("user_name", "Web User")
        space_id = data.get("space_id", "ordino-web")

        if not user_message:
            return jsonify({"error": "No message provided"}), 400

        logger.info(f"[API Chat] {user_name} ({user_id}): {user_message[:100]}")

        # === SLASH COMMAND HANDLING ===
        if user_message.startswith("/"):
            parts = user_message.split(maxsplit=1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""

            response = handle_slash_command(
                command, args, user_id, space_id,
                user_email=data.get("user_email", ""),
                user_display_name=user_name,
            )
            if response:
                response_time_ms = int((time.time() - request_start_time) * 1000)
                # Log slash command to analytics
                if analytics_db:
                    try:
                        interaction = Interaction(
                            timestamp=datetime.now().isoformat(),
                            user_id=user_id,
                            user_name=user_name,
                            space_name=space_id,
                            question=user_message,
                            response=response[:500],
                            command=command,
                            answered=True,
                            response_length=len(response),
                            had_sources=False,
                            sources_used=None,
                            tokens_used=0,
                            cost_usd=0.0,
                            response_time_ms=response_time_ms,
                            confidence=None,
                            topic="COMMAND",
                        )
                        analytics_db.log_interaction(interaction)
                    except Exception as e:
                        logger.error(f"[API Chat] Failed to log slash command: {e}")

                return jsonify({
                    "response": response,
                    "confidence": 1.0,
                    "sources": [],
                    "flow_type": "command",
                    "cached": False,
                    "response_time_ms": response_time_ms,
                })

        # === OFF-TOPIC FILTER ===
        if RATE_LIMITER_AVAILABLE:
            off_topic, reason = is_off_topic(user_message)
            if off_topic:
                return jsonify({
                    "response": get_off_topic_response(),
                    "confidence": 0.0,
                    "sources": [],
                    "flow_type": "off_topic",
                    "cached": False,
                    "response_time_ms": int((time.time() - request_start_time) * 1000)
                })

        # === CHECK CACHE ===
        if response_cache and CACHE_AVAILABLE:
            cached = response_cache.get(user_message)
            if cached:
                logger.info(f"[API Chat] Cache hit for: {user_message[:50]}")
                return jsonify({
                    "response": cached,
                    "confidence": 0.85,
                    "sources": [],
                    "flow_type": "cache",
                    "cached": True,
                    "response_time_ms": int((time.time() - request_start_time) * 1000)
                })

        # === PROPERTY LOOKUP (gather data as context for Claude) ===
        ai_response = None
        flow_type = "rag_llm"
        rag_sources_list = []
        confidence = 0.0
        property_context = None

        if nyc_data_client is not None and OPEN_DATA_AVAILABLE:
            try:
                address_info = extract_address_from_query(user_message)
                if address_info:
                    address, borough = address_info
                    property_info = nyc_data_client.get_property_info(address, borough)
                    property_context = property_info.to_context_string()
                    flow_type = "property_lookup"
                    confidence = 0.95
                    logger.info(f"[API Chat] Property data found for {address}, {borough}")
            except Exception as e:
                logger.warning(f"[API Chat] Property lookup failed: {e}")

        # === RAG + LLM (always run through Claude for web API) ===
        rag_context = None
        rag_sources = None
        objections_context = None

        # Objections context
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
                    top_k=settings.rag_top_k if settings else 5,
                    min_score=settings.rag_min_score if settings else 0.3,
                )
                if retrieval_result.num_results > 0:
                    rag_context = retrieval_result.context
                    rag_sources = retrieval_result.sources

                    # Build sources list for response
                    for src in (rag_sources or []):
                        rag_sources_list.append({
                            "title": src.get("file", src.get("title", "Unknown")),
                            "score": src.get("score", 0.0),
                            "chunk_preview": src.get("text", "")[:200]
                        })

                    # Confidence from avg source score
                    if rag_sources_list:
                        confidence = sum(s["score"] for s in rag_sources_list) / len(rag_sources_list)
            except Exception as e:
                logger.warning(f"[API Chat] RAG retrieval failed: {e}")

        # Combine all context (property data + objections + RAG docs)
        context_parts = []
        if property_context:
            context_parts.append(f"LIVE PROPERTY DATA (from NYC Open Data):\n{property_context}")
        if objections_context:
            context_parts.append(f"RELEVANT OBJECTIONS:\n{objections_context}")
        if rag_context:
            context_parts.append(f"RELEVANT DOCUMENTS:\n{rag_context}")
        combined_context = "\n\n---\n\n".join(context_parts) if context_parts else None

        # Get session history for context
        session = session_manager.get_or_create_session(user_id, space_id) if session_manager else None

        # Add user message to session BEFORE calling Claude
        # (so it's included in conversation_history like the webhook flow)
        if session_manager:
            session_manager.add_user_message(user_id, space_id, user_message)

        chat_history = session.chat_history if session else []

        # Route to appropriate model based on question complexity
        from core.llm_client import route_model
        selected_model = route_model(
            user_message,
            has_rag_context=bool(combined_context),
            flow_type=flow_type,
        )

        # Call Claude (format_for="web" preserves full markdown for Ordino widget)
        ai_response, model_used = claude_client.get_response(
            user_message=user_message,
            conversation_history=chat_history,
            rag_context=combined_context,
            rag_sources=rag_sources,
            format_for="web",
            model_override=selected_model,
        )
        logger.info(f"[API Chat] Model routing: {model_used} for '{user_message[:50]}...'")

        # Store assistant response in session
        if session_manager:
            session_manager.add_assistant_message(user_id, space_id, ai_response)

        # === CACHE RESPONSE ===
        if response_cache and CACHE_AVAILABLE:
            response_cache.set(user_message, ai_response)

        # === LOG TO ANALYTICS ===
        response_time_ms = int((time.time() - request_start_time) * 1000)

        if analytics_db:
            try:
                input_tokens = len(user_message + (combined_context or "")) // 4
                output_tokens = len(ai_response) // 4
                tokens_used = input_tokens + output_tokens
                # Use rate_limiter's accurate per-model pricing
                from core.rate_limiter import calculate_cost
                cost_usd = calculate_cost(model_used, input_tokens, output_tokens)

                interaction = Interaction(
                    timestamp=datetime.now().isoformat(),
                    user_id=user_id,
                    user_name=user_name,
                    space_name=space_id,
                    question=user_message,
                    response=ai_response,
                    command=None,
                    answered=True,
                    response_length=len(ai_response),
                    had_sources=bool(rag_sources_list),
                    sources_used=json.dumps([s["title"] for s in rag_sources_list]) if rag_sources_list else None,
                    tokens_used=tokens_used,
                    cost_usd=cost_usd,
                    response_time_ms=response_time_ms,
                    confidence=confidence,
                    topic=None,
                )
                analytics_db.log_interaction(interaction)
                logger.info(f"[API Chat] Logged to analytics (backend={'supabase' if SUPABASE_ANALYTICS else 'sqlite'})")
            except Exception as e:
                logger.error(f"[API Chat] Analytics logging failed: {e}", exc_info=True)

        return jsonify({
            "response": ai_response or "I wasn't able to generate a response. Please try again.",
            "confidence": confidence,
            "sources": rag_sources_list,
            "flow_type": flow_type,
            "cached": False,
            "response_time_ms": response_time_ms,
            "model": model_used,
        })

    except Exception as e:
        logger.exception(f"[API Chat] Error: {e}")
        return jsonify({
            "error": str(e),
            "response": "I encountered an error processing your request. Please try again.",
            "confidence": 0.0,
            "sources": [],
            "flow_type": "error",
            "cached": False,
            "response_time_ms": int((time.time() - request_start_time) * 1000)
        }), 500


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
def analytics():
    """Redirect to OAuth-protected dashboard."""
    return redirect(url_for('dashboard'))


@app.route("/analytics-data", methods=["GET"])
def analytics_data() -> tuple[Response, int]:
    """JSON endpoint for analytics data."""
    analytics_data = {
        "status": "ok",
    }

    if usage_tracker:
        analytics_data["usage"] = usage_tracker.get_daily_totals()

    if response_cache:
        analytics_data["cache"] = response_cache.get_cache_stats()
        analytics_data["top_questions"] = response_cache.get_top_questions(20)

    return jsonify(analytics_data), 200


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    """Analytics API for Ordino's admin panel.
    Returns Beacon usage stats, costs, and activity so Ordino can display
    Beacon AI costs alongside Gemini costs in the AI Usage page.

    Query params:
        days: Number of days to look back (default: 30)
        start_date: ISO format start date (alternative to days)
        end_date: ISO format end date
    """
    try:
        days = request.args.get("days", 30, type=int)
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        if not analytics_db:
            return jsonify({"error": "Analytics not available (no analytics backend configured)"}), 503

        stats = analytics_db.get_stats(
            days=days if not start_date else None,
            start_date=start_date,
            end_date=end_date,
        )

        # Reshape for Ordino's AI Usage page
        return jsonify({
            "provider": "anthropic",
            "service": "beacon",
            "period_days": days,
            "total_requests": stats["total_questions"],
            "total_cost_usd": stats["total_cost_usd"],
            "success_rate": stats["success_rate"],
            "active_users": stats["active_users"],
            "avg_response_time_ms": stats["response_time"]["avg_ms"],
            "cost_breakdown": stats["api_costs"],
            "top_users": stats["top_users"],
            "topics": stats["topics"],
            "daily_usage": stats.get("daily_usage", []),
        })

    except Exception as e:
        logger.exception(f"[API Analytics] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """Ingest a document into the Beacon knowledge base (Pinecone).

    Accepts:
      - JSON with {text, title, source_type, metadata} for markdown/text content
      - multipart/form-data with file upload (PDF or markdown) + optional source_type

    Called by Ordino when a document is uploaded to the Beacon Knowledge Base folder.
    Also used by the email ingestion pipeline.
    """
    try:
        if retriever is None or not RAG_AVAILABLE:
            return jsonify({"error": "RAG not configured (missing Pinecone/Voyage keys)"}), 503

        from ingestion.document_processor import DocumentProcessor, detect_document_type
        from core.vector_store import VectorStore
        import tempfile
        import os

        processor = DocumentProcessor()
        vector_store = retriever.vector_store

        # Check if it's a file upload or JSON text
        if request.content_type and "multipart/form-data" in request.content_type:
            # File upload
            if "file" not in request.files:
                return jsonify({"error": "No file provided"}), 400

            file = request.files["file"]
            filename = file.filename or "unknown.md"
            source_type = request.form.get("source_type", "")
            folder_hint = request.form.get("folder", "")

            ext = os.path.splitext(filename)[1].lower()
            if ext not in {".pdf", ".md", ".txt"}:
                return jsonify({"error": f"Unsupported file type: {ext}. Use .pdf, .md, or .txt"}), 400

            # Auto-detect source type from folder hint or filename
            if not source_type:
                if "service_notice" in folder_hint.lower() or "service" in folder_hint.lower():
                    source_type = "service_notice"
                elif "bulletin" in folder_hint.lower():
                    source_type = "technical_bulletin"
                elif "policy" in folder_hint.lower():
                    source_type = "policy_memo"
                elif "guide" in folder_hint.lower() or "process" in folder_hint.lower():
                    source_type = "procedure"
                elif "zoning" in folder_hint.lower():
                    source_type = "zoning"
                elif "code" in folder_hint.lower():
                    source_type = "building_code"
                elif "case" in folder_hint.lower() or "historical" in folder_hint.lower():
                    source_type = "historical_determination"
                else:
                    source_type = detect_document_type(filename)

            # Save to temp file and process
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                file.save(tmp.name)
                tmp_path = tmp.name

            try:
                if ext == ".pdf":
                    document = processor.process_pdf(tmp_path, source_type=source_type)
                else:
                    text = open(tmp_path, "r", encoding="utf-8").read()
                    from ingestion.ingest import extract_md_metadata
                    metadata = extract_md_metadata(text) if ext == ".md" else {}
                    metadata["file_path"] = filename
                    document = processor.process_text(
                        text=text,
                        title=metadata.get("title", os.path.splitext(filename)[0]),
                        source_type=source_type,
                        metadata=metadata,
                    )
            finally:
                os.unlink(tmp_path)

        else:
            # JSON text submission
            data = request.get_json() or {}
            text = data.get("text", "").strip()
            title = data.get("title", "Untitled")
            source_type = data.get("source_type", "document")
            metadata = data.get("metadata", {})

            if not text:
                return jsonify({"error": "No text provided"}), 400

            document = processor.process_text(
                text=text,
                title=title,
                source_type=source_type,
                metadata=metadata,
            )

        # Upload chunks to Pinecone
        count = vector_store.upsert_chunks(document.chunks)

        logger.info(f"[API Ingest] Ingested {count} chunks from '{document.title}' (type={source_type})")

        return jsonify({
            "success": True,
            "title": document.title,
            "source_type": source_type,
            "chunks_created": count,
            "total_characters": len(document.content),
        })

    except Exception as e:
        logger.exception(f"[API Ingest] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingest-email", methods=["POST"])
def api_ingest_email():
    """Process a forwarded DOB newsletter email.

    Accepts JSON with {html_content} — the raw HTML of a DOB Buildings News email.
    Parses the newsletter, ingests each update into the knowledge base,
    and feeds them to the Content Intelligence engine.

    This endpoint can be called by:
      - SendGrid Inbound Parse webhook
      - Mailgun Routes webhook
      - A scheduled task that checks Gmail for DOB newsletters
    """
    try:
        data = request.get_json() or {}
        html_content = data.get("html_content", "").strip()

        if not html_content:
            return jsonify({"error": "No html_content provided"}), 400

        # Parse the newsletter
        from content_engine.parser import DOBNewsletterParser
        parser = DOBNewsletterParser()
        result = parser.parse_email(html_content)

        updates = result.get("updates", [])
        newsletter_date = result.get("newsletter_date", "unknown")

        if not updates:
            return jsonify({
                "success": True,
                "message": "No updates found in newsletter",
                "newsletter_date": newsletter_date,
                "updates_processed": 0,
            })

        ingested = []
        content_candidates = []

        for update in updates:
            title = update.get("title", "Untitled Update")
            summary = update.get("summary", "")
            full_content = update.get("full_content", summary)
            category = update.get("category", "General")
            source_url = update.get("source_url", "")

            # Map category to source type for chunking
            category_to_type = {
                "Service Updates": "service_notice",
                "Local Laws": "policy_memo",
                "Buildings Bulletins": "technical_bulletin",
                "Hearings": "policy_memo",
                "Rules": "policy_memo",
                "Weather": "service_notice",
                "Code Notes": "building_code",
            }
            source_type = category_to_type.get(category, "service_notice")

            # 1) Ingest into Pinecone (so Beacon learns about it)
            if retriever is not None and RAG_AVAILABLE and full_content:
                try:
                    from ingestion.document_processor import DocumentProcessor
                    processor = DocumentProcessor()

                    # Build markdown content with metadata header
                    md_content = f"""Title: {title}
Category: {category}
Date Issued: {newsletter_date}
Source URL: {source_url}
Type: {source_type}

# {title}

{full_content}
"""
                    document = processor.process_text(
                        text=md_content,
                        title=title,
                        source_type=source_type,
                        metadata={
                            "category": category,
                            "date_issued": newsletter_date,
                            "source_url": source_url,
                        },
                    )

                    count = retriever.vector_store.upsert_chunks(document.chunks)
                    ingested.append({"title": title, "chunks": count})
                    logger.info(f"[Email Ingest] Ingested '{title}' → {count} chunks")
                except Exception as e:
                    logger.error(f"[Email Ingest] Failed to ingest '{title}': {e}")

            # 2) Feed to Content Intelligence engine (for blog/newsletter generation)
            try:
                from content_engine.engine import ContentEngine
                engine = ContentEngine()
                candidate = engine.analyze_update(title, summary or full_content[:500], source_url)
                content_candidates.append({
                    "id": candidate.id,
                    "title": candidate.title,
                    "priority": candidate.priority,
                    "content_type": candidate.content_type,
                })
                logger.info(f"[Email Ingest] Content candidate created: '{candidate.title}' ({candidate.priority})")
            except Exception as e:
                logger.error(f"[Email Ingest] Content engine failed for '{title}': {e}")

        return jsonify({
            "success": True,
            "newsletter_date": newsletter_date,
            "updates_found": len(updates),
            "updates_ingested": len(ingested),
            "content_candidates_created": len(content_candidates),
            "ingested": ingested,
            "content_candidates": content_candidates,
        })

    except Exception as e:
        logger.exception(f"[Email Ingest] Error: {e}")
        return jsonify({"error": str(e)}), 500


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


# ------------------------------------------------------------------
# Knowledge Base file serving (for Ordino document seeding)
# ------------------------------------------------------------------

@app.route("/api/knowledge/list", methods=["GET"])
def list_knowledge_files():
    """List all knowledge base markdown files for Ordino seeding."""
    import os

    files = []
    kb_root = os.path.join(os.path.dirname(__file__), "knowledge")
    if not os.path.isdir(kb_root):
        return jsonify({"files": [], "count": 0})

    for root, _dirs, filenames in os.walk(kb_root):
        for f in filenames:
            if f.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, f), kb_root)
                files.append(rel_path)

    files.sort()
    return jsonify({"files": files, "count": len(files)})


@app.route("/api/knowledge/<path:filepath>", methods=["GET"])
def serve_knowledge_file(filepath):
    """Serve a single knowledge base file for Ordino document seeding."""
    import os

    safe_path = os.path.normpath(filepath)
    if ".." in safe_path:
        return jsonify({"error": "Invalid path"}), 400

    # Add .md extension if not present
    if not safe_path.endswith(".md"):
        safe_path += ".md"

    kb_root = os.path.join(os.path.dirname(__file__), "knowledge")
    full_path = os.path.join(kb_root, safe_path)

    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    return jsonify({
        "filename": os.path.basename(full_path),
        "folder": os.path.dirname(safe_path),
        "content": content,
        "size": len(content),
    })


# Initialize when imported by gunicorn (production)
initialize_app()

if __name__ == "__main__":
    main()# Add this to bot_v2.py - Public analytics page (no OAuth)

ANALYTICS_PUBLIC_HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Beacon Analytics</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg: #f8fafc;
            --card: #ffffff;
            --border: #e2e8f0;
            --text: #0f172a;
            --text-muted: #64748b;
            --primary: #f59e0b;
            --success: #22c55e;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 32px 24px;
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            margin-bottom: 32px;
            text-align: center;
        }
        .header h1 {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .header p {
            font-size: 14px;
            color: var(--text-muted);
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            transition: all 0.2s;
        }
        .card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            transform: translateY(-2px);
        }
        .card-label {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .card-value {
            font-size: 36px;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 4px;
        }
        .card-sublabel {
            font-size: 12px;
            color: var(--text-muted);
        }
        .section {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }
        .section h2 {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 20px;
        }
        .question-item {
            padding: 16px;
            border-bottom: 1px solid var(--border);
        }
        .question-item:last-child {
            border-bottom: none;
        }
        .question-text {
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 8px;
        }
        .question-meta {
            display: flex;
            gap: 16px;
            font-size: 12px;
            color: var(--text-muted);
        }
        .badge {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            background: #fef3c7;
            color: var(--primary);
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 Beacon Analytics</h1>
        <p>Real-time bot performance metrics</p>
    </div>
    
    <div class="grid">
        <div class="card">
            <div class="card-label">Total Requests</div>
            <div class="card-value" id="total-requests">-</div>
            <div class="card-sublabel">Today</div>
        </div>
        
        <div class="card">
            <div class="card-label">Active Users</div>
            <div class="card-value" id="active-users">-</div>
            <div class="card-sublabel">Unique today</div>
        </div>
        
        <div class="card">
            <div class="card-label">API Cost</div>
            <div class="card-value" id="total-cost">$0.00</div>
            <div class="card-sublabel">Today</div>
        </div>
        
        <div class="card">
            <div class="card-label">Cache Hit Rate</div>
            <div class="card-value" id="cache-rate">-%</div>
            <div class="card-sublabel" id="cache-entries">-</div>
        </div>
    </div>
    
    <div class="section">
        <h2>🔥 Top Questions</h2>
        <div id="top-questions">
            <div style="text-align: center; padding: 40px; color: var(--text-muted);">
                Loading...
            </div>
        </div>
    </div>
    
    <script>
        async function loadAnalytics() {
            try {
                const response = await fetch('/analytics-data');
                const data = await response.json();
                
                // Update metrics
                document.getElementById('total-requests').textContent = data.usage?.total_requests || 0;
                document.getElementById('active-users').textContent = data.usage?.active_users || 0;
                document.getElementById('total-cost').textContent = '$' + (data.usage?.total_cost || 0).toFixed(4);
                
                const cacheRate = data.cache?.hit_rate || 0;
                document.getElementById('cache-rate').textContent = (cacheRate * 100).toFixed(0) + '%';
                document.getElementById('cache-entries').textContent = (data.cache?.total_entries || 0) + ' entries cached';
                
                // Render top questions
                const container = document.getElementById('top-questions');
                if (data.top_questions && data.top_questions.length > 0) {
                    container.innerHTML = data.top_questions.slice(0, 10).map(q => `
                        <div class="question-item">
                            <div class="question-text">${q.question}</div>
                            <div class="question-meta">
                                <span class="badge">${q.category || 'general'}</span>
                                <span>Asked ${q.count}× today</span>
                                <span>Last: ${new Date(q.last_asked).toLocaleTimeString()}</span>
                            </div>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-muted);">No questions yet today</div>';
                }
                
            } catch (error) {
                console.error('Failed to load analytics:', error);
            }
        }
        
        loadAnalytics();
        setInterval(loadAnalytics, 30000); // Refresh every 30s
    </script>
</body>
</html>'''




