"""
Beacon Content Scheduler

Background thread that periodically turns accumulated team questions into content
candidates — the piece that previously only ran when someone manually hit
/api/content/auto-generate. Candidates are persisted through the engine's
Supabase-first save (see analytics/content_routes.run_auto_generate), so they
appear in Ordino's /content page, where a notification bell surfaces the new
ones for review.

Mirrors the EmailPoller pattern: a daemon thread with an interval loop, started
once (under a file lock) from initialize_app() so only one gunicorn worker runs it.

Config (env):
  CONTENT_SCHED_INTERVAL       seconds between runs (default 86400 = daily)
  CONTENT_SCHED_INITIAL_DELAY  seconds to wait after startup before first run
  CONTENT_AUTO_GENERATE        "true"/"false" — master on/off switch (default true)
"""

import os
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

SCHED_INTERVAL = int(os.getenv("CONTENT_SCHED_INTERVAL", str(24 * 3600)))
SCHED_INITIAL_DELAY = int(os.getenv("CONTENT_SCHED_INITIAL_DELAY", "120"))
ENABLED = os.getenv("CONTENT_AUTO_GENERATE", "true").lower() in ("1", "true", "yes")


class ContentScheduler:
    """Background cron that auto-generates content candidates from team questions.

    Notification is handled in the UI (the Ordino /content notification bell reads
    the candidates this produces), so this class only generates — it does not push.
    """

    def __init__(self, engine=None):
        self.engine = engine
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_run: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_created = 0

    @property
    def is_configured(self) -> bool:
        return self.engine is not None and ENABLED

    def start(self):
        if not ENABLED:
            logger.info("Content scheduler disabled (CONTENT_AUTO_GENERATE=false)")
            return
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
        logger.info(f"✅ Content scheduler started (interval={SCHED_INTERVAL}s)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Content scheduler stopped")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "enabled": ENABLED,
            "interval_seconds": SCHED_INTERVAL,
            "last_run": self._last_run,
            "last_error": self._last_error,
            "last_created": self._last_created,
        }

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

            # Sleep in small steps so stop() stays responsive.
            slept = 0
            while self._running and slept < SCHED_INTERVAL:
                step = min(30, SCHED_INTERVAL - slept)
                time.sleep(step)
                slept += step

    def run_once(self) -> dict:
        """Generate candidates once. Returns the run_auto_generate result dict."""
        from analytics.content_routes import run_auto_generate
        result = run_auto_generate(self.engine)
        created = int(result.get("candidates_created", 0) or 0)
        self._last_created = created
        if not result.get("success"):
            logger.warning(
                f"[ContentScheduler] auto-generate: "
                f"{result.get('error') or result.get('message')}"
            )
        else:
            logger.info(
                f"[ContentScheduler] auto-generate created {created} "
                f"candidate(s) from {result.get('source')}"
            )
        return result
