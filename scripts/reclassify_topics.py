#!/usr/bin/env python3
"""One-time: re-classify beacon_interactions.topic with the real LLM classifier.

For a stretch the classifier model 404'd, so every stored interaction was tagged
by the crude keyword fallback (phantom DHCR, etc.). Now that the LLM + the full
34-tag taxonomy are live, re-run classification over the stored rows and write
the corrected topic back.

Reads/writes go through the beacon-analytics edge function (Beacon has no direct
DB key) — requires the get_interactions_for_reclass + update_interaction_topic
actions to be DEPLOYED on the Ordino side first.

    python scripts/reclassify_topics.py            # DRY-RUN (no writes) — default
    python scripts/reclassify_topics.py --write     # write corrected topics back
"""
import os
import sys
from collections import Counter

from config import Settings
from analytics.analytics_supabase import SupabaseAnalyticsDB
from analytics.topic_classifier import get_classifier

WRITE = "--write" in sys.argv


def main():
    s = Settings()
    key = os.getenv("BEACON_ANALYTICS_KEY", "")
    if not (s.supabase_url and key):
        sys.exit("SUPABASE_URL / BEACON_ANALYTICS_KEY missing")
    db = SupabaseAnalyticsDB(s.supabase_url, key)
    clf = get_classifier()

    rows = db._call("get_interactions_for_reclass", {"limit": 10000})
    if not isinstance(rows, list):
        sys.exit(f"unexpected response (is the edge fn deployed?): {str(rows)[:200]}")

    before, after = Counter(), Counter()
    changed = 0
    total = len(rows)
    for r in rows:
        old = r.get("topic")
        before[old or "(none)"] += 1
        new = clf.classify(r.get("question") or "", r.get("response") or "")
        after[new] += 1
        if new != old:
            changed += 1
            if WRITE:
                db._call("update_interaction_topic", {"id": r["id"], "topic": new})

    mode = "WROTE" if WRITE else "DRY-RUN"
    print(f"\n{mode}: {total} rows scanned, {changed} reclassified")
    print("-- BEFORE --")
    for t, n in before.most_common():
        print(f"  {n:4}  {t}")
    print("-- AFTER --")
    for t, n in after.most_common():
        print(f"  {n:4}  {t}")
    if not WRITE:
        print("\n(dry-run — nothing written. Re-run with --write to apply.)")


if __name__ == "__main__":
    main()
