"""
Supabase-backed analytics for Beacon bot.
Drop-in replacement for SQLite analytics.py that persists across Railway deploys.

Calls the Ordino Supabase edge function (beacon-analytics) as a proxy,
so Railway doesn't need the Supabase service_role key directly.

Requires:
  SUPABASE_URL - e.g. https://mimlfjkisguktiqqkpkm.supabase.co
  BEACON_ANALYTICS_KEY - shared secret for edge function auth
"""

import json
import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class SupabaseAnalyticsDB:
    """
    Supabase-backed analytics via edge function proxy.
    Same interface as AnalyticsDB in analytics.py so bot_v2.py can swap seamlessly.
    """

    def __init__(self, supabase_url: str, analytics_key: str):
        self.base_url = f"{supabase_url.rstrip('/')}/functions/v1/beacon-analytics"
        self.headers = {
            "Content-Type": "application/json",
            "x-beacon-key": analytics_key,
        }
        logger.info("Supabase analytics (edge function) initialized")

    def _call(self, action: str, data: dict = None) -> dict:
        """Call the beacon-analytics edge function."""
        try:
            resp = requests.post(
                self.base_url,
                json={"action": action, "data": data or {}},
                headers=self.headers,
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(
                    f"Edge function ({action}) returned {resp.status_code}: {resp.text[:500]}"
                )
                return {}
            result = resp.json()
            if "error" in result:
                logger.error(f"Edge function ({action}) error: {result['error']}")
            return result
        except requests.exceptions.ConnectionError as e:
            logger.error(
                f"Edge function ({action}) connection failed — is the beacon-analytics "
                f"edge function deployed? URL: {self.base_url} — {e}"
            )
            return {}
        except requests.exceptions.Timeout:
            logger.error(f"Edge function ({action}) timed out after 15s")
            return {}
        except Exception as e:
            logger.error(f"Edge function ({action}) unexpected error: {e}", exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_interaction(self, interaction) -> None:
        """Log a user interaction. Accepts an analytics.Interaction dataclass."""
        try:
            if not interaction.topic:
                interaction.topic = self._categorize_topic(
                    interaction.question, interaction.response or ""
                )

            self._call("log_interaction", {
                "timestamp": interaction.timestamp,
                "user_id": interaction.user_id,
                "user_name": interaction.user_name,
                "space_name": interaction.space_name,
                "question": interaction.question,
                "response": interaction.response,
                "command": interaction.command,
                "answered": interaction.answered,
                "response_length": interaction.response_length,
                "had_sources": interaction.had_sources,
                "sources_used": interaction.sources_used,
                "tokens_used": interaction.tokens_used,
                "cost_usd": interaction.cost_usd,
                "response_time_ms": interaction.response_time_ms,
                "confidence": interaction.confidence,
                "topic": interaction.topic,
            })
        except Exception as e:
            logger.error(f"log_interaction failed: {e}")

    def log_api_usage(self, api_name: str, operation: str, tokens: int, cost: float) -> None:
        """Log API usage for cost tracking."""
        try:
            self._call("log_api_usage", {
                "timestamp": datetime.now().isoformat(),
                "api_name": api_name,
                "operation": operation,
                "tokens_used": tokens,
                "cost_usd": cost,
            })
        except Exception as e:
            logger.error(f"log_api_usage failed: {e}")

    def log_suggestion(self, user_id: str, user_name: str, wrong: str, correct: str, topics: list[str]) -> int:
        """Log a correction suggestion from team."""
        try:
            result = self._call("log_suggestion", {
                "user_id": user_id,
                "user_name": user_name,
                "wrong_answer": wrong,
                "correct_answer": correct,
                "topics": json.dumps(topics),
            })
            return result.get("id", 0)
        except Exception as e:
            logger.error(f"log_suggestion failed: {e}")
            return 0

    def log_correction(self, user_id: str, user_name: str, wrong: str, correct: str, topics: list[str]) -> int:
        """Log an admin correction."""
        try:
            result = self._call("log_correction", {
                "user_id": user_id,
                "user_name": user_name,
                "wrong_answer": wrong,
                "correct_answer": correct,
                "topics": json.dumps(topics),
            })
            return result.get("id", 0)
        except Exception as e:
            logger.error(f"log_correction failed: {e}")
            return 0

    def log_feedback(self, user_id: str, user_name: str, feedback: str) -> int:
        """Log a feature request / feedback."""
        try:
            result = self._call("log_feedback", {
                "user_id": user_id,
                "user_name": user_name,
                "feedback_text": feedback,
            })
            return result.get("id", 0)
        except Exception as e:
            logger.error(f"log_feedback failed: {e}")
            return 0

    def create_roadmap_item(self, title: str, priority: str = "medium",
                            roadmap_status: str = "backlog",
                            target_quarter: str = None,
                            notes: str = None,
                            created_by: str = "admin") -> int:
        """Create a standalone roadmap item (not tied to user feedback)."""
        try:
            result = self._call("create_roadmap_item", {
                "title": title,
                "priority": priority,
                "roadmap_status": roadmap_status,
                "target_quarter": target_quarter,
                "notes": notes,
                "created_by": created_by,
            })
            return result.get("id", 0)
        except Exception as e:
            logger.error(f"create_roadmap_item failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: Optional[int] = None,
    ) -> dict:
        """Get comprehensive statistics for a date range."""
        try:
            result = self._call("get_stats", {
                "start_date": start_date,
                "end_date": end_date,
                "days": days,
            })
            return result if result else self._empty_stats(days)
        except Exception as e:
            logger.error(f"get_stats failed: {e}")
            return self._empty_stats(days)

    def get_recent_conversations(self, limit: int = 20, user_id: Optional[str] = None) -> list[dict]:
        """Get recent Q&A conversations with full responses."""
        try:
            result = self._call("get_recent_conversations", {
                "limit": limit,
                "user_id": user_id,
            })
            return result.get("conversations", []) if result else []
        except Exception as e:
            logger.error(f"get_recent_conversations failed: {e}")
            return []

    def get_pending_suggestions(self) -> list[dict]:
        """Get all pending suggestions for review."""
        try:
            result = self._call("get_pending_suggestions")
            return result.get("suggestions", []) if result else []
        except Exception as e:
            logger.error(f"get_pending_suggestions failed: {e}")
            return []

    def approve_suggestion(self, suggestion_id: int, reviewed_by: str) -> dict:
        """Approve a suggestion."""
        result = self._call("approve_suggestion", {
            "suggestion_id": suggestion_id,
            "reviewed_by": reviewed_by,
        })
        if not result:
            raise ValueError(f"Suggestion {suggestion_id} not found")
        return result

    def reject_suggestion(self, suggestion_id: int, reviewed_by: str) -> None:
        """Reject a suggestion."""
        self._call("reject_suggestion", {
            "suggestion_id": suggestion_id,
            "reviewed_by": reviewed_by,
        })

    def get_feedback(self, limit: int = 50, status: str = None) -> list[dict]:
        """Get user feedback submissions."""
        try:
            result = self._call("get_feedback", {
                "limit": limit,
                "status": status,
            })
            return result.get("feedback", []) if result else []
        except Exception as e:
            logger.error(f"get_feedback failed: {e}")
            return []

    def update_feedback_roadmap(self, feedback_id: int, roadmap_status: str = None,
                                priority: str = None, target_quarter: str = None,
                                notes: str = None) -> bool:
        """Update roadmap tracking for a feedback item."""
        result = self._call("update_feedback_roadmap", {
            "feedback_id": feedback_id,
            "roadmap_status": roadmap_status,
            "priority": priority,
            "target_quarter": target_quarter,
            "notes": notes,
        })
        return bool(result)

    def get_roadmap_summary(self) -> dict:
        """Get roadmap overview grouped by status."""
        try:
            result = self._call("get_roadmap_summary")
            return result if result else {"by_status": {}, "items_by_status": {}}
        except Exception as e:
            logger.error(f"get_roadmap_summary failed: {e}")
            return {"by_status": {}, "items_by_status": {}}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _empty_stats(self, days=None):
        return {
            "total_questions": 0, "answered": 0, "success_rate": 0,
            "active_users": 0, "total_cost_usd": 0, "api_costs": {},
            "top_users": [], "top_questions": [], "topics": [],
            "failed_queries": [], "command_usage": [],
            "response_time": {"avg_ms": 0, "min_ms": 0, "max_ms": 0},
            "pending_suggestions": 0, "new_feedback": 0,
            "date_range": {"start": "", "end": "", "days": days},
        }

    def _categorize_topic(self, question: str, response: str = "") -> str:
        """Auto-categorize using LLM classifier, fall back to keywords."""
        try:
            from analytics.topic_classifier import get_classifier
            classifier = get_classifier()
            return classifier.classify(question, response)
        except Exception as e:
            logger.warning(f"LLM classification failed, using keyword fallback: {e}")
            return self._categorize_topic_keywords(question, response)

    def _categorize_topic_keywords(self, question: str, response: str = "") -> str:
        """Keyword-based topic categorization (fallback)."""
        combined = (question + " " + response).lower()

        topics = {
            "Noise/Hours": ["what time", "work until", "noise", "after hours", "construction hours"],
            "FDNY": ["fdny", "fire alarm", "sprinkler", "standpipe", "suppression", "ansul"],
            "Certificates": ["co", "certificate of occupancy", "tco", "temporary co"],
            "Violations": ["violation", "ecb", "bis", "hpd violation", "dob violation"],
            "DHCR": ["dhcr", "rent", "stabiliz", "mci", "iai", "lease", "rent increase"],
            "DOB Filings": ["dob", "permit", "filing", "alt1", "alt2", "nb", "dm", "paa", "objection"],
            "Building Code": ["building code", "egress", "fire safety", "occupancy group"],
            "MDL": ["mdl", "multiple dwelling", "class a", "class b"],
            "Zoning": ["zoning", "use group", "far", "setback", "variance", "zr"],
            "Property Lookup": ["lookup", "address", "bin", "block", "lot"],
            "Plans/Drawings": ["plan", "drawing", "elevation", "floor plan", "blueprint"],
        }

        for topic, keywords in topics.items():
            if any(kw in combined for kw in keywords):
                return topic

        return "General"
