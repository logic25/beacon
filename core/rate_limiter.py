"""
Rate Limiting and Cost Control for Beacon

Implements the strategies discussed:
1. Per-user rate limits (20 questions/hour, 100/day)
2. Token budget limits (100K tokens/day per user)
3. Off-topic filtering (cheap/free pre-check)
4. Cost tracking per feature
"""

import re
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from functools import wraps

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION - Adjust these for your team
# ============================================================================

RATE_LIMITS = {
    "requests_per_hour": 20,      # Max questions per user per hour
    "requests_per_day": 100,      # Max questions per user per day
    "tokens_per_day": 100_000,    # Max tokens per user per day (~75K words)
    "daily_budget_usd": 5.00,     # Alert if daily spend exceeds this
}

# Industry keywords for off-topic detection
PERMIT_KEYWORDS = [
    # DOB / Permits
    "dob", "permit", "filing", "zoning", "code", "violation", "objection",
    "alt 1", "alt 2", "alt 3", "nb", "dm", "sign off", "sign-off", "approval",
    "bis", "bisweb", "now", "dob now", "plan exam", "examiner",

    # Building types
    "building class", "occupancy", "use group", "assembly", "mercantile",
    "residential", "commercial", "mixed use",

    # Zoning
    "far", "setback", "lot coverage", "yard", "height limit", "bulk",
    "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10",
    "c1", "c2", "c3", "c4", "c5", "c6", "m1", "m2", "m3",

    # Certificates
    "co", "tco", "certificate of occupancy", "temporary certificate",
    "letter of completion", "loc", "final inspection",

    # Other agencies
    "lpc", "landmark", "fdny", "dep", "dot", "hpd", "ecc", "mta",

    # Construction
    "sprinkler", "standpipe", "egress", "stairs", "elevator",
    "plumbing", "electrical", "mechanical", "structural",

    # Documents
    "tr1", "tr2", "tr3", "tr8", "pai", "paa", "ppo", "lno",
    "plans", "drawings", "specs", "survey", "i-card",

    # Process
    "reinstate", "supersede", "amend", "withdraw", "appeal",
    "audit", "hold", "objections", "items required",

    # NYC
    "manhattan", "brooklyn", "bronx", "queens", "staten island",
    "borough", "bbl", "bin", "block", "lot",

    # Real estate
    "property", "address", "building", "floor", "apartment",
]

# Off-topic signals (if these appear AND no permit keywords)
OFF_TOPIC_SIGNALS = [
    "poem", "poetry", "song", "story", "creative writing",
    "recipe", "cook", "food", "restaurant",
    "movie", "film", "tv show", "entertainment",
    "sports", "game", "team", "score",
    "weather", "forecast", "temperature",
    "joke", "funny", "humor", "riddle",
    "translate", "language",
]


# ============================================================================
# USAGE TRACKING (Simple file-based for easy setup)
# ============================================================================

@dataclass
class UsageRecord:
    """Track usage for a user."""
    user_id: str
    requests_today: int = 0
    requests_this_hour: int = 0
    tokens_today: int = 0
    cost_today: float = 0.0
    last_request: Optional[str] = None
    hour_window_start: Optional[str] = None
    day_start: Optional[str] = None


