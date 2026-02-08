"""
Retrieval module for RAG.
Handles document retrieval, context formatting with source citations,
jurisdiction detection, and correction injection from the knowledge base.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Settings, get_settings
from vector_store import VectorStore

logger = logging.getLogger(__name__)

# Document authority hierarchy: higher number = higher authority
DOC_AUTHORITY = {
    "determination": 10,
    "building_code": 9,
    "rule": 9,
    "zoning": 9,
    "technical_bulletin": 8,
    "policy_memo": 7,
    "service_notice": 6,
    "procedure": 5,
    "correction": 10,
    "checklist": 4,
    "reference": 4,
    "internal_notes": 3,
    "historical_determination": 8,
    "out_of_nyc_filing": 3,
    "document": 2,
}

# Jurisdiction detection keywords
# Add new cities here as expansion progresses
JURISDICTION_KEYWORDS = {
    "NYC": [
        "nyc", "new york city", "dob", "department of buildings",
        "bis", "dob now", "alt-1", "alt-2", "alt-3", "alt1", "alt2", "alt3",
        "manhattan", "brooklyn", "queens", "bronx", "staten island",
        "certificate of occupancy", "tco", "paa", "zrd1", "ccd1",
        "multiple dwelling", "mdl", "housing maintenance code",
        "pw1", "pw2", "pw3", "zd1", "ai1",
    ],
    "Town of Hempstead, NY": [
        "hempstead", "town of hempstead",
    ],
    "Jersey City, NJ": [
        "jersey city",
    ],
    "Tampa, FL": [
        "tampa",
    ],
    "Houston, TX": [
        "houston",
    ],
    "Philadelphia, PA": [
        "philadelphia", "philly", "eclipse",
    ],
    "Atlanta, GA": [
        "atlanta",
    ],
    "Austin, TX": [
        "austin",
    ],
}


def detect_jurisdiction(query: str) -> Optional[str]:
    """Detect jurisdiction from user's question.

    Checks for city/jurisdiction keywords in the query.
    If no specific jurisdiction is detected, returns None (search all).
    NYC-specific terms (DOB, Alt-1, etc.) auto-detect as NYC.
    """
    query_lower = query.lower()

    # Check non-NYC jurisdictions first (more specific)
    for jurisdiction, keywords in JURISDICTION_KEYWORDS.items():
        if jurisdiction == "NYC":
            continue
        for keyword in keywords:
            if keyword in query_lower:
                logger.info(f"Detected jurisdiction: {jurisdiction}")
                return jurisdiction

    # Check NYC keywords
    for keyword in JURISDICTION_KEYWORDS["NYC"]:
        if keyword in query_lower:
            logger.info(f"Detected jurisdiction: NYC")
            return "NYC"

    # No jurisdiction detected
    return None


@dataclass
class RetrievalResult:
    """Result from document retrieval."""

    context: str
    sources: list[dict]
    query: str
    num_results: int
    jurisdiction: Optional[str] = None


class Retriever:
    """Document retriever with jurisdiction filtering, corrections overlay, and authority ranking."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        settings: Optional[Settings] = None,
        knowledge_base_path: str = "knowledge_base.json",
    ):
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStore(self.settings)
        self.knowledge_base_path = Path(knowledge_base_path)

    def _load_corrections(self) -> list[dict]:
        """Load corrections from knowledge_base.json."""
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
        """Find corrections relevant to the current query."""
        corrections = self._load_corrections()
        if not corrections:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        relevant = []
        for correction in corrections:
            topics = [t.lower() for t in correction.get("topics", [])]
            question = correction.get("question", "").lower()
            answer = correction.get("answer", "").lower()

            all_correction_text = " ".join(topics + [question, answer])
            correction_words = set(all_correction_text.split())

            overlap = query_words & correction_words
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
        """Retrieve relevant documents with jurisdiction awareness.

        1. Detects jurisdiction from the query
        2. Searches Pinecone filtered to that jurisdiction
        3. If no results, falls back to unfiltered search
        4. Checks corrections database
        5. Sorts by authority hierarchy
        """
        # Detect jurisdiction from the query
        jurisdiction = detect_jurisdiction(query)

        # Search with jurisdiction filter
        results = self.vector_store.search(
            query=query,
            top_k=top_k,
            source_type_filter=source_type,
            jurisdiction_filter=jurisdiction,
        )

        # Filter by minimum score
        filtered_results = [r for r in results if r["score"] >= min_score]

        # Fallback: if jurisdiction filter returned nothing, search all
        if not filtered_results and jurisdiction:
            logger.info(
                f"No results for jurisdiction={jurisdiction}, falling back to all"
            )
            results = self.vector_store.search(
                query=query,
                top_k=top_k,
                source_type_filter=source_type,
                jurisdiction_filter=None,
            )
            filtered_results = [r for r in results if r["score"] >= min_score]

        # Check for relevant corrections
        corrections = self._find_relevant_corrections(query)

        if not filtered_results and not corrections:
            logger.info(
                f"No results above threshold {min_score} for query: {query[:50]}..."
            )
            return RetrievalResult(
                context="",
                sources=[],
                query=query,
                num_results=0,
                jurisdiction=jurisdiction,
            )

        # Format context
        context = self._format_context(filtered_results, corrections, jurisdiction)
        sources = self._format_sources(filtered_results, corrections)

        total_results = len(filtered_results) + len(corrections)
        logger.info(
            f"Retrieved {len(filtered_results)} docs + {len(corrections)} corrections "
            f"for query: {query[:50]}... (jurisdiction={jurisdiction})"
        )

        return RetrievalResult(
            context=context,
            sources=sources,
            query=query,
            num_results=total_results,
            jurisdiction=jurisdiction,
        )

    def _format_context(
        self,
        results: list[dict],
        corrections: list[dict],
        jurisdiction: Optional[str] = None,
    ) -> str:
        """Format retrieved documents and corrections as context for the LLM."""
        context_parts = []

        # Corrections first
        if corrections:
            context_parts.append(
                "\u26a0\ufe0f TEAM CORRECTIONS (these override other sources):"
            )
            for i, correction in enumerate(corrections, 1):
                context_parts.append(
                    f"[Correction {i}]\n"
                    f"Issue: {correction.get('question', '')}\n"
                    f"Correct answer: {correction.get('answer', '')}"
                )
            context_parts.append("---")

        # Sort by authority then score
        if len(results) > 1:
            results_with_authority = []
            for r in results:
                source_type = r.get("source_type", "document")
                authority = DOC_AUTHORITY.get(source_type, 2)
                results_with_authority.append((authority, r))

            results_with_authority.sort(
                key=lambda x: (x[0], x[1]["score"]), reverse=True
            )
            results = [r for _, r in results_with_authority]

        # Jurisdiction context note
        if jurisdiction:
            context_parts.append(
                f"NOTE: Results filtered to jurisdiction: {jurisdiction}"
            )

        # Documents
        for i, result in enumerate(results, 1):
            source_info = result["source_file"]
            source_type = result.get("source_type", "document")
            result_jurisdiction = result.get("jurisdiction", "")

            if result.get("page_number"):
                source_info += f", page {result['page_number']}"

            date_issued = result.get("metadata", {}).get("date_issued", "")
            date_str = f" (issued {date_issued})" if date_issued else ""
            jur_str = f" [{result_jurisdiction}]" if result_jurisdiction else ""

            context_parts.append(
                f"[Document {i}: {source_info} \u2014 {source_type}{date_str}{jur_str}]\n"
                f"{result['text']}\n"
            )

        return "\n---\n".join(context_parts)

    def _format_sources(
        self, results: list[dict], corrections: list[dict]
    ) -> list[dict]:
        """Format sources for citation display."""
        sources = []
        seen_files = set()

        for correction in corrections:
            sources.append({
                "file": "Team Knowledge Base",
                "type": "correction",
                "relevance": "100%",
            })
            break

        for result in results:
            source_file = result["source_file"]

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

            # Pass through source_url if available in metadata
            source_url = result.get("metadata", {}).get("source_url", "")
            if source_url:
                source["url"] = source_url

            sources.append(source)

        return sources


