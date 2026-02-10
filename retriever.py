"""
Retrieval module for RAG.
Handles document retrieval and context formatting with source citations.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
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
        knowledge_base_path: str = "knowledge_base.json",
    ):
        """Initialize the retriever.

        Args:
            vector_store: Vector store instance (creates one if not provided)
            settings: Application settings
            knowledge_base_path: Path to corrections/knowledge base file
        """
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStore(self.settings)
        self.knowledge_base_path = Path(knowledge_base_path)
        self.corrections = self._load_corrections()

    def _load_corrections(self) -> list[dict]:
        """Load corrections from knowledge base file.
        
        Returns:
            List of correction entries
        """
        if not self.knowledge_base_path.exists():
            return []
        
        try:
            with open(self.knowledge_base_path) as f:
                data = json.load(f)
                entries = data.get("entries", {})
                
                # Extract corrections (type == "correction")
                corrections = []
                for entry_id, entry_data in entries.items():
                    if entry_data.get("entry_type") == "correction":
                        corrections.append({
                            "question": entry_data.get("question", ""),
                            "answer": entry_data.get("answer", ""),
                            "context": entry_data.get("context", ""),
                        })
                
                logger.info(f"Loaded {len(corrections)} corrections from knowledge base")
                return corrections
        except Exception as e:
            logger.warning(f"Failed to load corrections: {e}")
            return []
    
    def _find_relevant_corrections(self, query: str) -> list[dict]:
        """Find corrections relevant to the query.
        
        Simple keyword matching for now. Could be enhanced with embeddings.
        
        Args:
            query: User's question
            
        Returns:
            List of relevant corrections
        """
        if not self.corrections:
            return []
        
        query_lower = query.lower()
        relevant = []
        
        for correction in self.corrections:
            question_lower = correction["question"].lower()
            
            # Check if query contains key terms from the correction
            question_words = set(question_lower.split())
            query_words = set(query_lower.split())
            
            # If there's significant overlap, consider it relevant
            overlap = question_words & query_words
            if len(overlap) >= 2:  # At least 2 words in common
                relevant.append(correction)
        
        return relevant
    
    def _format_corrections(self, corrections: list[dict]) -> str:
        """Format corrections as context for the LLM.
        
        Args:
            corrections: List of correction dictionaries
            
        Returns:
            Formatted corrections string
        """
        if not corrections:
            return ""
        
        parts = ["⚠️ IMPORTANT CORRECTIONS (HIGHEST PRIORITY - OVERRIDE ANY CONFLICTING INFORMATION):"]
        
        for i, correction in enumerate(corrections, 1):
            parts.append(
                f"\n**Correction {i}:**\n"
                f"**Wrong:** {correction['question']}\n"
                f"**Correct:** {correction['answer']}"
            )
            if correction.get('context'):
                parts.append(f"**Context:** {correction['context']}")
        
        return "\n".join(parts)

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
        # Check for relevant corrections FIRST
        relevant_corrections = self._find_relevant_corrections(query)
        
        # Search vector store
        results = self.vector_store.search(
            query=query,
            top_k=top_k,
            source_type_filter=source_type,
        )

        # Filter by minimum score
        filtered_results = [r for r in results if r["score"] >= min_score]

        # Build context with corrections at the top
        context_parts = []
        
        # Add corrections first (highest priority)
        if relevant_corrections:
            corrections_text = self._format_corrections(relevant_corrections)
            context_parts.append(corrections_text)
            logger.info(f"Found {len(relevant_corrections)} relevant corrections")
        
        # Add vector search results
        if filtered_results:
            docs_context = self._format_context(filtered_results)
            context_parts.append(docs_context)
        
        combined_context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        # Format sources for citation (only from vector search, not corrections)
        sources = self._format_sources(filtered_results) if filtered_results else []

        logger.info(
            f"Retrieved {len(filtered_results)} documents + {len(relevant_corrections)} corrections for query: {query[:50]}..."
        )

        return RetrievalResult(
            context=combined_context,
            sources=sources,
            query=query,
            num_results=len(filtered_results) + len(relevant_corrections),
        )

        return RetrievalResult(
            context=context,
            sources=sources,
            query=query,
            num_results=len(filtered_results),
        )

    def _format_context(self, results: list[dict]) -> str:
        """Format retrieved documents as context for the LLM.
        
        Includes confidence scores so the LLM knows which documents
        to trust vs. which are weak matches.

        Args:
            results: Search results from vector store

        Returns:
            Formatted context string with confidence indicators
        """
        context_parts = []

        for i, result in enumerate(results, 1):
            score = result["score"]
            source_info = result["source_file"]
            if result.get("page_number"):
                source_info += f", page {result['page_number']}"
            
            # Add confidence indicator
            if score >= 0.90:
                confidence = "VERY HIGH confidence"
            elif score >= 0.80:
                confidence = "HIGH confidence"
            elif score >= 0.70:
                confidence = "MODERATE confidence"
            else:
                confidence = "LOW confidence - use cautiously"

            context_parts.append(
                f"[Document {i}: {source_info} | {confidence} ({score:.0%} match)]\n{result['text']}\n"
            )

        return "\n---\n".join(context_parts)

    def _format_sources(self, results: list[dict]) -> list[dict]:
        """Format sources for citation display.
        
        Only includes high-confidence sources (>80%) to avoid
        citing irrelevant documents that happened to match weakly.

        Args:
            results: Search results from vector store

        Returns:
            List of high-confidence source dictionaries
        """
        sources = []
        seen_files = set()
        
        # Only include sources with >85% confidence for citation
        HIGH_CONFIDENCE_THRESHOLD = 0.85

        for result in results:
            source_file = result["source_file"]
            score = result["score"]
            
            # Skip low-confidence matches
            if score < HIGH_CONFIDENCE_THRESHOLD:
                continue

            # Deduplicate by source file
            if source_file in seen_files:
                continue
            seen_files.add(source_file)

            source = {
                "file": source_file,
                "type": result["source_type"],
                "relevance": f"{score:.0%}",
                "score": score,  # Include raw score for sorting
            }

            if result.get("page_number"):
                source["page"] = result["page_number"]

            sources.append(source)

        # Sort by relevance (highest first)
        sources.sort(key=lambda x: x["score"], reverse=True)
        
        # Remove raw score from output (was just for sorting)
        for source in sources:
            source.pop("score", None)

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

    lines = ["\n\nðŸ“š **Sources:**"]

    for i, source in enumerate(sources, 1):
        line = f"  [{i}] {source['file']}"
        if source.get("page"):
            line += f" (p. {source['page']})"
        line += f" â€” {source['type'].replace('_', ' ').title()}"
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