class UsageTracker:
    """Track and limit user usage. File-based for simplicity."""

    def __init__(self, data_dir: str = "data/usage"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.usage_file = self.data_dir / "usage.json"
        self._load()

    def _load(self):
        """Load usage data from file."""
        if self.usage_file.exists():
            with open(self.usage_file, 'r') as f:
                data = json.load(f)
                self.users = {
                    uid: UsageRecord(**record)
                    for uid, record in data.items()
                }
        else:
            self.users = {}

    def _save(self):
        """Save usage data to file."""
        data = {uid: asdict(record) for uid, record in self.users.items()}
        with open(self.usage_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _get_or_create_user(self, user_id: str) -> UsageRecord:
        """Get user record, creating if needed."""
        if user_id not in self.users:
            self.users[user_id] = UsageRecord(user_id=user_id)
        return self.users[user_id]

    def _reset_if_needed(self, record: UsageRecord):
        """Reset counters if time windows have passed."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        this_hour = now.strftime("%Y-%m-%d %H")

        # Reset daily counters
        if record.day_start != today:
            record.requests_today = 0
            record.tokens_today = 0
            record.cost_today = 0.0
            record.day_start = today

        # Reset hourly counter
        if record.hour_window_start != this_hour:
            record.requests_this_hour = 0
            record.hour_window_start = this_hour

    def check_limits(self, user_id: str) -> tuple[bool, str]:
        """
        Check if user is within rate limits.

        Returns:
            (allowed, message) - True if allowed, False with reason if not
        """
        record = self._get_or_create_user(user_id)
        self._reset_if_needed(record)

        # Check hourly limit
        if record.requests_this_hour >= RATE_LIMITS["requests_per_hour"]:
            return (False, f"You've reached the limit of {RATE_LIMITS['requests_per_hour']} questions per hour. Try again soon!")

        # Check daily limit
        if record.requests_today >= RATE_LIMITS["requests_per_day"]:
            return (False, f"You've reached the daily limit of {RATE_LIMITS['requests_per_day']} questions. Try again tomorrow!")

        # Check token limit
        if record.tokens_today >= RATE_LIMITS["tokens_per_day"]:
            return (False, "Daily token limit reached. Try again tomorrow!")

        return (True, "OK")

    def record_usage(
        self,
        user_id: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        feature: str = "general"
    ):
        """Record usage after a successful request."""
        record = self._get_or_create_user(user_id)
        self._reset_if_needed(record)

        record.requests_today += 1
        record.requests_this_hour += 1
        record.tokens_today += input_tokens + output_tokens
        record.cost_today += cost
        record.last_request = datetime.now().isoformat()

        self._save()

        # Log for monitoring
        logger.info(
            f"Usage: user={user_id} feature={feature} "
            f"tokens={input_tokens + output_tokens} cost=${cost:.4f} "
            f"daily_total=${record.cost_today:.4f}"
        )

        # Alert if daily budget exceeded
        if record.cost_today > RATE_LIMITS["daily_budget_usd"]:
            logger.warning(
                f"âš ï¸ Daily budget exceeded! user={user_id} "
                f"cost=${record.cost_today:.2f} "
                f"limit=${RATE_LIMITS['daily_budget_usd']}"
            )

    def get_usage_summary(self, user_id: str) -> dict:
        """Get usage summary for a user."""
        record = self._get_or_create_user(user_id)
        self._reset_if_needed(record)

        return {
            "requests_today": record.requests_today,
            "requests_remaining_today": RATE_LIMITS["requests_per_day"] - record.requests_today,
            "requests_this_hour": record.requests_this_hour,
            "tokens_today": record.tokens_today,
            "cost_today": round(record.cost_today, 4),
        }

    def get_daily_totals(self) -> dict:
        """Get totals across all users for today."""
        today = datetime.now().strftime("%Y-%m-%d")

        total_requests = 0
        total_tokens = 0
        total_cost = 0.0
        active_users = 0

        for record in self.users.values():
            if record.day_start == today:
                total_requests += record.requests_today
                total_tokens += record.tokens_today
                total_cost += record.cost_today
                if record.requests_today > 0:
                    active_users += 1

        return {
            "date": today,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 4),
            "active_users": active_users,
        }


# ============================================================================
# OFF-TOPIC DETECTION (Free pre-filter)
# ============================================================================

def is_off_topic(message: str) -> tuple[bool, str]:
    """
    Check if message is off-topic (not about permits/real estate).

    This is a FREE check (no AI calls) that prevents wasting tokens
    on irrelevant questions like "write me a poem".

    Returns:
        (is_off_topic, reason)
    """
    message_lower = message.lower()

    # Check for permit-related keywords
    has_permit_keyword = any(
        keyword in message_lower
        for keyword in PERMIT_KEYWORDS
    )

    # Check for off-topic signals
    has_off_topic_signal = any(
        signal in message_lower
        for signal in OFF_TOPIC_SIGNALS
    )

    # If has permit keywords, it's on-topic
    if has_permit_keyword:
        return (False, "on_topic")

    # If has off-topic signals and NO permit keywords, it's off-topic
    if has_off_topic_signal:
        return (True, "off_topic_signal")

    # Short messages without context are suspicious
    if len(message.strip()) < 15 and not has_permit_keyword:
        # Could be "hi" or "thanks" - allow but flag
        return (False, "short_unclear")

    # Default: allow (might be a valid question we didn't recognize)
    return (False, "allowed_default")


def get_off_topic_response() -> str:
    """Get a friendly response for off-topic questions."""
    return (
        "I'm focused on helping with NYC permit expediting and zoning questions. "
        "How can I help with your projects today?\n\n"
        "You can ask me about:\n"
        "â€¢ DOB filings and applications\n"
        "â€¢ Zoning regulations and use groups\n"
        "â€¢ Permit status and objections\n"
        "â€¢ Building code requirements"
    )


# ============================================================================
# COST CALCULATOR
# ============================================================================

# Model pricing (per 1M tokens)
MODEL_PRICING = {
    # Claude 4.5 series (current — per million tokens)
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},

    # Claude 4 / 3.5 series (legacy)
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},

    # Gemini (for intent classification)
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int
) -> float:
    """Calculate cost for a request."""
    # Try exact match first
    if model in MODEL_PRICING:
        pricing = MODEL_PRICING[model]
    else:
        # Try partial match
        for model_name, pricing in MODEL_PRICING.items():
            if model_name in model or model in model_name:
                break
        else:
            # Default to Haiku pricing
            pricing = MODEL_PRICING["claude-haiku-4-5-20251001"]
            logger.warning(f"Unknown model {model}, using Haiku pricing")

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return input_cost + output_cost


# ============================================================================
# DECORATOR FOR EASY USE
# ============================================================================

# Global tracker instance
_tracker = None

def get_tracker() -> UsageTracker:
    """Get or create global usage tracker."""
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker


def rate_limited(func):
    """
    Decorator to add rate limiting to any function that handles user requests.

    The decorated function must have user_id as first argument.
    """
    @wraps(func)
    def wrapper(user_id: str, *args, **kwargs):
        tracker = get_tracker()

        # Check rate limits
        allowed, message = tracker.check_limits(user_id)
        if not allowed:
            return {"error": message, "rate_limited": True}

        # Call the actual function
        return func(user_id, *args, **kwargs)

    return wrapper


# ============================================================================
# CLI for checking usage
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check usage stats")
    parser.add_argument("--user", "-u", help="Check specific user")
    parser.add_argument("--totals", "-t", action="store_true", help="Show daily totals")

    args = parser.parse_args()

    tracker = UsageTracker()

    if args.totals:
        totals = tracker.get_daily_totals()
        print("\nðŸ“Š Daily Totals:")
        print(f"   Date: {totals['date']}")
        print(f"   Requests: {totals['total_requests']}")
        print(f"   Tokens: {totals['total_tokens']:,}")
        print(f"   Cost: ${totals['total_cost']:.4f}")
        print(f"   Active Users: {totals['active_users']}")

    if args.user:
        usage = tracker.get_usage_summary(args.user)
        print(f"\nðŸ‘¤ Usage for {args.user}:")
        print(f"   Requests today: {usage['requests_today']}")
        print(f"   Remaining today: {usage['requests_remaining_today']}")
        print(f"   Tokens today: {usage['tokens_today']:,}")
        print(f"   Cost today: ${usage['cost_today']:.4f}")
