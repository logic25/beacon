#!/usr/bin/env python3
"""
Document ingestion script for the Beacon RAG knowledge base.
Supports PDFs and Markdown files.

Usage:
    python ingest.py knowledge/                    # Ingest all docs in folder
    python ingest.py knowledge/processes/paa_guide.md  # Single file
    python ingest.py document.pdf                  # Single PDF
    python ingest.py --stats                       # Show current index stats
"""

import argparse
import logging
import sys
from pathlib import Path

from config import get_settings
from document_processor import DocumentProcessor, detect_document_type
from vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}


def detect_type_from_path(file_path: Path) -> str:
    """Detect document type from folder structure and filename."""
    parts = [p.lower() for p in file_path.parts]

    # Check folder names for type hints
    if "service_notices" in parts:
        return "service_notice"
    if "technical_bulletins" in parts:
        return "technical_bulletin"
    if "policy_memos" in parts:
        return "policy_memo"
    if "objections" in parts:
        return "objection"
    if "processes" in parts or "procedures" in parts:
        return "procedure"
    if "communication" in parts:
        return "communication_pattern"
    if "case_studies" in parts:
        return "case_study"
    if "historical" in parts:
        return "historical_determination"
    if "building_code" in parts:
        return "building_code"
    if "zoning" in parts:
        return "zoning"

    # Fall back to filename detection
    return detect_document_type(file_path.name)


def extract_md_metadata(text: str) -> dict:
    """Extract YAML-style metadata from markdown header."""
    metadata = {}
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if value and key in {
                "title", "category", "type", "date_issued",
                "effective_date", "jurisdiction", "department",
                "source_url", "status", "notice_number",
                "added_to_beacon", "tags",
            }:
                metadata[key] = value
        # Stop scanning after first heading or blank line following metadata
        if line.startswith("# ") or line.startswith("## "):
            break

    return metadata


def ingest_file(
    file_path: Path,
    vector_store: VectorStore,
    processor: DocumentProcessor,
    source_type: str | None = None,
) -> int:
    """Ingest a single file (PDF or Markdown).

    Returns:
        Number of chunks ingested
    """
    logger.info(f"Processing: {file_path}")

    # Auto-detect document type from folder structure
    if source_type is None:
        source_type = detect_type_from_path(file_path)
        logger.info(f"  Detected type: {source_type}")

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        document = processor.process_pdf(
            file_path=file_path,
            source_type=source_type,
        )
    elif ext in {".md", ".txt"}:
        text = file_path.read_text(encoding="utf-8")
        metadata = {}

        # Extract metadata from markdown headers
        if ext == ".md":
            metadata = extract_md_metadata(text)

        metadata["file_path"] = str(file_path)

        document = processor.process_text(
            text=text,
            title=metadata.get("title", file_path.stem),
            source_type=source_type,
            metadata=metadata,
        )
    else:
        logger.warning(f"  Skipping unsupported file type: {ext}")
        return 0

    logger.info(f"  Created {len(document.chunks)} chunks")

    # Upload to vector store
    count = vector_store.upsert_chunks(document.chunks)
    logger.info(f"  Uploaded {count} chunks to Pinecone")

    return count


def ingest_folder(
    folder_path: Path,
    vector_store: VectorStore,
    processor: DocumentProcessor,
) -> tuple[int, int]:
    """Ingest all supported files in a folder (recursive)."""
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(folder_path.glob(f"**/*{ext}"))

    logger.info(f"Found {len(files)} supported files in {folder_path}")

    total_files = 0
    total_chunks = 0

    for file in sorted(files):
        try:
            chunks = ingest_file(file, vector_store, processor)
            total_files += 1
            total_chunks += chunks
        except Exception as e:
            logger.error(f"Failed to process {file}: {e}")

    return total_files, total_chunks


def show_stats(vector_store: VectorStore) -> None:
    """Display current index statistics."""
    stats = vector_store.get_stats()
    print("\n📊 Vector Store Statistics")
    print("=" * 40)
    print(f"  Total vectors: {stats['total_vectors']:,}")
    print(f"  Dimension: {stats['dimension']}")
    print("=" * 40)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest documents into the Beacon knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest.py knowledge/                          # Ingest all docs
  python ingest.py knowledge/processes/paa_guide.md    # Single markdown
  python ingest.py document.pdf                        # Single PDF
  python ingest.py doc.pdf --type determination        # Specify type
  python ingest.py --stats                             # Show index stats
        """,
    )

    parser.add_argument(
        "path",
        nargs="?",
        help="Path to file or folder to ingest",
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=[
            "determination",
            "service_notice",
            "technical_bulletin",
            "policy_memo",
            "procedure",
            "objection",
            "communication_pattern",
            "case_study",
            "historical_determination",
            "building_code",
            "zoning",
            "document",
        ],
        help="Document type (auto-detected from folder structure if not specified)",
    )
    parser.add_argument(
        "--stats",
        "-s",
        action="store_true",
        help="Show current index statistics",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Chunk size in characters (default: 1000)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Chunk overlap in characters (default: 200)",
    )

    args = parser.parse_args()

    if not args.stats and not args.path:
        parser.error("Either --stats or a path is required")

    # Initialize components
    try:
        settings = get_settings()

        if not settings.pinecone_api_key:
            logger.error("PINECONE_API_KEY not set in environment")
            sys.exit(1)

        vector_store = VectorStore(settings)
        processor = DocumentProcessor(
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        sys.exit(1)

    if args.stats:
        show_stats(vector_store)
        return

    path = Path(args.path)

    if not path.exists():
        logger.error(f"Path not found: {path}")
        sys.exit(1)

    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.error(f"Unsupported file type: {path.suffix}")
            logger.error(f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}")
            sys.exit(1)

        chunks = ingest_file(path, vector_store, processor, args.type)
        print(f"\n✅ Ingested {chunks} chunks from {path.name}")

    elif path.is_dir():
        files, chunks = ingest_folder(path, vector_store, processor)
        print(f"\n✅ Ingested {chunks} chunks from {files} files")

    show_stats(vector_store)


if __name__ == "__main__":
    main()