def format_citations(sources: list[dict]) -> str:
    """Format sources as a citation block for the response."""
    if not sources:
        return ""

    lines = ["\n\n\U0001f4da **Sources:**"]

    for i, source in enumerate(sources, 1):
        line = f"  [{i}] {source['file']}"
        if source.get("page"):
            line += f" (p. {source['page']})"
        line += f" \u2014 {source['type'].replace('_', ' ').title()}"
        if source.get("relevance"):
            line += f" ({source['relevance']} match)"
        lines.append(line)

    return "\n".join(lines)


def build_rag_prompt(query: str, context: str) -> str:
    """Build a prompt that includes retrieved context."""
    if not context:
        return query

    return f"""Based on the following reference documents, answer the user's question.

IMPORTANT RULES:
- If TEAM CORRECTIONS are present, they override any conflicting document information.
- When documents conflict, prefer the most recently dated source.
- Documents are listed in order of authority (most authoritative first).
- Pay attention to jurisdiction tags. Do NOT apply NYC rules to other cities or vice versa.
- If the documents don't contain relevant information, use your expert knowledge but note that you're not citing a specific source.

REFERENCE DOCUMENTS:
{context}

USER QUESTION: {query}

Provide a comprehensive answer. When information comes from the reference documents, indicate which document number it's from."""
