"""
Retrieval module for RAG.
Handles document retrieval and context formatting with source citations.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config import Settings, get_settings
from vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result from document retrieval."""

    context: str  # Formatted context for LLM
    sources: list[dict]  # Source documents for citations
    query: str
    num_results: int


class Retriever:
    """Document retriever with source tracking."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        settings: Optional[Settings] = None,
    ):
        """Initialize the retriever.

        Args:
            vector_store: Vector store instance (creates one if not provided)
            settings: Application settings
        """
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStore(self.settings)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
        source_type: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve relevant documents for a query.

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

        if not filtered_results:
            logger.info(f"No results above threshold {min_score} for query: {query[:50]}...")
            return RetrievalResult(
                context="",
                sources=[],
                query=query,
                num_results=0,
            )

        # Format context for LLM
        context = self._format_context(filtered_results)

        # Format sources for citation
        sources = self._format_sources(filtered_results)

        logger.info(
            f"Retrieved {len(filtered_results)} documents for query: {query[:50]}..."
        )

        return RetrievalResult(
            context=context,
            sources=sources,
            query=query,
            num_results=len(filtered_results),
        )

    def _format_context(self, results: list[dict]) -> str:
        """Format retrieved documents as context for the LLM.

        Args:
            results: Search results from vector store

        Returns:
            Formatted context string
        """
        context_parts = []

        for i, result in enumerate(results, 1):
            source_info = result["source_file"]
            if result.get("page_number"):
                source_info += f", page {result['page_number']}"

            context_parts.append(
                f"[Document {i}: {source_info}]\n{result['text']}\n"
            )

        return "\n---\n".join(context_parts)

    def _format_sources(self, results: list[dict]) -> list[dict]:
        """Format sources for citation display.

        Args:
            results: Search results from vector store

        Returns:
            List of source dictionaries
        """
        sources = []
        seen_files = set()

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
If the documents don't contain relevant information, use your expert knowledge but note that you're not citing a specific source.

REFERENCE DOCUMENTS:
{context}

USER QUESTION: {query}

Provide a comprehensive answer. When information comes from the reference documents, indicate which document number it's from."""
