"""
Beacon Content Scheduler

Background thread that (1) periodically turns accumulated team questions into
content candidates — the piece that used to only run when someone manually hit
/api/content/auto-generate — and (2) posts a Google Chat notification whenever
new candidates appear, so the team finds out without having to open Ordino.

Mirrors the EmailPoller pattern: a daemon thread with an interval loop, started
once (under a file lock) from initialize_app() so only a single gunicorn worker
runs it.

Configuration (all optional, via env):
  CONTENT_SCHED_INTERVAL        seconds between runs (default 86400 = daily)
  CONTENT_SCHED_INITIAL_DELAY   seconds to wait after startup before first run
  CONTENT_AUTO_GENERATE         "true"/"false" — generate candidates each cycle
  CONTENT_NOTIFY_SPACE          Google Chat space id (e.g. "spaces/ABC123");
                                falls back to PASSIVE_LISTEN_SPACE
  CONTENT_SEEN_PATH             where announced candidate IDs are remembered
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List

logger = logging.getLogger(__name__)

SCHED_INTERVAL = int(os.getenv("CONTENT_SCHED_INTERVAL", str(24 * 3600)))
SCHED_INITIAL_DELAY = int(os.getenv("CONTENT_SCHED_INITIAL_DELAY", "120"))
NOTIFY_SPACE = os.getenv("CONTENT_NOTIFY_SPACE", "") or os.getenv("PASSIVE_LISTEN_SPACE", "")
SEEN_STATE_PATH = os.getenv("CONTENT_SEEN_PATH", "/tmp/beacon_content_seen.json")
AUTO_GENERATE = os.getenv("CONTENT_AUTO_GENERATE", "true").lower() in ("1", "true", "yes")


class ContentScheduler:
    """Background scheduler for content-candidate generation + notification."""

    def __init__(self, engine=None, chat_client=None, notify_space: Optional[str] = None):
        self.engine = engine
        self.chat_client = chat_client
        self.notify_space = notify_space if notify_space is not None else NOTIFY_SPACE

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_run: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_created = 0
        self._last_notified = 0

    @property
    def is_configured(self) -> bool:
        # Can run auto-generate with just an engine; notification is skipped when
        # no chat space/client is configured.
        return self.engine is not None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if self.engine is None:
            logger.info("Content scheduler not configured (no engine)")
            return
        if self._running:
            logger.warning("Content scheduler already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="content-scheduler"
        )
        self._thread.start()
        logger.info(
            f"✅ Content scheduler started (interval={SCHED_INTERVAL}s, "
            f"auto_generate={AUTO_GENERATE}, notify_space={self.notify_space or 'none'})"
        )

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Content scheduler stopped")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "interval_seconds": SCHED_INTERVAL,
            "auto_generate": AUTO_GENERATE,
            "notify_space": self.notify_space or None,
            "last_run": self._last_run,
            "last_error": self._last_error,
            "last_created": self._last_created,
            "last_notified": self._last_notified,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _loop(self):
        time.sleep(SCHED_INITIAL_DELAY)  # let the app finish starting
        while self._running:
            try:
                self.run_once()
                self._last_run = datetime.now(timezone.utc).isoformat()
                self._last_error = None
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Content scheduler error: {e}", exc_info=True)

            # Sleep in small increments so stop() stays responsive.
            slept = 0
            while self._running and slept < SCHED_INTERVAL:
                step = min(30, SCHED_INTERVAL - slept)
                time.sleep(step)
                slept += step

    def run_once(self) -> dict:
        """One cycle: optionally auto-generate candidates, then notify on new ones."""
        created = 0
        if AUTO_GENERATE:
            try:
                from analytics.content_routes import run_auto_generate
                result = run_auto_generate(self.engine)
                created = int(result.get("candidates_created", 0) or 0)
                if not result.get("success"):
                    logger.warning(
                        f"[ContentScheduler] auto-generate: "
                        f"{result.get('error') or result.get('message')}"
                    )
            except Exception as e:
                logger.error(f"[ContentScheduler] auto-generate failed: {e}", exc_info=True)
        self._last_created = created

        notified = self._notify_new_candidates()
        self._last_notified = notified
        return {"created": created, "notified": notified}

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------
    def _current_candidates(self) -> List[dict]:
        try:
            cands = self.engine.get_pending_candidates()
        except Exception as e:
            logger.error(f"[ContentScheduler] could not load candidates: {e}")
            return []
        out = []
        for c in cands:
            cid = getattr(c, "id", None)
            if not cid:
                continue
            out.append({
                "id": cid,
                "title": getattr(c, "title", "") or "",
                "priority": (getattr(c, "priority", "") or ""),
                "team_questions_count": getattr(c, "team_questions_count", 0) or 0,
            })
        return out

    def _load_seen(self) -> set:
        try:
            with open(SEEN_STATE_PATH) as f:
                return set(json.load(f).get("seen", []))
        except Exception:
            return set()

    def _save_seen(self, ids):
        try:
            with open(SEEN_STATE_PATH, "w") as f:
                json.dump(
                    {"seen": sorted(ids), "updated": datetime.now(timezone.utc).isoformat()},
                    f,
                )
        except Exception as e:
            logger.warning(f"[ContentScheduler] could not persist seen-state: {e}")

    def _notify_new_candidates(self) -> int:
        candidates = self._current_candidates()
        if not candidates:
            return 0

        current_ids = {c["id"] for c in candidates}
        first_run = not os.path.exists(SEEN_STATE_PATH)

        # First run ever: seed state silently so we don't blast the whole backlog.
        if first_run:
            self._save_seen(current_ids)
            logger.info(
                f"[ContentScheduler] seeded seen-state with {len(current_ids)} "
                f"existing candidates (no notification on first run)"
            )
            return 0

        seen = self._load_seen()
        new = [c for c in candidates if c["id"] not in seen]
        if not new:
            self._save_seen(current_ids)
            return 0

        message = self._format_message(new)
        sent_ok = self._send_chat(message)

        # Persist as seen once we've notified — or if there's no chat target, so
        # the backlog doesn't grow unbounded. If a chat send failed, keep them
        # unseen to retry next cycle.
        if sent_ok or not (self.chat_client and self.notify_space):
            self._save_seen(current_ids)
        return len(new)

    @staticmethod
    def _format_message(new: List[dict]) -> str:
        order = {"high": 0, "medium": 1, "low": 2}
        new_sorted = sorted(new, key=lambda c: order.get(str(c["priority"]).lower(), 3))
        lines = [f"*Beacon: {len(new_sorted)} new content idea(s) to review*", ""]
        for c in new_sorted:
            pr = (str(c["priority"]).upper() or "—")
            qc = c["team_questions_count"]
            suffix = f" — {qc} team questions" if qc else ""
            lines.append(f"• [{pr}] {c['title']}{suffix}")
        lines.append("")
        lines.append("Review & approve in Ordino → Content.")
        return "\n".join(lines)

    def _send_chat(self, text: str) -> bool:
        if not (self.chat_client and self.notify_space):
            logger.info("[ContentScheduler] no chat client/space configured; skipping notification")
            return False
        try:
            result = self.chat_client.send_message(self.notify_space, text)
            ok = bool(getattr(result, "success", False))
            if not ok:
                logger.warning(f"[ContentScheduler] chat send failed: {getattr(result, 'error', None)}")
            return ok
        except Exception as e:
            logger.error(f"[ContentScheduler] chat send error: {e}", exc_info=True)
            return False
