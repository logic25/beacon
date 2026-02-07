"""
Retrieval module for RAG.
Handles document retrieval, context formatting with source citations,
and correction injection from the knowledge base.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Settings, get_settings
from vector_store import VectorStore

logger = logging.getLogger(__name__)

# Document authority hierarchy: higher number = higher authority
# When docs conflict, prefer higher-authority sources
DOC_AUTHORITY = {
    "determination": 10,       # DOB rulings — highest authority
    "building_code": 9,        # Code text
    "rule": 9,                 # 1 RCNY rules
    "zoning": 9,               # Zoning Resolution
    "technical_bulletin": 8,   # BBs and TPPNs
    "policy_memo": 7,          # DOB policy memos
    "service_notice": 6,       # DOB service notices
    "procedure": 5,            # GLE internal procedures
    "correction": 10,          # Team corrections — always override
    "checklist": 4,
    "reference": 4,
    "internal_notes": 3,       # Historical notes
    "historical_determination": 8,
    "out_of_nyc_filing": 3,
    "document": 2,             # Generic / unclassified
}


@dataclass
class RetrievalResult:
    """Result from document retrieval."""

    context: str  # Formatted context for LLM
    sources: list[dict]  # Source documents for citations
    query: str
    num_results: int


class Retriever:
    """Document retriever with source tracking and corrections overlay."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        settings: Optional[Settings] = None,
        knowledge_base_path: str = "knowledge_base.json",
    ):
        """Initialize the retriever.

        Args:
            vector_store: Vector store instance (creates one if not provided)
            settings: Application settings
            knowledge_base_path: Path to knowledge_base.json for corrections
        """
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStore(self.settings)
        self.knowledge_base_path = Path(knowledge_base_path)

    def _load_corrections(self) -> list[dict]:
        """Load corrections from knowledge_base.json.

        Returns:
            List of correction entries
        """
        if not self.knowledge_base_path.exists():
            return []

        try:
            with self.knowledge_base_path.open() as f:
                data = json.load(f)

            corrections = []
            for entry_id, entry in data.items():
                if entry.get("entry_type") == "correction":
                    corrections.append(entry)

            return corrections
        except Exception as e:
            logger.warning(f"Failed to load corrections: {e}")
            return []

    def _find_relevant_corrections(self, query: str) -> list[dict]:
        """Find corrections relevant to the current query.

        Simple keyword matching — corrections are few enough that we can
        check all of them on every query without performance issues.

        Args:
            query: User's question

        Returns:
            List of relevant correction entries
        """
        corrections = self._load_corrections()
        if not corrections:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        relevant = []
        for correction in corrections:
            # Check if any topic keywords match the query
            topics = [t.lower() for t in correction.get("topics", [])]
            question = correction.get("question", "").lower()
            answer = correction.get("answer", "").lower()

            # Score relevance by keyword overlap
            all_correction_text = " ".join(topics + [question, answer])
            correction_words = set(all_correction_text.split())

            overlap = query_words & correction_words
            # Require at least 2 meaningful word matches (skip tiny words)
            meaningful_overlap = [w for w in overlap if len(w) > 3]

            if len(meaningful_overlap) >= 2:
                relevant.append(correction)

        return relevant

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
        source_type: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve relevant documents for a query.

        Checks both Pinecone vector store AND local corrections database.
        Corrections are injected as highest-priority context.

        Args:
            query: User's question/query
            top_k: Maximum number of documents to retrieve
            min_score: Minimum similarity score threshold
            source_type: Optional filter by document type

        Returns:
            RetrievalResult with formatted context and sources
        """
        # Search vector store
        results = self.vector_store.search(
            query=query,
            top_k=top_k,
            source_type_filter=source_type,
        )

        # Filter by minimum score
        filtered_results = [r for r in results if r["score"] >= min_score]

        # Check for relevant corrections
        corrections = self._find_relevant_corrections(query)

        if not filtered_results and not corrections:
            logger.info(f"No results above threshold {min_score} for query: {query[:50]}...")
            return RetrievalResult(
                context="",
                sources=[],
                query=query,
                num_results=0,
            )

        # Format context for LLM — corrections first (highest priority)
        context = self._format_context(filtered_results, corrections)

        # Format sources for citation
        sources = self._format_sources(filtered_results, corrections)

        total_results = len(filtered_results) + len(corrections)
        logger.info(
            f"Retrieved {len(filtered_results)} documents + {len(corrections)} corrections "
            f"for query: {query[:50]}..."
        )

        return RetrievalResult(
            context=context,
            sources=sources,
            query=query,
            num_results=total_results,
        )

    def _format_context(
        self, results: list[dict], corrections: list[dict]
    ) -> str:
        """Format retrieved documents and corrections as context for the LLM.

        Corrections appear first as they override other sources.

        Args:
            results: Search results from vector store
            corrections: Relevant corrections from knowledge base

        Returns:
            Formatted context string
        """
        context_parts = []

        # Corrections first — highest priority
        if corrections:
            context_parts.append(
                "⚠️ TEAM CORRECTIONS (these override other sources):"
            )
            for i, correction in enumerate(corrections, 1):
                context_parts.append(
                    f"[Correction {i}]\n"
                    f"Issue: {correction.get('question', '')}\n"
                    f"Correct answer: {correction.get('answer', '')}"
                )
            context_parts.append("---")

        # Document hierarchy note
        if len(results) > 1:
            # Sort results by authority level (higher = more authoritative)
            results_with_authority = []
            for r in results:
                source_type = r.get("source_type", "document")
                authority = DOC_AUTHORITY.get(source_type, 2)
                results_with_authority.append((authority, r))

            # Sort by authority (desc), then by score (desc)
            results_with_authority.sort(
                key=lambda x: (x[0], x[1]["score"]), reverse=True
            )
            results = [r for _, r in results_with_authority]

        # Regular documents
        for i, result in enumerate(results, 1):
            source_info = result["source_file"]
            source_type = result.get("source_type", "document")
            if result.get("page_number"):
                source_info += f", page {result['page_number']}"

            # Add date info if available in metadata
            date_issued = result.get("metadata", {}).get("date_issued", "")
            date_str = f" (issued {date_issued})" if date_issued else ""

            context_parts.append(
                f"[Document {i}: {source_info} — {source_type}{date_str}]\n"
                f"{result['text']}\n"
            )

        return "\n---\n".join(context_parts)

    def _format_sources(
        self, results: list[dict], corrections: list[dict]
    ) -> list[dict]:
        """Format sources for citation display.

        Args:
            results: Search results from vector store
            corrections: Relevant corrections

        Returns:
            List of source dictionaries
        """
        sources = []
        seen_files = set()

        # Add correction sources
        for correction in corrections:
            sources.append({
                "file": "Team Knowledge Base",
                "type": "correction",
                "relevance": "100%",
            })
            break  # Only show once even if multiple corrections

        # Add document sources
        for result in results:
            source_file = result["source_file"]

            # Deduplicate by source file
            if source_file in seen_files:
                continue
            seen_files.add(source_file)

            source = {
                "file": source_file,
                "type": result["source_type"],
                "relevance": f"{result['score']:.0%}",
            }

            if result.get("page_number"):
                source["page"] = result["page_number"]

            sources.append(source)

        return sources


def format_citations(sources: list[dict]) -> str:
    """Format sources as a citation block for the response.

    Args:
        sources: List of source dictionaries

    Returns:
        Formatted citation string
    """
    if not sources:
        return ""

    lines = ["\n\n📚 **Sources:**"]

    for i, source in enumerate(sources, 1):
        line = f"  [{i}] {source['file']}"
        if source.get("page"):
            line += f" (p. {source['page']})"
        line += f" — {source['type'].replace('_', ' ').title()}"
        if source.get("relevance"):
            line += f" ({source['relevance']} match)"
        lines.append(line)

    return "\n".join(lines)


def build_rag_prompt(query: str, context: str) -> str:
    """Build a prompt that includes retrieved context.

    Args:
        query: User's question
        context: Retrieved document context

    Returns:
        Enhanced prompt with context
    """
    if not context:
        return query

    return f"""Based on the following reference documents, answer the user's question.

IMPORTANT RULES:
- If TEAM CORRECTIONS are present, they override any conflicting document information.
- When documents conflict, prefer the most recently dated source.
- Documents are listed in order of authority (most authoritative first).
- If the documents don't contain relevant information, use your expert knowledge but note that you're not citing a specific source.

REFERENCE DOCUMENTS:
{context}

USER QUESTION: {query}

Provide a comprehensive answer. When information comes from the reference documents, indicate which document number it's from."""
