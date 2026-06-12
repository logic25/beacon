"""
Purge a document (its chunks + manifest) from the Pinecone KB by source-file match.

Use when something got ingested that shouldn't be in the KB — e.g. the email poller
grabbed a forwarded news article during testing and filed it as a service notice.

Pinecone serverless can't delete by metadata filter, so we list every vector, fetch
metadata, and delete the IDs whose `source_file` / title contains the given substring.

Usage:
    python purge_doc.py "Columbus Circle"          # dry-run: shows what would be deleted
    python purge_doc.py "Columbus Circle" --delete  # actually delete
"""

import argparse
import logging

from core.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def purge(needle: str, do_delete: bool) -> None:
    store = VectorStore()
    index = store.index
    needle_l = needle.lower()

    matched_ids = []
    matched_titles = set()
    scanned = 0

    for id_batch in index.list():
        if not id_batch:
            continue
        ids = list(id_batch)
        scanned += len(ids)
        fetched = index.fetch(ids=ids)
        for vid, vdata in fetched.vectors.items():
            meta = vdata.metadata or {}
            hay = " ".join(
                str(meta.get(k, "")) for k in ("source_file", "title", "email_subject")
            ).lower()
            # also match the id itself (chunk/manifest ids embed the file path)
            if needle_l in hay or needle_l in vid.lower():
                matched_ids.append(vid)
                matched_titles.add(meta.get("source_file") or meta.get("title") or vid)

    logger.info(f"Scanned {scanned} vectors; {len(matched_ids)} match '{needle}'.")
    for t in sorted(matched_titles):
        logger.info(f"  • {t}")

    if not matched_ids:
        logger.info("Nothing to purge.")
        return

    if not do_delete:
        logger.info("DRY-RUN — re-run with --delete to remove these vectors.")
        return

    # Pinecone delete caps the batch size; chunk the id list.
    for i in range(0, len(matched_ids), 100):
        index.delete(ids=matched_ids[i : i + 100])
    logger.info(f"Deleted {len(matched_ids)} vectors for '{needle}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge a doc from the Pinecone KB by source-file substring.")
    parser.add_argument("needle", help="Substring to match against source_file/title/subject/id")
    parser.add_argument("--delete", action="store_true", help="Actually delete (default is dry-run)")
    args = parser.parse_args()
    purge(args.needle, args.delete)


if __name__ == "__main__":
    main()
