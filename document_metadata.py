"""
Document metadata and versioning system.
Tracks document versions, effective dates, and supersession relationships.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DocumentVersion:
    """Tracks a document's version and relationships."""

    document_id: str
    title: str
    source_type: str
    file_path: str

    # Version tracking
    effective_date: Optional[str] = None  # When this became effective
    expiration_date: Optional[str] = None  # When this expires/expired
    version: str = "1.0"

    # Supersession tracking
    supersedes: list[str] = field(default_factory=list)  # Doc IDs this replaces
    superseded_by: Optional[str] = None  # Doc ID that replaced this

    # Status
    is_current: bool = True
    notes: str = ""

    # Timestamps
    ingested_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_type": self.source_type,
            "file_path": self.file_path,
            "effective_date": self.effective_date,
            "expiration_date": self.expiration_date,
            "version": self.version,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "is_current": self.is_current,
            "notes": self.notes,
            "ingested_at": self.ingested_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentVersion":
        return cls(**data)


class DocumentRegistry:
    """
    Registry for tracking document versions and relationships.

    This helps Claude understand:
    - Which documents are current vs outdated
    - What supersedes what
    - Effective dates for regulations
    """

    def __init__(self, registry_path: str = "document_registry.json"):
        self.registry_path = Path(registry_path)
        self.documents: dict[str, DocumentVersion] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                with self.registry_path.open() as f:
                    data = json.load(f)
                    self.documents = {
                        doc_id: DocumentVersion.from_dict(doc_data)
                        for doc_id, doc_data in data.items()
                    }
                logger.info(f"Loaded {len(self.documents)} documents from registry")
            except Exception as e:
                logger.error(f"Failed to load registry: {e}")

    def save(self) -> None:
        """Save registry to disk."""
        try:
            with self.registry_path.open("w") as f:
                data = {
                    doc_id: doc.to_dict()
                    for doc_id, doc in self.documents.items()
                }
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save registry: {e}")

    def register(
        self,
        document_id: str,
        title: str,
        source_type: str,
        file_path: str,
        effective_date: Optional[str] = None,
        version: str = "1.0",
        supersedes: Optional[list[str]] = None,
        notes: str = "",
    ) -> DocumentVersion:
        """Register a new document or update existing.

        Args:
            document_id: Unique identifier for this document
            title: Human-readable title
            source_type: Type (bulletin, determination, etc.)
            file_path: Path to the source file
            effective_date: When this became/becomes effective
            version: Version string
            supersedes: List of document IDs this replaces
            notes: Any additional notes

        Returns:
            The registered DocumentVersion
        """
        supersedes = supersedes or []

        # Mark superseded documents as outdated
        for old_doc_id in supersedes:
            if old_doc_id in self.documents:
                old_doc = self.documents[old_doc_id]
                old_doc.is_current = False
                old_doc.superseded_by = document_id
                old_doc.updated_at = datetime.now().isoformat()
                logger.info(f"Marked {old_doc_id} as superseded by {document_id}")

        # Create new document version
        doc = DocumentVersion(
            document_id=document_id,
            title=title,
            source_type=source_type,
            file_path=file_path,
            effective_date=effective_date,
            version=version,
            supersedes=supersedes,
            notes=notes,
        )

        self.documents[document_id] = doc
        self.save()

        return doc

    def get_current_documents(self, source_type: Optional[str] = None) -> list[DocumentVersion]:
        """Get all current (non-superseded) documents.

        Args:
            source_type: Optional filter by type

        Returns:
            List of current documents
        """
        docs = [d for d in self.documents.values() if d.is_current]
        if source_type:
            docs = [d for d in docs if d.source_type == source_type]
        return docs

    def get_superseded_documents(self) -> list[DocumentVersion]:
        """Get all superseded documents."""
        return [d for d in self.documents.values() if not d.is_current]

    def get_document_chain(self, document_id: str) -> list[DocumentVersion]:
        """Get the full version chain for a document.

        Returns documents from oldest to newest.
        """
        chain = []
        current_id = document_id

        # Walk backwards to find oldest
        doc = self.documents.get(current_id)
        while doc and doc.supersedes:
            oldest_id = doc.supersedes[0]  # Take first superseded doc
            if oldest_id in self.documents:
                doc = self.documents[oldest_id]
                current_id = oldest_id
            else:
                break

        # Now walk forwards
        doc = self.documents.get(current_id)
        while doc:
            chain.append(doc)
            if doc.superseded_by and doc.superseded_by in self.documents:
                doc = self.documents[doc.superseded_by]
            else:
                break

        return chain

    def get_context_for_llm(self) -> str:
        """Generate context string about document versions for the LLM."""
        current = self.get_current_documents()
        superseded = self.get_superseded_documents()

        lines = ["📋 **Document Registry Status:**"]
        lines.append(f"  Current documents: {len(current)}")
        lines.append(f"  Superseded documents: {len(superseded)}")

        if superseded:
            lines.append("\n⚠️ **Note:** Some documents in the knowledge base are outdated:")
            for doc in superseded[:5]:
                replaced_by = doc.superseded_by or "unknown"
                lines.append(f"  • {doc.title} → replaced by {replaced_by}")

        return "\n".join(lines)


# Example usage for DOB Service Notices
DOB_NOTICE_TYPES = {
    "sn": "Service Notice",
    "bulletin": "Buildings Bulletin",
    "tpn": "Technical Policy Notice",
    "paa": "Policy and Procedure Notice",
}
