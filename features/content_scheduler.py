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
  CONTENT_STALE_ALERT_DAYS     days without a new candidate before alerting (default 5)
  CONTENT_STALE_ALERT_SPACE    optional Google Chat space for the (secondary) alert
                               (falls back to PASSIVE_LISTEN_SPACE)
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

# Staleness watchdog: how many days the content pipeline may go without a NEW
# candidate before we alert. A silent newsletter-parsing regression once let
# candidate creation stop for a month unnoticed (status stayed running:true), so
# the watchdog exists to make that class of silent failure loud.
STALE_ALERT_DAYS = int(os.getenv("CONTENT_STALE_ALERT_DAYS", "5"))
# Optional secondary channel — a Google Chat space to also post the alert to.
# Uses Beacon's existing chat.bot app-auth (no new OAuth scope). Primary delivery
# is always the Ordino in-app notification.
STALE_ALERT_SPACE = os.getenv("CONTENT_STALE_ALERT_SPACE", "") or os.getenv("PASSIVE_LISTEN_SPACE", "")


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
        # Staleness watchdog state. Keyed on the stuck last-candidate date so we alert
        # ONCE per stale streak (not every daily run); reset when candidates resume.
        self._last_stale_alert_key: Optional[str] = None
        self._last_stale_alert_at: Optional[str] = None

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
            "stale_alert_days": STALE_ALERT_DAYS,
            "last_stale_alert_key": self._last_stale_alert_key,
            "last_stale_alert_at": self._last_stale_alert_at,
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

            # Watchdog runs regardless of run_once's outcome — a crashing run_once is
            # itself a reason the pipeline could go quiet. Never let a watchdog error
            # break the scheduler loop.
            try:
                self._check_staleness()
            except Exception as e:
                logger.warning(f"[ContentScheduler] staleness watchdog error: {e}")

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

    # ------------------------------------------------------------------
    # Staleness watchdog
    # ------------------------------------------------------------------
    def _check_staleness(self):
        """Alert if the content pipeline has gone quiet.

        Computes days since the most recent content_candidates.created_at and fires a
        single alert per stale streak once it exceeds CONTENT_STALE_ALERT_DAYS. The
        streak is keyed on the stuck last-candidate date, so we alert once — not every
        daily run — and re-alert only if it goes stale again after recovering.
        """
        latest = self._latest_candidate_date()
        if latest is None:
            # Can't determine (no candidates returned or analytics store unavailable) —
            # don't false-alarm; we alert only on a real, datable stale streak.
            return

        days = (datetime.now(timezone.utc) - latest).days
        if days <= STALE_ALERT_DAYS:
            # Pipeline is healthy — clear the streak so a future stall re-alerts.
            self._last_stale_alert_key = None
            return

        key = latest.date().isoformat()
        if self._last_stale_alert_key == key:
            return  # already alerted for this stale streak; don't spam daily

        self._fire_stale_alert(days, key)
        self._last_stale_alert_key = key
        self._last_stale_alert_at = datetime.now(timezone.utc).isoformat()

    def _latest_candidate_date(self) -> Optional[datetime]:
        """Most recent content_candidates.created_at across ALL statuses, tz-aware UTC.

        Returns None if the analytics store is unavailable or has no candidates. Uses
        the same Supabase-backed store the engine writes candidates to; the edge
        function orders by relevance (not date), so we fetch a generous batch and take
        the max created_at rather than trusting order.
        """
        adb = getattr(self.engine, "analytics_db", None)
        if adb is None or not hasattr(adb, "get_content_candidates"):
            return None
        # status=None → no status filter server-side → all statuses (a candidate that
        # already advanced to drafted/approved still counts as "created").
        rows = adb.get_content_candidates(status=None, limit=1000) or []
        latest = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            dt = self._parse_ts(r.get("created_at"))
            if dt and (latest is None or dt > latest):
                latest = dt
        return latest

    @staticmethod
    def _parse_ts(ts) -> Optional[datetime]:
        """Parse an ISO timestamp to tz-aware UTC; naive input is assumed UTC
        (candidates store datetime.now().isoformat()). Returns None on failure."""
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _fire_stale_alert(self, days: int, last_date: str):
        """Deliver the staleness alert.

        Channel choice (per product decision):
          * PRIMARY — Ordino in-app notification (top notification bell). Reuses the
            existing Beacon→Ordino write path (beacon-analytics `notify_ingest`), the
            same one KB-ingests use. No new OAuth scope.
          * SECONDARY (optional) — Google Chat to Beacon's configured space, via the
            chat.bot app-auth Beacon already holds (GoogleChatClient). No new scope.
            Only fires when CONTENT_STALE_ALERT_SPACE / PASSIVE_LISTEN_SPACE is set.
          * Email — intentionally NOT implemented: gmail send would require adding the
            gmail.send scope to Beacon's service account (a manual step). Commented
            hook left below.
        """
        msg = (f"Content pipeline: no new candidates in {days} days (last: {last_date}). "
               f"Check /api/content-scheduler/status and newsletter parsing.")
        logger.warning(f"[ContentScheduler] STALE — {msg}")

        # --- PRIMARY: Ordino in-app notification (notification bell) ---
        adb = getattr(self.engine, "analytics_db", None)
        if adb is not None and hasattr(adb, "notify_ingest"):
            try:
                adb.notify_ingest(
                    title=f"Content pipeline quiet — {days} days, no new candidates",
                    body=msg,
                    link="/content",
                )
            except Exception as e:
                logger.warning(f"[ContentScheduler] Ordino stale-alert notify failed: {e}")

        # --- SECONDARY (optional): Google Chat to Beacon's space ---
        if STALE_ALERT_SPACE:
            try:
                from core.google_chat import GoogleChatClient
                GoogleChatClient().send_message(STALE_ALERT_SPACE, f"⚠️ {msg}")
            except Exception as e:
                logger.warning(f"[ContentScheduler] GChat stale-alert failed: {e}")

        # --- EMAIL (NOT implemented — needs gmail.send scope on the Beacon SA) ---
        # Left as a hook intentionally. To enable, add the gmail.send scope to the
        # service account (a Manny step), then wire a sender here, e.g.:
        #   recipient = os.getenv("CONTENT_STALE_ALERT_EMAIL")
        #   if recipient:
        #       send_gmail(recipient, "Beacon content pipeline stale", msg)
