#!/usr/bin/env python3
"""
Corpus analysis for the Beacon content engine — READ ONLY, deletes nothing.

Two outputs from one pull of beacon_interactions:

  1. CONTAMINATION REPORT — machine/tool-formatted queries that were logged as
     "team questions" but aren't (e.g. the 228 Greene Ave research query with
     "no markdown / Filing Type:" scaffolding). These are already BLOCKED at
     read-time by the content engine; this shows which rows still sit in the store
     and should be cleaned out.

  2. DEMAND RANKING — the clean questions tagged by topic and ranked by volume:
     what your team actually asks about most = your data-driven content roadmap.

Run:  cd ~/beacon && python3 analyze_corpus.py
Needs SUPABASE_URL + BEACON_ANALYTICS_KEY in the environment (same as the engine).
"""
import os
import requests
from collections import Counter

# Keep in sync with content_engine/engine.py `_query_team_questions_supabase`.
CONTAMINATION = (
    "[instructions", "[context:", "[system instruction", "<!--bug_report",
    "respond conversationally like", "no markdown", "no bold", "no asterisks",
    "no emojis", "no headers", "in plain text", "just clear, factual paragraphs",
    "answer this", "citing specific code sections", "filing type:",
)

TOPIC_MAP = {
    "DOB Filings": ["dob", "permit", "filing", "alt1", "alt2", "alt-1", "alt-2", "nb ", "paa", "pw1", "pw2"],
    "Objections": ["objection", "disapproval", "examiner", "comment"],
    "Zoning": ["zoning", "use group", "far ", "setback", "variance", "zr ", "contextual"],
    "Certificate of Occupancy": ["certificate of occupancy", "tco", "c of o", " co "],
    "Violations": ["violation", "ecb", "oath", "dob violation", "hpd violation"],
    "FDNY": ["fdny", "sprinkler", "fire alarm", "standpipe", "fire department"],
    "Building Code": ["building code", "egress", "occupancy", "nycecc", " bc ", " mc "],
    "DOB NOW / System status": ["dob now", "portal", "login", "system down", "error", "glitch"],
    "Fees": ["fee", "how much", "cost", "$"],
    "Landmarks / DOT / DEP": ["landmark", "lpc", "dot", "dep", "sidewalk", "curb cut"],
}


def topic_of(q: str) -> str:
    ql = f" {q.lower()} "
    for topic, kws in TOPIC_MAP.items():
        if any(k in ql for k in kws):
            return topic
    return "Other / Uncategorized"


def main() -> None:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("BEACON_ANALYTICS_KEY", "")
    if not url or not key:
        print("Missing SUPABASE_URL or BEACON_ANALYTICS_KEY in env.")
        return

    resp = requests.post(
        f"{url}/functions/v1/beacon-analytics",
        json={"action": "get_recent_conversations", "data": {"limit": 2000}},
        headers={"Content-Type": "application/json", "x-beacon-key": key},
        timeout=30,
    )
    resp.raise_for_status()
    r = resp.json()
    convs = r if isinstance(r, list) else r.get("conversations", [])
    print(f"Pulled {len(convs)} interactions.\n")

    contaminated, clean = [], []
    for c in convs:
        q = (c.get("question") or "").strip()
        if not q:
            continue
        if any(m in q.lower() for m in CONTAMINATION):
            contaminated.append(q)
        else:
            clean.append(q)

    print("=" * 72)
    print(f"1) CONTAMINATION — {len(contaminated)} of {len(convs)} flagged")
    print("   (already blocked at read-time; these rows should be cleaned from the store)")
    print("=" * 72)
    for q in contaminated[:40]:
        print(f"  - {q[:110]}")
    if len(contaminated) > 40:
        print(f"  ... and {len(contaminated) - 40} more")

    print("\n" + "=" * 72)
    print(f"2) DEMAND RANKING — {len(clean)} clean questions by topic (your content roadmap)")
    print("=" * 72)
    for topic, n in Counter(topic_of(q) for q in clean).most_common():
        print(f"  {n:>4}  {topic:<28} {'#' * min(40, n)}")


if __name__ == "__main__":
    main()
