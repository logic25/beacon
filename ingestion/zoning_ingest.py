#!/usr/bin/env python3
"""
NYC Zoning Resolution ingestion script.
Specialized for parsing and ingesting the ZR with proper metadata.

The Zoning Resolution is available at: https://zr.planning.nyc.gov/

Structure:
- Article I: General Provisions
- Article II: Use Regulations (CRITICAL - Use Groups 1-18)
- Article III: Residential District Bulk (R1-R10)
- Article IV: Commercial District Bulk (C1-C8)
- Article V: Non-Conforming Uses
- Article VI: Special Regulations
- Article VII: Special Permits
- Articles VIII-XIII: Special Purpose Districts
- Article XIV: General Amendments

Usage:
    python zoning_ingest.py path/to/zr_article.pdf --article II
    python zoning_ingest.py ./zr_pdfs/  # Ingest all PDFs in folder
    python zoning_ingest.py --download  # Download ZR from zr.planning.nyc.gov
"""

import argparse
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import get_settings
from ingestion.document_processor import DocumentProcessor
from core.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Zoning Resolution structure
ZR_ARTICLES = {
    "I": {"name": "General Provisions", "priority": "low"},
    "II": {"name": "Use Regulations", "priority": "critical"},  # Use Groups!
    "III": {"name": "Residential District Bulk", "priority": "high"},
    "IV": {"name": "Commercial District Bulk", "priority": "high"},
    "V": {"name": "Non-Conforming Uses", "priority": "medium"},
    "VI": {"name": "Special Regulations", "priority": "medium"},
    "VII": {"name": "Special Permits", "priority": "medium"},
    "VIII": {"name": "Special Purpose Districts", "priority": "medium"},
    "IX": {"name": "Special Purpose Districts (cont)", "priority": "medium"},
    "X": {"name": "Special Purpose Districts (cont)", "priority": "medium"},
    "XI": {"name": "Special Purpose Districts (cont)", "priority": "medium"},
    "XII": {"name": "Inclusionary Housing", "priority": "high"},
    "XIII": {"name": "Special Purpose Districts (cont)", "priority": "medium"},
    "XIV": {"name": "General Amendments", "priority": "low"},
}

# Zoning district patterns for detection
ZONING_DISTRICTS = {
    "residential": r'\b(R[1-9]0?[A-Z]?(?:-[1-3])?)\b',
    "commercial": r'\b(C[1-8]-[0-9][A-Z]?)\b',
    "manufacturing": r'\b(M[1-3]-[0-9][A-Z]?)\b',
    "special": r'\b(S[A-Z]{2,})\b',
}

# Use Group patterns (Article II)
USE_GROUP_PATTERN = r'Use Group\s*(\d+[A-D]?)'


@dataclass
class ZRSection:
    """A section of the Zoning Resolution."""

    article: str
    section_number: str
    section_title: str
    content: str
    districts_mentioned: list[str] = field(default_factory=list)
    use_groups_mentioned: list[str] = field(default_factory=list)
    page_number: Optional[int] = None

    def to_metadata(self) -> dict:
        """Convert to metadata dict for vector storage."""
        article_info = ZR_ARTICLES.get(self.article, {})
        return {
            "source_type": "zoning_resolution",
            "article": self.article,
            "article_name": article_info.get("name", "Unknown"),
            "priority": article_info.get("priority", "medium"),
            "section_number": self.section_number,
            "section_title": self.section_title,
            "districts": ",".join(self.districts_mentioned) if self.districts_mentioned else "",
            "use_groups": ",".join(self.use_groups_mentioned) if self.use_groups_mentioned else "",
            "page_number": self.page_number,
        }


