"""
One-time backfill: stamp jurisdiction onto every existing Pinecone vector.

WHY THIS EXISTS / WHY IT MUST RUN BEFORE ENABLING THE CHAT FILTER:
Until now, ingested chunks had no `jurisdiction` metadata. The retriever supports
a Pinecone filter `{"jurisdiction": {"$eq": "<city>"}}`, and Pinecone treats a
MISSING field as "does not match" — so the moment the chat widget starts sending
a jurisdiction, every already-indexed (un-tagged) chunk would be silently excluded
from retrieval. This script tags the whole existing corpus so that filter is safe.

Green Light is NYC-only today, so the default is "NYC". Run once after deploying
the ingest-side jurisdiction tagging, BEFORE turning on any chat-side jurisdiction
filter.

Usage:
    python backfill_jurisdiction.py            # tags every vector "NYC"
    python backfill_jurisdiction.py --value "NYC" --dry-run
"""

import argparse
import logging

from core.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def backfill(value: str, dry_run: bool, only_missing: bool) -> None:
    store = VectorStore()
    index = store.index

    scanned = 0
    updated = 0
    skipped = 0

    # index.list() paginates over all vector IDs in the (serverless) index.
    for id_batch in index.list():
        if not id_batch:
            continue
        ids = list(id_batch)
        scanned += len(ids)

        # Decide which need tagging. With --only-missing we skip vectors that
        # already carry a jurisdiction (don't clobber future non-NYC tags).
        targets = ids
        if only_missing:
            fetched = index.fetch(ids=ids)
            targets = [
                vid
                for vid, vdata in fetched.vectors.items()
                if not (vdata.metadata or {}).get("jurisdiction")
            ]
            skipped += len(ids) - len(targets)

        for vid in targets:
            if dry_run:
                logger.info(f"[dry-run] would set jurisdiction='{value}' on {vid}")
            else:
                # Metadata-only update — no need to re-send embedding values.
                index.update(id=vid, set_metadata={"jurisdiction": value})
            updated += 1

        logger.info(f"  scanned={scanned} updated={updated} skipped={skipped}")

    logger.info(
        f"Backfill complete: scanned={scanned}, "
        f"{'would update' if dry_run else 'updated'}={updated}, skipped={skipped}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill jurisdiction metadata on Pinecone vectors.")
    parser.add_argument("--value", default="NYC", help="Jurisdiction to set (default: NYC)")
    parser.add_argument("--dry-run", action="store_true", help="Log what would change without writing")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only tag vectors that have no jurisdiction yet (don't overwrite existing tags)",
    )
    args = parser.parse_args()
    backfill(args.value, args.dry_run, args.only_missing)


if __name__ == "__main__":
    main()
