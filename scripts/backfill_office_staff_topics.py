#!/usr/bin/env python3
"""
One-time backfill: mine the Office Staff Google Chat history for past work
questions, classify them by topic, and log them to Beacon analytics as
gap/topic signal (answered=False, command='passive_backfill') so the Topics
breakdown + content backlog reflect HISTORY, not just go-forward capture.

Reuses the same building blocks the live passive listener uses (the GChat client,
the zero-cost question filter, the TopicClassifier). Paginates through the full
space history (the listener's own _list_messages only returns one page).

Run inside the Beacon runtime (so deps + GChat auth + analytics keys exist):
    python scripts/backfill_office_staff_topics.py            # DRY-RUN (no writes) — default
    python scripts/backfill_office_staff_topics.py --write    # actually log to analytics

DRY-RUN prints how many messages were scanned, how many are work questions, and
the topic breakdown — so you can sanity-check before writing anything.
"""
import os
import sys
from datetime import datetime
from urllib.parse import urlencode

from config import Settings
from core.google_chat import GoogleChatClient
from analytics.topic_classifier import get_classifier
from features.passive_listener import is_relevant_question

WRITE = "--write" in sys.argv
SPACE = os.getenv("PASSIVE_LISTEN_SPACE", "")


def main():
    if not SPACE:
        sys.exit("PASSIVE_LISTEN_SPACE is not set — nothing to back-fill.")

    settings = Settings()
    chat = GoogleChatClient(settings)
    classifier = get_classifier()

    analytics_db = None
    if WRITE:
        from analytics.analytics_supabase import SupabaseAnalyticsDB
        key = os.getenv("BEACON_ANALYTICS_KEY", "")
        if not (settings.supabase_url and key):
            sys.exit("--write requested but SUPABASE_URL / BEACON_ANALYTICS_KEY are missing.")
        analytics_db = SupabaseAnalyticsDB(settings.supabase_url, key)

    from analytics.analytics import Interaction

    base = f"{chat.BASE_URL}/{SPACE}/messages"
    page_token = None
    scanned = questions = written = 0
    by_topic: dict[str, int] = {}

    while True:
        params = {"pageSize": 100, "orderBy": "createTime asc"}
        if page_token:
            params["pageToken"] = page_token
        resp = chat._make_request("GET", f"{base}?{urlencode(params)}")
        if resp.status_code != 200:
            print(f"list failed: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            break

        data = resp.json()
        for m in data.get("messages", []):
            scanned += 1
            text = m.get("text", "") or ""
            relevant, _reason = is_relevant_question(text)
            if not relevant:
                continue
            questions += 1
            topic = classifier.classify(text)
            by_topic[topic] = by_topic.get(topic, 0) + 1
            if WRITE and analytics_db:
                sender = m.get("sender", {}) or {}
                try:
                    analytics_db.log_interaction(Interaction(
                        timestamp=m.get("createTime") or datetime.now().isoformat(),
                        user_id=sender.get("name", "backfill"),
                        user_name=sender.get("displayName", "Backfill"),
                        space_name=SPACE,
                        question=text,
                        response=None,
                        command="passive_backfill",
                        answered=False,
                        response_length=0,
                        had_sources=False,
                        sources_used=[],
                        tokens_used=0,
                        cost_usd=0.0,
                        response_time_ms=0,
                        confidence=0.0,
                        topic=topic,
                    ))
                    written += 1
                except Exception as e:
                    print(f"  log failed for one message: {e}", file=sys.stderr)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    mode = "WROTE" if WRITE else "DRY-RUN"
    print(f"\n{mode} — scanned {scanned} messages, {questions} work questions"
          + (f", logged {written}" if WRITE else ""))
    for t, n in sorted(by_topic.items(), key=lambda x: -x[1]):
        print(f"  {n:4}  {t}")
    if not WRITE:
        print("\n(dry-run — nothing written. Re-run with --write to log these into Beacon analytics.)")


if __name__ == "__main__":
    main()
