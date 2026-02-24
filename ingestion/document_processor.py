"""
Document processing for RAG ingestion.
Handles PDF parsing, text extraction, and chunking.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Doc-type-aware chunk sizes: larger chunks for docs where reasoning/context
# needs to stay intact, smaller for self-contained notices
CHUNK_SETTINGS = {
    # Determinations: legal reasoning must stay intact
    "determination": {"chunk_size": 2500, "chunk_overlap": 400},
    "historical_determination": {"chunk_size": 2500, "chunk_overlap": 400},
    # Building code / zoning: table-heavy, need surrounding context
    "building_code": {"chunk_size": 1500, "chunk_overlap": 300},
    "rule": {"chunk_size": 1500, "chunk_overlap": 300},
    "zoning": {"chunk_size": 1500, "chunk_overlap": 300},
    # Bulletins: longer technical sections
    "technical_bulletin": {"chunk_size": 1500, "chunk_overlap": 250},
    # Procedures: step-by-step, keep steps together
    "procedure": {"chunk_size": 1500, "chunk_overlap": 250},
    # Service notices: short, self-contained
    "service_notice": {"chunk_size": 1000, "chunk_overlap": 200},
    # Policy memos: medium
    "policy_memo": {"chunk_size": 1200, "chunk_overlap": 200},
    # Internal notes / historical: keep context intact
    "internal_notes": {"chunk_size": 2000, "chunk_overlap": 300},
    # Corrections: never chunked (injected whole)
    "correction": {"chunk_size": 5000, "chunk_overlap": 0},
    # Checklists / reference: keep together
    "checklist": {"chunk_size": 2000, "chunk_overlap": 200},
    "reference": {"chunk_size": 1500, "chunk_overlap": 250},
    # Out-of-NYC filings
    "out_of_nyc_filing": {"chunk_size": 1500, "chunk_overlap": 200},
}

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


def get_chunk_settings(source_type: str) -> tuple[int, int]:
    """Get chunk size and overlap for a given document type.

    Args:
        source_type: Document type string

    Returns:
        Tuple of (chunk_size, chunk_overlap)
    """
    settings = CHUNK_SETTINGS.get(source_type, {})
    return (
        settings.get("chunk_size", DEFAULT_CHUNK_SIZE),
        settings.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
    )


@dataclass
class DocumentChunk:
    """A chunk of text from a document with metadata."""

    chunk_id: str
    text: str
    source_file: str
    source_type: str  # "determination", "service_notice", "memo", etc.
    page_number: Optional[int] = None
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            **self.metadata,
        }


@dataclass
class Document:
    """A processed document with metadata."""

    file_path: str
    title: str
    source_type: str
    content: str
    chunks: list[DocumentChunk] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DocumentProcessor:
    """Process documents for RAG ingestion."""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        """Initialize the processor.

        Args:
            chunk_size: Default target size for each chunk in characters
            chunk_overlap: Default overlap between consecutive chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _generate_chunk_id(self, file_path: str, chunk_index: int) -> str:
        """Generate a unique ID for a chunk."""
        content = f"{file_path}:{chunk_index}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)
        # Remove special characters that might cause issues
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        return text.strip()

    def _chunk_text(
        self,
        text: str,
        file_path: str,
        source_type: str,
        base_metadata: dict,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> list[DocumentChunk]:
        """Split text into overlapping chunks.

        Uses doc-type-aware chunk sizes if not explicitly provided.

        Args:
            text: Full document text
            file_path: Path to source file
            source_type: Type of document
            base_metadata: Metadata to include with each chunk
            chunk_size: Override chunk size (uses doc-type default if None)
            chunk_overlap: Override overlap (uses doc-type default if None)

        Returns:
            List of DocumentChunk objects
        """
        # Use doc-type settings if not explicitly overridden
        if chunk_size is None or chunk_overlap is None:
            type_size, type_overlap = get_chunk_settings(source_type)
            chunk_size = chunk_size or type_size
            chunk_overlap = chunk_overlap or type_overlap

        chunks = []
        text = self._clean_text(text)

        if not text:
            return chunks

        # Split into sentences first for better chunk boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)

        current_chunk = ""
        chunk_index = 0

        for sentence in sentences:
            # If adding this sentence would exceed chunk size, save current chunk
            if (
                len(current_chunk) + len(sentence) > chunk_size
                and current_chunk
            ):
                chunk = DocumentChunk(
                    chunk_id=self._generate_chunk_id(file_path, chunk_index),
                    text=current_chunk.strip(),
                    source_file=Path(file_path).name,
                    source_type=source_type,
                    chunk_index=chunk_index,
                    metadata=base_metadata.copy(),
                )
                chunks.append(chunk)
                chunk_index += 1

                # Keep overlap from end of current chunk
                overlap_text = current_chunk[-chunk_overlap:] if chunk_overlap > 0 else ""
                # Find a sentence boundary in the overlap if possible
                if overlap_text:
                    overlap_match = re.search(r"[.!?]\s+", overlap_text)
                    if overlap_match:
                        current_chunk = overlap_text[overlap_match.end():]
                    else:
                        current_chunk = overlap_text
                else:
                    current_chunk = ""

            current_chunk += " " + sentence

        # Don't forget the last chunk
        if current_chunk.strip():
            chunk = DocumentChunk(
                chunk_id=self._generate_chunk_id(file_path, chunk_index),
                text=current_chunk.strip(),
                source_file=Path(file_path).name,
                source_type=source_type,
                chunk_index=chunk_index,
                metadata=base_metadata.copy(),
            )
            chunks.append(chunk)

        logger.info(
            f"Created {len(chunks)} chunks from {base_metadata.get('title', file_path)} "
            f"(type={source_type}, chunk_size={chunk_size})"
        )
        return chunks

    def process_pdf(
        self,
        file_path: str | Path,
        source_type: str = "document",
        metadata: Optional[dict] = None,
    ) -> Document:
        """Process a PDF file into chunks.

        Args:
            file_path: Path to PDF file
            source_type: Type classification (determination, service_notice, etc.)
            metadata: Additional metadata to attach

        Returns:
            Document object with chunks
        """
        try:
            import pymupdf  # PyMuPDF
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for PDF processing. "
                "Install with: pip install pymupdf"
            )

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        metadata = metadata or {}
        metadata["processed_at"] = datetime.now().isoformat()
        metadata["file_path"] = str(file_path)

        # Extract text from PDF
        full_text = ""
        page_texts = []

        with pymupdf.open(file_path) as doc:
            for page_num, page in enumerate(doc):
                page_text = page.get_text()
                page_texts.append((page_num + 1, page_text))
                full_text += page_text + "\n"

            metadata["page_count"] = len(doc)

        # Create document
        document = Document(
            file_path=str(file_path),
            title=file_path.stem,
            source_type=source_type,
            content=self._clean_text(full_text),
            metadata=metadata,
        )

        # Create chunks
        document.chunks = self._chunk_text(
            full_text,
            str(file_path),
            source_type,
            metadata,
        )

        # Try to add page numbers to chunks
        self._assign_page_numbers(document.chunks, page_texts)

        return document

    def process_text(
        self,
        text: str,
        title: str,
        source_type: str = "document",
        metadata: Optional[dict] = None,
    ) -> Document:
        """Process raw text into chunks.

        Args:
            text: Raw text content
            title: Document title/identifier
            source_type: Type classification
            metadata: Additional metadata

        Returns:
            Document object with chunks
        """
        metadata = metadata or {}
        metadata["processed_at"] = datetime.now().isoformat()

        document = Document(
            file_path=title,
            title=title,
            source_type=source_type,
            content=self._clean_text(text),
            metadata=metadata,
        )

        document.chunks = self._chunk_text(
            text,
            title,
            source_type,
            metadata,
        )

        return document

    def _assign_page_numbers(
        self,
        chunks: list[DocumentChunk],
        page_texts: list[tuple[int, str]],
    ) -> None:
        """Try to assign page numbers to chunks based on content matching."""
        for chunk in chunks:
            # Find which page contains the start of this chunk
            chunk_start = chunk.text[:100]  # First 100 chars
            for page_num, page_text in page_texts:
                if chunk_start in page_text:
                    chunk.page_number = page_num
                    break


def detect_document_type(filename: str, content: str = "") -> str:
    """Attempt to detect document type from filename and content.

    Args:
        filename: Name of the file
        content: Optional text content for detection

    Returns:
        Detected document type string
    """
    filename_lower = filename.lower()
    content_lower = content.lower()

    # Check filename patterns
    if any(x in filename_lower for x in ["determination", "det_", "ccd1", "zrd"]):
        return "determination"
    if any(x in filename_lower for x in ["service", "notice", "violation"]):
        return "service_notice"
    if any(x in filename_lower for x in ["memo", "internal", "procedure"]):
        return "internal_memo"
    if any(x in filename_lower for x in ["recon", "appeal"]):
        return "reconsideration"

    # Check content patterns
    if "determination" in content_lower and "department of buildings" in content_lower:
        return "determination"
    if "notice of violation" in content_lower:
        return "service_notice"

    return "document"
