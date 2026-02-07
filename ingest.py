#!/usr/bin/env python3
"""
Document ingestion script for the RAG knowledge base.
Use this to add PDFs and other documents to the vector store.

Usage:
    python ingest.py path/to/document.pdf
    python ingest.py path/to/folder/  # Ingest all PDFs in folder
    python ingest.py --stats           # Show current index stats
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


def ingest_pdf(
    file_path: Path,
    vector_store: VectorStore,
    processor: DocumentProcessor,
    source_type: str | None = None,
) -> int:
    """Ingest a single PDF file.

    Args:
        file_path: Path to the PDF file
        vector_store: Vector store instance
        processor: Document processor instance
        source_type: Optional override for document type

    Returns:
        Number of chunks ingested
    """
    logger.info(f"Processing: {file_path}")

    # Auto-detect document type if not specified
    if source_type is None:
        source_type = detect_document_type(file_path.name)
        logger.info(f"  Detected type: {source_type}")

    # Process the PDF into chunks
    document = processor.process_pdf(
        file_path=file_path,
        source_type=source_type,
    )

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
    """Ingest all PDFs in a folder.

    Args:
        folder_path: Path to the folder
        vector_store: Vector store instance
        processor: Document processor instance

    Returns:
        Tuple of (files processed, total chunks)
    """
    pdf_files = list(folder_path.glob("**/*.pdf"))
    logger.info(f"Found {len(pdf_files)} PDF files in {folder_path}")

    total_files = 0
    total_chunks = 0

    for pdf_file in pdf_files:
        try:
            chunks = ingest_pdf(pdf_file, vector_store, processor)
            total_files += 1
            total_chunks += chunks
        except Exception as e:
            logger.error(f"Failed to process {pdf_file}: {e}")

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
        description="Ingest documents into the RAG knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest.py document.pdf                    # Ingest single PDF
  python ingest.py ./documents/                    # Ingest folder of PDFs
  python ingest.py doc.pdf --type determination    # Specify document type
  python ingest.py --stats                         # Show index statistics

Document Types:
  - determination     DOB determination letters (CCD1, ZRD)
  - service_notice    Violation notices, service documents
  - reconsideration   Appeal/reconsideration documents
  - internal_memo     Internal procedures and notes
  - document          Generic (auto-detected)
        """,
    )

    parser.add_argument(
        "path",
        nargs="?",
        help="Path to PDF file or folder to ingest",
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=[
            "determination",
            "service_notice",
            "reconsideration",
            "internal_memo",
            "document",
        ],
        help="Document type (auto-detected if not specified)",
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

    # Validate arguments
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

    # Handle stats request
    if args.stats:
        show_stats(vector_store)
        return

    # Handle file/folder ingestion
    path = Path(args.path)

    if not path.exists():
        logger.error(f"Path not found: {path}")
        sys.exit(1)

    if path.is_file():
        if not path.suffix.lower() == ".pdf":
            logger.error("Only PDF files are currently supported")
            sys.exit(1)

        chunks = ingest_pdf(path, vector_store, processor, args.type)
        print(f"\n✅ Ingested {chunks} chunks from {path.name}")

    elif path.is_dir():
        files, chunks = ingest_folder(path, vector_store, processor)
        print(f"\n✅ Ingested {chunks} chunks from {files} files")

    # Show updated stats
    show_stats(vector_store)


if __name__ == "__main__":
    main()
