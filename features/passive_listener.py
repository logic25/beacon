"""
Beacon Passive Listener — Monitors Google Chat spaces for relevant
questions even without @Beacon mention.

Behavior:
1. Polls the space for new messages every POLL_INTERVAL seconds
2. Classifies each message as a relevant question (zero API cost)
3. Logs relevant questions as content opportunities
4. After RESPONSE_DELAY seconds, checks if anyone answered in-thread
5. If unanswered → Beacon offers help with a RAG-powered response
6. If answered → stays quiet, keeps content log only

Requires:
- Google Chat API `chat.bot` scope (already configured)
- Beacon must be a member of the monitored space
- PASSIVE_LISTEN_SPACE env var set to the space name (e.g. "spaces/AAAAo1CRec0")
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# How often to poll for new messages (seconds)
POLL_INTERVAL = int(os.getenv("PASSIVE_POLL_INTERVAL", "120"))  # 2 min default

# How long to wait before checking if a question was answered (seconds)
RESPONSE_DELAY = int(os.getenv("PASSIVE_RESPONSE_DELAY", "900"))  # 15 min default

# Maximum messages to fetch per poll
POLL_PAGE_SIZE = int(os.getenv("PASSIVE_POLL_PAGE_SIZE", "50"))

# ---------------------------------------------------------------------------
# Question Detection (zero API cost — keyword + pattern based)
# ---------------------------------------------------------------------------

# Question-starting patterns
QUESTION_PATTERNS = [
    r"^(how|what|where|when|who|why|which|can|could|does|do|is|are|has|have|should|would|will)\b",
    r"\?$",  # ends with question mark
    r"^(anyone|anybody|someone|somebody)\s+(know|have|seen|dealt with|experience)",
    r"^(has anyone|have any of you|do we|does anyone|did anyone)",
    r"^(i need|i\'m looking for|looking for|trying to find|need help with)",
    r"^(what\'s the|whats the|what is the)\s+(process|procedure|status|timeline|requirement)",
]

# Keywords relevant to GLE's business (NYC expediting / real estate)
BUSINESS_KEYWORDS = [
    # Filing types
    "alt1", "alt2", "alt3", "alt-1", "alt-2", "alt-3",
    "nb", "dm", "sign", "paa",
    # Agencies & processes
    "dob", "dhcr", "hpd", "fdny", "ecb", "oath", "bsa",
    "dep", "dot", "lpc", "city planning",
    "violation", "violations", "complaint",
    "permit", "permits", "filing", "filings",
    "inspection", "inspections", "inspector",
    "certificate of occupancy", "c of o", "tco", "cco",
    "letter of completion", "loc",
    "plan examiner", "plan exam",
    "objection", "objections",
    "zoning", "variance", "bsa",
    "scaffold", "sidewalk shed", "construction fence",
    "asbestos", "ahu-5", "ahu5",
    "boiler", "elevator", "sprinkler", "standpipe",
    "facade", "fisp", "ll11",
    "gas", "plumbing", "electrical",
    # Rent / DHCR
    "rent stabilized", "rent stabilization", "dhcr",
    "mci", "iac", "preferential rent",
    "lease", "tenant", "landlord",
    # General process
    "expediter", "expediting", "expeditor",
    "how long", "timeline", "turnaround",
    "fee", "fees", "cost",
    "renewal", "renew",
    "borough office", "hub",
    "now hub", "bis", "dob now",
]

# Compiled patterns for efficiency
_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in QUESTION_PATTERNS]
_keyword_set = set(kw.lower() for kw in BUSINESS_KEYWORDS)


def is_relevant_question(text: str) -> tuple[bool, str]:
    """Classify if a message is a relevant, work-related question.

    Returns (is_relevant, reason) — no API calls, zero cost.
    """
    if not text or len(text) < 10:
        return False, ""

    text_lower = text.lower().strip()

    # Skip common non-question patterns
    skip_patterns = [
        r"^(good morning|good afternoon|good evening|gm|happy|congrat|thank|thanks|ok|okay|got it|sure|sounds good|lol|haha|yes|no|yep|nope|👍|🙏)",
        r"^(hey|hi|hello|yo)\s*$",
        r"^https?://",  # just a link
    ]
    for sp in skip_patterns:
        if re.match(sp, text_lower):
            return False, ""

    # Check for question patterns
    has_question_pattern = False
    for pattern in _compiled_patterns:
        if pattern.search(text_lower):
            has_question_pattern = True
            break

    # Check for business keywords
    has_business_keyword = False
    matched_keyword = ""
    for kw in _keyword_set:
        if kw in text_lower:
            has_business_keyword = True
            matched_keyword = kw
            break

    # Must have BOTH a question pattern AND a business keyword
    # This avoids false positives like "where are we going for lunch?"
    if has_question_pattern and has_business_keyword:
        return True, f"question about '{matched_keyword}'"

    # High-confidence question pattern: question mark + 20+ chars + business keyword
    if "?" in text and len(text) > 20 and has_business_keyword:
        return True, f"question with keyword '{matched_keyword}'"

    return False, ""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PendingQuestion:
    """A detected question waiting to see if someone answers it."""
    message_id: str
    thread_name: str
    space_name: str
    text: str
    sender_name: str
    sender_id: str
    detected_at: datetime
    reason: str
    respond_after: datetime  # when to check for replies
    responded: bool = False
    logged_as_content: bool = False


# ---------------------------------------------------------------------------
# Passive Listener
# ---------------------------------------------------------------------------

class PassiveListener:
    """Background listener that monitors a Google Chat space."""

    def __init__(self, chat_client, retriever=None, content_engine=None,
                 claude_client=None, analytics_db=None):
        """
        Args:
            chat_client: GoogleChatClient instance (already initialized)
            retriever: RAG Retriever instance (for answering questions)
            content_engine: ContentEngine instance (for logging opportunities)
            claude_client: ClaudeClient instance (for generating responses)
            analytics_db: Analytics DB for logging interactions
        """
        self.chat_client = chat_client
        self.retriever = retriever
        self.content_engine = content_engine
        self.claude = claude_client
        self.analytics_db = analytics_db

        self._space_name = os.getenv("PASSIVE_LISTEN_SPACE", "")
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_poll_time: Optional[str] = None  # RFC 3339 timestamp
        self._pending_questions: dict[str, PendingQuestion] = {}
        self._processed_message_ids: set[str] = set()  # avoid re-processing
        self._seen_reactions: set[str] = set()  # reactions already logged as feedback
        self._prompted_messages: set[str] = set()  # Beacon msgs we've asked to /correct
        self._max_processed_cache = 5000  # rotate after this many

    @property
    def is_configured(self) -> bool:
        return bool(self._space_name)

    def start(self):
        """Start the passive listener background thread."""
        if not self._space_name:
            logger.info("Passive listener not configured (set PASSIVE_LISTEN_SPACE)")
            return

        if self._running:
            logger.warning("Passive listener already running")
            return

        self._running = True
        # Set initial poll time to now (don't backfill)
        self._last_poll_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")

        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="passive-listener")
        self._thread.start()
        logger.info(f"✅ Passive listener started for {self._space_name} "
                     f"(poll={POLL_INTERVAL}s, delay={RESPONSE_DELAY}s)")

    def stop(self):
        """Stop the passive listener."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Passive listener stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _poll_loop(self):
        """Main polling loop — runs in a background thread."""
        while self._running:
            try:
                self._poll_new_messages()
                self._check_pending_questions()
                self._poll_reactions()
            except Exception as e:
                logger.error(f"Passive listener error: {e}", exc_info=True)

            # Sleep in small increments so we can stop quickly
            for _ in range(POLL_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def _poll_reactions(self):
        """Log 👍/👎 reactions as feedback — but ONLY on Beacon's OWN messages
        (sender.type == 'BOT'). A reaction on a teammate's message is ignored, so
        thumbs-upping Sheri never touches the Beacon feedback log."""
        try:
            from urllib.parse import urlencode
            url = (f"{self.chat_client.BASE_URL}/{self._space_name}/messages?"
                   f"{urlencode({'pageSize': 25, 'orderBy': 'createTime desc'})}")
            resp = self.chat_client._make_request("GET", url)
            if resp.status_code != 200:
                return
            for m in resp.json().get("messages", []):
                if (m.get("sender") or {}).get("type") != "BOT":
                    continue  # ONLY Beacon's own messages count as feedback
                name = m.get("name")
                if not name:
                    continue
                rr = self.chat_client._make_request(
                    "GET", f"{self.chat_client.BASE_URL}/{name}/reactions")
                if rr.status_code != 200:
                    continue
                for rx in rr.json().get("reactions", []):
                    emoji = (rx.get("emoji") or {}).get("unicode") or ""
                    if emoji not in ("👍", "👎"):
                        continue
                    user = rx.get("user") or {}
                    key = f"{name}|{user.get('name', '')}|{emoji}"
                    if key in self._seen_reactions:
                        continue
                    self._seen_reactions.add(key)
                    self._log_reaction_feedback(m, emoji, user)
            if len(self._seen_reactions) > self._max_processed_cache:
                self._seen_reactions.clear()
        except Exception as e:
            logger.warning(f"Reaction poll failed: {e}")

    def _log_reaction_feedback(self, beacon_msg: dict, emoji: str, user: dict):
        """Record a 👍/👎 on a Beacon answer, and on a 👎 invite the correction
        (Google Chat has no pop-up, so Beacon asks for the fix in-thread)."""
        answer = (beacon_msg.get("text") or "")[:300]
        ftype = "positive" if emoji == "👍" else "negative"
        if self.analytics_db:
            try:
                self.analytics_db._call("log_feedback", {
                    "user_id": user.get("name", ""),
                    "user_name": user.get("displayName", "") or "chat user",
                    "feedback_text": f"{emoji} reaction on Beacon answer: {answer}",
                    "feedback_type": ftype,
                })
                logger.info(f"Logged {emoji} reaction feedback on a Beacon answer")
            except Exception as e:
                logger.error(f"Failed to log reaction feedback: {e}")
        # On a 👎, ask for the right answer once per message (Chat has no pop-up).
        if emoji == "👎":
            name = beacon_msg.get("name")
            if name and name not in self._prompted_messages:
                self._prompted_messages.add(name)
                try:
                    self.chat_client.send_message(
                        self._space_name,
                        "Thanks for the 👎 — I've flagged that answer as off. If you know the "
                        "right answer, reply `/correct <the correct answer>` and I'll learn it.",
                        thread_name=(beacon_msg.get("thread") or {}).get("name"),
                    )
                except Exception as e:
                    logger.error(f"Failed to post correction prompt: {e}")

    def _poll_new_messages(self):
        """Fetch new messages from the space and classify them."""
        try:
            messages = self._list_messages(
                space_name=self._space_name,
                filter_after=self._last_poll_time,
                page_size=POLL_PAGE_SIZE,
            )

            if not messages:
                return

            logger.debug(f"Passive listener: {len(messages)} new messages")

            for msg in messages:
                msg_name = msg.get("name", "")

                # Skip already-processed messages
                if msg_name in self._processed_message_ids:
                    continue
                self._processed_message_ids.add(msg_name)

                # Rotate cache if too large
                if len(self._processed_message_ids) > self._max_processed_cache:
                    # Keep the most recent half
                    self._processed_message_ids = set(
                        list(self._processed_message_ids)[self._max_processed_cache // 2:]
                    )

                # Skip bot messages (including Beacon's own)
                sender = msg.get("sender", {})
                if sender.get("type") == "BOT":
                    continue

                # Skip messages that are @mentions (already handled by webhook)
                annotations = msg.get("annotations", [])
                has_mention = any(
                    a.get("type") == "USER_MENTION" and
                    a.get("userMention", {}).get("type") == "MENTION"
                    for a in annotations
                )
                if has_mention:
                    continue

                text = msg.get("text", "").strip()
                if not text:
                    continue

                # Classify
                is_relevant, reason = is_relevant_question(text)
                if not is_relevant:
                    continue

                thread_name = msg.get("thread", {}).get("name", "")
                sender_name = sender.get("displayName", "Unknown")
                sender_id = sender.get("name", "unknown")
                create_time = msg.get("createTime", "")

                logger.info(f"Passive listener detected question from {sender_name}: "
                            f"{text[:80]}... ({reason})")

                pq = PendingQuestion(
                    message_id=msg_name,
                    thread_name=thread_name,
                    space_name=self._space_name,
                    text=text,
                    sender_name=sender_name,
                    sender_id=sender_id,
                    detected_at=datetime.now(timezone.utc),
                    reason=reason,
                    respond_after=datetime.now(timezone.utc) + timedelta(seconds=RESPONSE_DELAY),
                )

                self._pending_questions[msg_name] = pq

                # Log as content opportunity immediately
                self._log_content_opportunity(pq)

            # Update last poll time to the most recent message's createTime
            latest_time = messages[-1].get("createTime")
            if latest_time:
                self._last_poll_time = latest_time

        except Exception as e:
            logger.error(f"Error polling messages: {e}", exc_info=True)

    def _check_pending_questions(self):
        """Check if pending questions have been answered."""
        now = datetime.now(timezone.utc)
        to_remove = []

        for msg_id, pq in self._pending_questions.items():
            if pq.responded:
                to_remove.append(msg_id)
                continue

            if now < pq.respond_after:
                continue  # not time yet

            # Time to check — was it answered?
            try:
                thread_replied = self._check_for_replies(pq)

                if thread_replied:
                    logger.info(f"Question was answered by team: {pq.text[:60]}...")
                    pq.responded = True
                    to_remove.append(msg_id)
                else:
                    # Nobody answered — Beacon offers help
                    logger.info(f"Unanswered question, Beacon offering help: {pq.text[:60]}...")
                    self._offer_help(pq)
                    pq.responded = True
                    to_remove.append(msg_id)

            except Exception as e:
                logger.error(f"Error checking pending question {msg_id}: {e}")
                # Don't remove — will retry next cycle

        for msg_id in to_remove:
            self._pending_questions.pop(msg_id, None)

    # ------------------------------------------------------------------
    # Google Chat API calls
    # ------------------------------------------------------------------

    def _list_messages(self, space_name: str, filter_after: str = None,
                       page_size: int = 50) -> list[dict]:
        """List messages in a space using the Google Chat API.

        Uses app authentication with chat.bot scope.
        """
        url = f"{self.chat_client.BASE_URL}/{space_name}/messages"
        params = {"pageSize": page_size}

        if filter_after:
            # Filter for messages created after the last poll
            params["filter"] = f'createTime > "{filter_after}"'

        # Order by creation time ascending so we process oldest first
        params["orderBy"] = "createTime asc"

        try:
            # Build the URL with query params
            from urllib.parse import urlencode
            full_url = f"{url}?{urlencode(params)}"

            response = self.chat_client._make_request("GET", full_url)

            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            elif response.status_code == 403:
                logger.warning(f"Passive listener: 403 — may need chat.bot scope or space membership. "
                               f"Response: {response.text[:200]}")
                return []
            else:
                logger.warning(f"List messages failed: {response.status_code} - {response.text[:200]}")
                return []

        except Exception as e:
            logger.error(f"Error listing messages: {e}")
            return []

    def _check_for_replies(self, pq: PendingQuestion) -> bool:
        """Check if anyone replied — either in-thread OR in the main space.

        Google Chat users sometimes reply directly in the space instead of
        in the thread, so we check both:
        1. Thread replies (if the question has a thread)
        2. Recent space messages that look like they're responding to the question
           (posted after the question, by a different human, within the delay window)
        """
        from urllib.parse import urlencode
        timestamp_str = pq.detected_at.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

        # --- Check 1: In-thread replies ---
        if pq.thread_name:
            try:
                url = f"{self.chat_client.BASE_URL}/{self._space_name}/messages"
                params = {
                    "pageSize": 10,
                    "filter": f'createTime > "{timestamp_str}" AND thread.name = "{pq.thread_name}"',
                }
                full_url = f"{url}?{urlencode(params)}"
                response = self.chat_client._make_request("GET", full_url)

                if response.status_code == 200:
                    messages = response.json().get("messages", [])
                    for msg in messages:
                        sender = msg.get("sender", {})
                        if sender.get("type") != "BOT":
                            logger.debug(f"Thread reply found from {sender.get('displayName')}")
                            return True
            except Exception as e:
                logger.error(f"Error checking thread replies: {e}")

        # --- Check 2: Recent space messages (non-threaded replies) ---
        # Look for human messages posted shortly after the question that might
        # be answering it — even if not in the same thread.
        try:
            url = f"{self.chat_client.BASE_URL}/{self._space_name}/messages"
            params = {
                "pageSize": 15,
                "filter": f'createTime > "{timestamp_str}"',
                "orderBy": "createTime asc",
            }
            full_url = f"{url}?{urlencode(params)}"
            response = self.chat_client._make_request("GET", full_url)

            if response.status_code == 200:
                messages = response.json().get("messages", [])
                question_words = set(pq.text.lower().split())

                for msg in messages:
                    sender = msg.get("sender", {})
                    # Skip bot messages and the original question sender
                    if sender.get("type") == "BOT":
                        continue
                    if sender.get("name") == pq.sender_id:
                        continue  # same person, not an answer

                    msg_text = msg.get("text", "").lower()
                    if not msg_text or len(msg_text) < 5:
                        continue

                    # Heuristics: does this look like a reply to the question?
                    # - Mentions the asker's name
                    # - Shares keywords with the question
                    # - Is a substantial message (not just "ok" or "thanks")
                    sender_name_lower = pq.sender_name.lower().split()[0] if pq.sender_name else ""

                    # Check if reply mentions the asker by first name
                    mentions_asker = sender_name_lower and sender_name_lower in msg_text

                    # Check keyword overlap (at least 2 meaningful words in common)
                    reply_words = set(msg_text.split())
                    # Filter out short/common words
                    meaningful_q = {w for w in question_words if len(w) > 3}
                    meaningful_r = {w for w in reply_words if len(w) > 3}
                    overlap = meaningful_q & meaningful_r
                    has_keyword_overlap = len(overlap) >= 2

                    if mentions_asker or has_keyword_overlap:
                        logger.debug(f"Space reply likely answers question: "
                                     f"mentions_asker={mentions_asker}, overlap={overlap}")
                        return True

        except Exception as e:
            logger.error(f"Error checking space replies: {e}")

        return False

    # ------------------------------------------------------------------
    # Response & logging
    # ------------------------------------------------------------------

    def _get_recent_context(self, pq: "PendingQuestion", limit: int = 40, hours: int = 12) -> str:
        """Pull the recent back-and-forth BEFORE the question so Beacon can find its
        footing the way a human would — scan today's relevant chat, not a fixed 6.
        Takes up to `limit` messages from the last `hours` hours preceding the
        question (whichever bound hits first). Returns a chronological transcript."""
        try:
            from urllib.parse import urlencode
            params = {"pageSize": 100, "orderBy": "createTime desc"}
            url = f"{self.chat_client.BASE_URL}/{self._space_name}/messages?{urlencode(params)}"
            resp = self.chat_client._make_request("GET", url)
            if resp.status_code != 200:
                return ""
            msgs = resp.json().get("messages", [])  # newest-first
            qi = next((i for i, m in enumerate(msgs) if m.get("name") == pq.message_id), None)
            preceding = msgs[qi + 1:] if qi is not None else msgs
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
            lines = []
            for m in preceding:  # newest-first
                ct = (m.get("createTime") or "")[:19]
                if ct and ct < cutoff:
                    break  # older than the window — a human wouldn't scroll back further
                txt = (m.get("text") or "").strip()
                if not txt:
                    continue
                sender = (m.get("sender") or {}).get("displayName") or "Someone"
                lines.append(f"{sender}: {txt[:300]}")
                if len(lines) >= limit:
                    break
            return "\n".join(reversed(lines))  # chronological
        except Exception as e:
            logger.warning(f"Could not fetch recent context: {e}")
            return ""

    def _resolve_question(self, question: str, context: str) -> str:
        """Use the recent conversation to restate the question as a self-contained one
        (resolve 'this'/'that'), so retrieval searches the real topic. Falls back to
        the raw question on any failure or empty context."""
        if not context or not self.claude:
            return question
        try:
            from core.llm_client import Message
            prompt = (
                "From this NYC permit-expediting team chat, restate the LAST question as "
                "ONE clear, self-contained question — resolve references like 'this'/'that' "
                "using the conversation. Reply with ONLY the rewritten question.\n\n"
                f"Conversation:\n{context}\n\nLast question: {question}"
            )
            out, _, _ = self.claude.get_response(
                user_message=prompt,
                conversation_history=[Message(role="user", content=prompt)],
                model_override="claude-haiku-4-5-20251001",
            )
            resolved = (out or "").strip()
            return resolved if 8 <= len(resolved) <= 400 else question
        except Exception as e:
            logger.warning(f"Question resolve failed: {e}")
            return question

    def _offer_help(self, pq: PendingQuestion):
        """Send a helpful Beacon response in the thread."""
        if not self.retriever or not self.claude:
            logger.warning("Cannot offer help — retriever or claude not configured")
            return

        try:
            # Find footing like a human: scan today's recent back-and-forth, then
            # "resolve" the self-contained question and search on THAT (focused),
            # instead of stuffing a noisy transcript into the retrieval query.
            recent_context = self._get_recent_context(pq)
            resolved_q = self._resolve_question(pq.text, recent_context)

            # Get RAG context
            retrieval_result = self.retriever.retrieve(
                query=resolved_q,
                top_k=5,
                min_score=0.55,
            )

            if retrieval_result.num_results == 0:
                # No KB coverage — stay silent in chat, but CAPTURE it: a question we
                # can't answer is both a KB gap and a content opportunity (the flywheel).
                logger.info(f"No KB coverage for: {pq.text[:60]} — logging as gap/content opportunity")
                self._log_content_opportunity(pq)
                if self.analytics_db:
                    try:
                        from analytics.analytics import Interaction
                        from analytics.topic_classifier import get_classifier
                        self.analytics_db.log_interaction(Interaction(
                            timestamp=datetime.now().isoformat(),
                            user_id=pq.sender_id, user_name=pq.sender_name, space_name=pq.space_name,
                            question=pq.text, response=None, command="passive_gap",
                            answered=False, response_length=0, had_sources=False, sources_used=[],
                            tokens_used=0, cost_usd=0.0, response_time_ms=0, confidence=0.0,
                            topic=get_classifier().classify(pq.text),
                        ))
                    except Exception as e:
                        logger.error(f"Failed to log gap interaction: {e}")
                return  # Don't post a guess when the KB has nothing

            # Generate response with Claude (using Haiku for cost efficiency)
            from core.llm_client import Message

            system_prompt = (
                "You are Beacon, the AI assistant for Green Light Expediting (GLE), a NYC "
                "expediting firm. You spotted a work question in the team chat that nobody has "
                "answered yet. Use the recent chat conversation provided to understand what the "
                "question refers to (resolve 'this'/'that' from the messages before it). The team "
                "are expert expeditors and PMs — be direct and substantive, "
                "not basic. Answer ONLY from the knowledge base context provided; do not guess or "
                "invent code/filing specifics. If the context doesn't clearly answer it, say so "
                "plainly and suggest checking with their manager (Chris or Manny) — never make "
                "something up. For anything actionable (filings, deadlines, code or zoning "
                "specifics), add a brief reminder to confirm it's current against DOB, since rules "
                "change. Write plain, conversational chat text — NO bold headers or bullet lists. "
                "Open with 'Saw this — here's what I found:' and keep it tight (2-5 sentences)."
            )

            rag_context = retrieval_result.context
            context_block = (
                f"Recent chat conversation (for context — resolve references like 'this'/'that' "
                f"from it):\n{recent_context}\n\n" if recent_context else ""
            )
            user_prompt = (
                f"{context_block}Question to answer (from {pq.sender_name}): {pq.text}\n\n"
                f"Knowledge base context:\n{rag_context}"
            )

            msg = Message(role="user", content=f"{system_prompt}\n\n{user_prompt}")
            response_text, model_used, usage = self.claude.get_response(
                user_message=f"{system_prompt}\n\n{user_prompt}",
                conversation_history=[msg],
                model_override="claude-haiku-4-5-20251001",  # always Haiku for passive
            )

            if response_text:
                # Cite sources so the team can verify (already retrieved).
                source_titles = [s.title for s in retrieval_result.sources[:2] if getattr(s, "title", None)]
                if source_titles:
                    response_text = f"{response_text}\n\n📚 Source: {', '.join(source_titles)}"
                # Send in the same thread
                result = self.chat_client.send_message(
                    self._space_name,
                    response_text,
                    thread_name=pq.thread_name,
                )
                if result.success:
                    logger.info(f"Passive response sent for: {pq.text[:60]}")

                    # Log to analytics
                    if self.analytics_db:
                        try:
                            from analytics.analytics import Interaction
                            from analytics.topic_classifier import get_classifier
                            interaction = Interaction(
                                timestamp=datetime.now().isoformat(),
                                user_id=pq.sender_id,
                                user_name=pq.sender_name,
                                space_name=pq.space_name,
                                question=pq.text,
                                response=response_text[:500],
                                command="passive_response",
                                answered=True,
                                response_length=len(response_text),
                                had_sources=retrieval_result.num_results > 0,
                                sources_used=[s.title for s in retrieval_result.sources[:3]],
                                tokens_used=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                                cost_usd=0.0,
                                response_time_ms=0,
                                confidence=retrieval_result.avg_score,
                                topic=get_classifier().classify(pq.text, response_text),
                            )
                            self.analytics_db.log_interaction(interaction)
                        except Exception as e:
                            logger.error(f"Failed to log passive interaction: {e}")

        except Exception as e:
            logger.error(f"Error offering help: {e}", exc_info=True)

    def _log_content_opportunity(self, pq: PendingQuestion):
        """Log a detected question as a content opportunity."""
        if not self.content_engine:
            return

        try:
            candidate = self.content_engine.analyze_update(
                title=f"Team question: {pq.text[:100]}",
                summary=f"Detected in Google Chat from {pq.sender_name}: {pq.text}",
                source_url=f"gchat:{pq.message_id}",
                source_type="passive_chat",
            )
            pq.logged_as_content = True
            logger.info(f"Content opportunity logged: {candidate.id} - {candidate.title[:60]}")
        except Exception as e:
            logger.error(f"Failed to log content opportunity: {e}")

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Get the current status of the passive listener."""
        return {
            "running": self._running,
            "space": self._space_name,
            "last_poll": self._last_poll_time,
            "pending_questions": len(self._pending_questions),
            "processed_messages": len(self._processed_message_ids),
            "poll_interval_seconds": POLL_INTERVAL,
            "response_delay_seconds": RESPONSE_DELAY,
        }