class ZRProcessor:
    """Specialized processor for Zoning Resolution documents."""

    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 300):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.base_processor = DocumentProcessor(chunk_size, chunk_overlap)

    def _detect_districts(self, text: str) -> list[str]:
        """Find all zoning districts mentioned in text."""
        districts = []
        for district_type, pattern in ZONING_DISTRICTS.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            districts.extend(matches)
        return list(set(districts))

    def _detect_use_groups(self, text: str) -> list[str]:
        """Find all Use Groups mentioned in text."""
        matches = re.findall(USE_GROUP_PATTERN, text, re.IGNORECASE)
        return list(set(matches))

    def _detect_article(self, text: str, filename: str) -> str:
        """Try to detect which article this is from."""
        # Check filename first
        for article in ZR_ARTICLES.keys():
            if f"article{article.lower()}" in filename.lower().replace(" ", "").replace("_", ""):
                return article
            if f"art{article.lower()}" in filename.lower().replace(" ", "").replace("_", ""):
                return article

        # Check content for article header
        article_pattern = r'ARTICLE\s+([IVX]+)'
        match = re.search(article_pattern, text[:5000])
        if match:
            return match.group(1)

        return "Unknown"

    def _parse_sections(self, text: str, article: str) -> list[ZRSection]:
        """Parse text into ZR sections."""
        sections = []

        # ZR sections typically start with section numbers like "23-00" or "12-10"
        section_pattern = r'(?:Section\s+)?(\d{2}-\d{2}[A-Z]?)\s*\n?\s*([A-Z][^.]*?)(?:\n|\.)'

        # Split by section markers
        parts = re.split(section_pattern, text)

        current_section = None
        current_content = []

        for i, part in enumerate(parts):
            # Check if this looks like a section number
            if re.match(r'\d{2}-\d{2}[A-Z]?', part.strip()):
                # Save previous section
                if current_section and current_content:
                    content = " ".join(current_content)
                    sections.append(ZRSection(
                        article=article,
                        section_number=current_section["number"],
                        section_title=current_section["title"],
                        content=content,
                        districts_mentioned=self._detect_districts(content),
                        use_groups_mentioned=self._detect_use_groups(content),
                    ))

                # Start new section
                title = parts[i + 1] if i + 1 < len(parts) else ""
                current_section = {
                    "number": part.strip(),
                    "title": title.strip() if title else "Untitled",
                }
                current_content = []
            elif current_section:
                # Add to current section content
                if part.strip():
                    current_content.append(part.strip())

        # Don't forget the last section
        if current_section and current_content:
            content = " ".join(current_content)
            sections.append(ZRSection(
                article=article,
                section_number=current_section["number"],
                section_title=current_section["title"],
                content=content,
                districts_mentioned=self._detect_districts(content),
                use_groups_mentioned=self._detect_use_groups(content),
            ))

        # If no sections found, treat whole doc as one section
        if not sections:
            sections.append(ZRSection(
                article=article,
                section_number="00-00",
                section_title="General",
                content=text,
                districts_mentioned=self._detect_districts(text),
                use_groups_mentioned=self._detect_use_groups(text),
            ))

        return sections

    def process_pdf(
        self,
        file_path: Path,
        article: Optional[str] = None,
    ) -> list[dict]:
        """Process a ZR PDF and return chunks with metadata.

        Args:
            file_path: Path to the PDF
            article: Article number (auto-detected if not provided)

        Returns:
            List of chunks ready for vector store
        """
        try:
            import pymupdf
        except ImportError:
            raise ImportError("PyMuPDF required: pip install pymupdf")

        logger.info(f"Processing ZR PDF: {file_path}")

        # Extract text
        full_text = ""
        with pymupdf.open(file_path) as doc:
            for page in doc:
                full_text += page.get_text() + "\n"

        # Detect article if not provided
        if not article:
            article = self._detect_article(full_text, file_path.name)
        logger.info(f"Article: {article} ({ZR_ARTICLES.get(article, {}).get('name', 'Unknown')})")

        # Parse into sections
        sections = self._parse_sections(full_text, article)
        logger.info(f"Found {len(sections)} sections")

        # Create chunks from sections
        chunks = []
        from ingestion.document_processor import DocumentChunk
        import hashlib

        for section in sections:
            # If section is too long, split it
            if len(section.content) > self.chunk_size:
                # Use base processor to chunk
                section_chunks = self._chunk_section(section)
                chunks.extend(section_chunks)
            else:
                # Section fits in one chunk
                chunk_id = hashlib.md5(
                    f"{file_path}:{section.section_number}".encode()
                ).hexdigest()[:16]

                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    text=section.content,
                    source_file=f"ZR Article {article} - {section.section_number}",
                    source_type="zoning_resolution",
                    chunk_index=0,
                    metadata=section.to_metadata(),
                ))

        logger.info(f"Created {len(chunks)} chunks from {file_path.name}")
        return chunks

    def _chunk_section(self, section: ZRSection) -> list:
        """Split a large section into multiple chunks."""
        from ingestion.document_processor import DocumentChunk
        import hashlib

        chunks = []
        text = section.content

        # Split on paragraph breaks when possible
        paragraphs = re.split(r'\n\s*\n', text)

        current_chunk = ""
        chunk_idx = 0

        for para in paragraphs:
            if len(current_chunk) + len(para) > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_id = hashlib.md5(
                    f"{section.section_number}:{chunk_idx}".encode()
                ).hexdigest()[:16]

                metadata = section.to_metadata()
                metadata["chunk_index"] = chunk_idx

                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    text=current_chunk.strip(),
                    source_file=f"ZR Article {section.article} - {section.section_number}",
                    source_type="zoning_resolution",
                    chunk_index=chunk_idx,
                    metadata=metadata,
                ))

                chunk_idx += 1
                # Keep some overlap
                words = current_chunk.split()
                overlap_words = words[-50:] if len(words) > 50 else []
                current_chunk = " ".join(overlap_words) + " " + para
            else:
                current_chunk += " " + para

        # Don't forget the last chunk
        if current_chunk.strip():
            chunk_id = hashlib.md5(
                f"{section.section_number}:{chunk_idx}".encode()
            ).hexdigest()[:16]

            metadata = section.to_metadata()
            metadata["chunk_index"] = chunk_idx

            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                text=current_chunk.strip(),
                source_file=f"ZR Article {section.article} - {section.section_number}",
                source_type="zoning_resolution",
                chunk_index=chunk_idx,
                metadata=metadata,
            ))

        return chunks


