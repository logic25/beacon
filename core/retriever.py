"""
Retrieval module for RAG.
Handles document retrieval, context formatting with source citations,
and correction injection from the knowledge base.

Used by:
  - bot_v2.py: process_message_async() and /api/chat endpoint
  - content_engine/engine.py: topic research for content scoring
  - intelligent_scorer.py: RAG-enhanced content opportunity analysis

Source output format must include 'text', 'score', 'file', 'type', 'relevance'
because the /api/chat endpoint reads all of these fields to build the
Ordino widget's source cards (chunk_preview, confidence score, title).
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Settings, get_settings
from core.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Document authority hierarchy: higher number = higher authority
# When docs conflict, prefer higher-authority sources.
# Keys must match the source_type metadata values stored in Pinecone.
DOC_AUTHORITY = {
    "determination": 10,            # DOB rulings — highest authority
    "correction": 10,               # Team corrections — always override
    "building_code": 9,             # Code text
    "rule": 9,                      # 1 RCNY rules
    "zoning": 9,                    # Zoning Resolution
    "multiple_dwelling_law": 9,     # MDL sections
    "housing_maintenance_code": 8,  # HMC
    "technical_bulletin": 8,        # BBs and TPPNs
    "historical_determination": 8,
    "policy_memo": 7,               # DOB policy memos
    "service_notice": 6,            # DOB service notices
    "procedure": 5,                 # GLE internal procedures / guides
    "process": 5,                   # Alias for procedure (knowledge/processes/)
    "checklist": 4,
    "reference": 4,
    "communication": 3,             # Communication patterns
    "internal_notes": 3,            # Historical notes
    "historical": 3,                # Historical case files
    "out_of_nyc_filing": 3,
    "document": 2,                  # Generic / unclassified
}


@dataclass
class RetrievalResult:
    """Result from document retrieval."""

    context: str             # Formatted context string for the LLM
    sources: list[dict]      # Source dicts for citation display & Ordino widget
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
            knowledge_base_path: Path to corrections/knowledge base file
        """
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStore(self.settings)
        self.knowledge_base_path = Path(knowledge_base_path)
        self.corrections = self._load_corrections()
        self._corrections_mtime: float = self._get_kb_mtime()

    # ------------------------------------------------------------------
    # Corrections loading
    # ------------------------------------------------------------------

    def _get_kb_mtime(self) -> float:
        """Get the modification time of the knowledge base file."""
        try:
            return os.path.getmtime(self.knowledge_base_path) if self.knowledge_base_path.exists() else 0.0
        except OSError:
            return 0.0

    def _load_corrections(self) -> list[dict]:
        """Load corrections from knowledge base file.

        Returns:
            List of correction entries with question, answer, context, topics.
        """
        if not self.knowledge_base_path.exists():
            return []

        try:
            with open(self.knowledge_base_path) as f:
                data = json.load(f)

            # Handle both formats: top-level dict or nested under "entries"
            entries = data.get("entries", data) if isinstance(data, dict) else {}
            if not isinstance(entries, dict):
                return []

            corrections = []
            for _entry_id, entry_data in entries.items():
                if not isinstance(entry_data, dict):
                    continue
                if entry_data.get("entry_type") == "correction":
                    corrections.append({
                        "question": entry_data.get("question", ""),
                        "answer": entry_data.get("answer", ""),
                        "context": entry_data.get("context", ""),
                        "topics": entry_data.get("topics", []),
                    })

            logger.info(f"Loaded {len(corrections)} corrections from knowledge base")
            return corrections
        except Exception as e:
            logger.warning(f"Failed to load corrections: {e}")
            return []

    def reload_corrections(self) -> None:
        """Reload corrections if the file has changed.

        Called automatically on each retrieve() so that /correct and /tip
        additions are picked up without restarting Railway.
        """
        current_mtime = self._get_kb_mtime()
        if current_mtime != self._corrections_mtime:
            logger.info("Knowledge base file changed — reloading corrections")
            self.corrections = self._load_corrections()
            self._corrections_mtime = current_mtime

    # ------------------------------------------------------------------
    # Correction matching
    # ------------------------------------------------------------------

    def _find_relevant_corrections(self, query: str) -> list[dict]:
        """Find corrections relevant to the query.

        Uses topics-based keyword matching with meaningful word filtering.
        Words <= 3 chars are skipped to avoid false matches on "the", "and", etc.

        Args:
            query: User's question

        Returns:
            List of relevant corrections
        """
        if not self.corrections:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        relevant = []
        for correction in self.corrections:
            # Build combined text from topics, question, and answer
            topics = [t.lower() for t in correction.get("topics", [])]
            question = correction.get("question", "").lower()
            answer = correction.get("answer", "").lower()

            all_correction_text = " ".join(topics + [question, answer])
            correction_words = set(all_correction_text.split())

            # Score relevance by keyword overlap — skip tiny words
            overlap = query_words & correction_words
            meaningful_overlap = [w for w in overlap if len(w) > 3]

            if len(meaningful_overlap) >= 2:
                relevant.append(correction)

        return relevant

    # ------------------------------------------------------------------
    # Main retrieve
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
        source_type: Optional[str] = None,
        jurisdiction: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve relevant documents for a query.

        Checks both Pinecone vector store AND local corrections database.
        Corrections are injected as highest-priority context.

        Args:
            query: User's question/query
            top_k: Maximum number of documents to retrieve
            min_score: Minimum similarity score threshold
            source_type: Optional filter by document type
            jurisdiction: Optional filter by jurisdiction (e.g. "NYC")

        Returns:
            RetrievalResult with formatted context and sources
        """
        # Auto-reload corrections if file changed (picks up /correct additions)
        self.reload_corrections()

        # Check for relevant corrections FIRST
        relevant_corrections = self._find_relevant_corrections(query)

        # Search vector store. Retrieve a WIDER candidate pool than we'll use, then
        # re-rank so a recent, authoritative doc (e.g. a new DOB service notice) can
        # surface above an older general guide it supersedes. Raw vector score alone
        # let stale guides out-rank fresh notices on the same topic.
        results = self.vector_store.search(
            query=query,
            top_k=max(top_k * 3, 15),
            source_type_filter=source_type,
            jurisdiction_filter=jurisdiction,
        )
        results = self._rerank(results)[:top_k]

        # Filter by minimum score (on the raw vector score)
        filtered_results = [r for r in results if r["score"] >= min_score]

        # Build context with corrections at the top
        context_parts = []

        if relevant_corrections:
            corrections_text = self._format_corrections(relevant_corrections)
            context_parts.append(corrections_text)
            logger.info(f"Found {len(relevant_corrections)} relevant corrections")

        if filtered_results:
            docs_context = self._format_context(filtered_results)
            context_parts.append(docs_context)

        combined_context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        # Format sources for citation + Ordino widget
        sources = self._format_sources(filtered_results, relevant_corrections)

        total = len(filtered_results) + len(relevant_corrections)
        logger.info(
            f"Retrieved {len(filtered_results)} documents + "
            f"{len(relevant_corrections)} corrections for: {query[:60]}..."
        )

        return RetrievalResult(
            context=combined_context,
            sources=sources,
            query=query,
            num_results=total,
        )

    # ------------------------------------------------------------------
    # Context formatting
    # ------------------------------------------------------------------

    def _format_corrections(self, corrections: list[dict]) -> str:
        """Format corrections as context for the LLM.

        Args:
            corrections: List of correction dictionaries

        Returns:
            Formatted corrections string
        """
        if not corrections:
            return ""

        parts = [
            "⚠️ TEAM CORRECTIONS (these override any conflicting document information):"
        ]

        for i, correction in enumerate(corrections, 1):
            parts.append(
                f"\n[Correction {i}]\n"
                f"Issue: {correction['question']}\n"
                f"Correct answer: {correction['answer']}"
            )
            if correction.get("context"):
                parts.append(f"Context: {correction['context']}")

        return "\n".join(parts)

    def _rerank(self, results: list[dict]) -> list[dict]:
        """Re-rank candidates by raw score + small recency & authority boosts.

        The boosts are deliberately small (recency ≤ 0.08, authority ≤ 0.05) so they
        only change the order when relevance is CLOSE — a freshness/authority
        tiebreaker, NOT an override of genuine relevance. This lets a recent DOB
        service notice beat an older general guide on the same topic, without
        surfacing off-topic recent docs (a large relevance gap still wins).
        """
        from datetime import datetime
        now = datetime.now()
        for r in results:
            score = r.get("score", 0.0)
            auth = DOC_AUTHORITY.get(r.get("source_type", "document"), 2)
            auth_boost = min(auth, 10) / 200.0  # up to +0.05
            recency_boost = 0.0
            di = (r.get("metadata") or {}).get("date_issued", "") or r.get("date_issued", "")
            try:
                d = datetime.fromisoformat(str(di)[:10])
                days = (now - d).days
                if 0 <= days < 365:
                    recency_boost = 0.08 * (1 - days / 365.0)  # up to +0.08, very recent
            except Exception:
                pass
            r["_rerank_score"] = score + auth_boost + recency_boost
        return sorted(
            results,
            key=lambda r: r.get("_rerank_score", r.get("score", 0.0)),
            reverse=True,
        )

    def _format_context(self, results: list[dict]) -> str:
        """Format retrieved documents as context for the LLM.

        Sorts by document authority (DOC_AUTHORITY), then by similarity score.
        Includes confidence indicators and date metadata so the LLM can
        weigh sources appropriately.

        Args:
            results: Search results from vector store

        Returns:
            Formatted context string
        """
        # Sort by authority level (desc), then score (desc)
        if len(results) > 1:
            results_sorted = []
            for r in results:
                source_type = r.get("source_type", "document")
                authority = DOC_AUTHORITY.get(source_type, 2)
                results_sorted.append((authority, r))

            results_sorted.sort(
                key=lambda x: (x[0], x[1]["score"]), reverse=True
            )
            results = [r for _, r in results_sorted]

        context_parts = []

        for i, result in enumerate(results, 1):
            score = result["score"]
            source_info = result["source_file"]
            source_type = result.get("source_type", "document")

            if result.get("page_number"):
                source_info += f", page {result['page_number']}"

            # Date metadata (from ingestion, if available)
            date_issued = result.get("metadata", {}).get("date_issued", "")
            date_str = f" (issued {date_issued})" if date_issued else ""

            # Confidence indicator for the LLM
            if score >= 0.90:
                confidence = "VERY HIGH"
            elif score >= 0.80:
                confidence = "HIGH"
            elif score >= 0.70:
                confidence = "MODERATE"
            else:
                confidence = "LOW - use cautiously"

            context_parts.append(
                f"[Document {i}: {source_info} — {source_type}{date_str} | "
                f"{confidence} confidence ({score:.0%} match)]\n"
                f"{result['text']}\n"
            )

        return "\n---\n".join(context_parts)

    # ------------------------------------------------------------------
    # Source formatting (feeds Ordino widget + Google Chat citations)
    # ------------------------------------------------------------------

    def _format_sources(
        self, results: list[dict], corrections: list[dict]
    ) -> list[dict]:
        """Format sources for citation display and the Ordino BeaconChatWidget.

        IMPORTANT: The /api/chat endpoint reads these fields from each source:
          - "file" or "title"  → source card title
          - "score"            → confidence calculation
          - "text"             → chunk_preview in the widget (first 200 chars)
          - "type"             → source type label
          - "relevance"        → percentage string

        Only includes sources above the citation threshold to avoid
        citing documents that matched weakly.

        Args:
            results: Search results from vector store
            corrections: Relevant corrections

        Returns:
            List of source dictionaries
        """
        sources = []
        seen_files = set()

        CITATION_THRESHOLD = 0.65

        # Correction sources first (always shown)
        if corrections:
            sources.append({
                "file": "Team Knowledge Base",
                "type": "correction",
                "relevance": "100%",
                "score": 1.0,
                "text": corrections[0].get("answer", "")[:300],
            })

        for result in results:
            source_file = result["source_file"]
            score = result["score"]

            # Skip low-confidence matches for citations
            if score < CITATION_THRESHOLD:
                continue

            # Deduplicate by source file
            if source_file in seen_files:
                continue
            seen_files.add(source_file)

            source = {
                "file": source_file,
                "type": result.get("source_type", "document"),
                "relevance": f"{score:.0%}",
                "score": score,
                "text": result.get("text", "")[:300],
            }

            if result.get("page_number"):
                source["page"] = result["page_number"]

            sources.append(source)

        # Sort document sources by score (desc), keep corrections at top
        correction_sources = [s for s in sources if s.get("type") == "correction"]
        doc_sources = [s for s in sources if s.get("type") != "correction"]
        doc_sources.sort(key=lambda x: x.get("score", 0), reverse=True)

        return correction_sources + doc_sources


# ------------------------------------------------------------------
# Standalone helpers (used by llm_client.py and bot_v2.py)
# ------------------------------------------------------------------

def format_citations(sources: list[dict]) -> str:
    """Format sources as a citation block for the response.

    Used by the Google Chat webhook flow. The Ordino /api/chat
    endpoint uses llm_client._format_citations() instead.

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