def download_zr_pdfs(output_dir: Path) -> list[Path]:
    """Download Zoning Resolution PDFs from zr.planning.nyc.gov.

    Note: The ZR website doesn't have direct PDF links easily scraped.
    This function provides instructions for manual download.
    """
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║                    Zoning Resolution Download                         ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  The ZR is available at: https://zr.planning.nyc.gov/                ║
║                                                                       ║
║  RECOMMENDED APPROACH:                                                ║
║                                                                       ║
║  1. Start with the most critical articles:                           ║
║     - Article II: Use Regulations (Use Groups 1-18)                  ║
║     - Article III: Residential Bulk (R districts)                    ║
║     - Article IV: Commercial Bulk (C districts)                      ║
║                                                                       ║
║  2. Download from DCP's website or use these resources:              ║
║     - zr.planning.nyc.gov (interactive, section by section)          ║
║     - DCP has full PDF compilations periodically                     ║
║                                                                       ║
║  3. Place PDFs in: {output_dir}                                      ║
║                                                                       ║
║  4. Run: python zoning_ingest.py {output_dir}                        ║
║                                                                       ║
║  ALTERNATIVE: Use the Use Group tables (smaller, very useful)        ║
║     - These define what uses are allowed in each district            ║
║     - Available as appendices to Article II                          ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝
""".format(output_dir=output_dir))

    output_dir.mkdir(parents=True, exist_ok=True)
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Ingest NYC Zoning Resolution into RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python zoning_ingest.py article_ii.pdf --article II
    python zoning_ingest.py ./zr_pdfs/
    python zoning_ingest.py --download
    python zoning_ingest.py --stats

Priority Articles for Practical Use:
    Article II:  Use Groups (CRITICAL - what's allowed where)
    Article III: Residential bulk (FAR, height, setbacks for R districts)
    Article IV:  Commercial bulk (FAR, height for C districts)
        """,
    )

    parser.add_argument("path", nargs="?", help="Path to PDF or folder of PDFs")
    parser.add_argument("--article", "-a", help="Article number (e.g., II, III)")
    parser.add_argument("--download", "-d", action="store_true", help="Show download instructions")
    parser.add_argument("--stats", "-s", action="store_true", help="Show current ZR stats in index")

    args = parser.parse_args()

    # Initialize
    settings = get_settings()

    if not settings.pinecone_api_key:
        print("❌ PINECONE_API_KEY not set")
        return

    vector_store = VectorStore(settings)
    processor = ZRProcessor()

    if args.download:
        download_zr_pdfs(Path("./zr_pdfs"))
        return

    if args.stats:
        stats = vector_store.get_stats()
        print(f"\n📊 Vector Store: {stats['total_vectors']} total vectors")
        # TODO: Query for ZR-specific stats
        return

    if not args.path:
        parser.print_help()
        return

    path = Path(args.path)

    if not path.exists():
        print(f"❌ Path not found: {path}")
        return

    total_chunks = 0

    if path.is_file():
        chunks = processor.process_pdf(path, args.article)
        count = vector_store.upsert_chunks(chunks)
        total_chunks += count
        print(f"✅ Ingested {count} chunks from {path.name}")

    elif path.is_dir():
        for pdf_file in path.glob("**/*.pdf"):
            try:
                chunks = processor.process_pdf(pdf_file, args.article)
                count = vector_store.upsert_chunks(chunks)
                total_chunks += count
                print(f"✅ Ingested {count} chunks from {pdf_file.name}")
            except Exception as e:
                print(f"❌ Failed to process {pdf_file.name}: {e}")

    print(f"\n🎉 Total: {total_chunks} chunks ingested to Pinecone")

    # Show updated stats
    stats = vector_store.get_stats()
    print(f"📊 Index now has {stats['total_vectors']} vectors")


if __name__ == "__main__":
    main()
