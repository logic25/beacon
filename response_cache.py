"""
Semantic Response Cache

Caches responses using semantic similarity - so "what's the FAR for R7?"
and "FAR in R7 district?" both hit the same cache entry.

Also tracks question frequency for analytics dashboard.
"""

import json
import logging
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional
import re

logger = logging.getLogger(__name__)

# Try to import embedding client
try:
    import voyageai
    HAS_VOYAGE = True
except ImportError:
    HAS_VOYAGE = False
    logger.warning("voyageai not installed - using keyword-based similarity")


# ============================================================================
# CONFIGURATION
# ============================================================================

CACHE_CONFIG = {
    "similarity_threshold": 0.85,  # How similar questions must be to hit cache
    "cache_ttl_hours": 24,         # How long to keep cached responses
    "max_cache_entries": 1000,     # Maximum cache size
    "track_frequency": True,       # Track question frequency for analytics
}


@dataclass
class CacheEntry:
    """A cached response."""
    question: str
    response: str
    embedding: Optional[list] = None  # Vector embedding for similarity
    keywords: list = field(default_factory=list)  # Fallback for keyword matching
    created_at: str = ""
    hit_count: int = 0
    last_hit: Optional[str] = None

    def is_expired(self, ttl_hours: int = 24) -> bool:
        """Check if cache entry has expired."""
        if not self.created_at:
            return True
        created = datetime.fromisoformat(self.created_at)
        return datetime.now() - created > timedelta(hours=ttl_hours)


@dataclass
class QuestionCluster:
    """A cluster of similar questions for analytics."""
    canonical_question: str  # Representative question
    variations: list = field(default_factory=list)  # Similar phrasings
    count: int = 0
    last_asked: Optional[str] = None
    category: str = "general"  # zoning, permits, violations, etc.


class SemanticCache:
    """
    Cache that matches semantically similar questions.

    Example:
        "what is the FAR for R7?"
        "FAR in R7 district?"
        "max floor area ratio R7"

    All match the same cached response.
    """

    def __init__(self, data_dir: str = "data/cache", voyage_api_key: Optional[str] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.cache_file = self.data_dir / "response_cache.json"
        self.analytics_file = self.data_dir / "question_analytics.json"

        self.cache: dict[str, CacheEntry] = {}
        self.clusters: dict[str, QuestionCluster] = {}

        # Initialize embedding client if available
        self.voyage_client = None
        if HAS_VOYAGE and voyage_api_key:
            self.voyage_client = voyageai.Client(api_key=voyage_api_key)

        self._load()

    def _load(self):
        """Load cache and analytics from disk."""
        if self.cache_file.exists():
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                self.cache = {
                    k: CacheEntry(**v) for k, v in data.items()
                }

        if self.analytics_file.exists():
            with open(self.analytics_file, 'r') as f:
                data = json.load(f)
                self.clusters = {
                    k: QuestionCluster(**v) for k, v in data.items()
                }

    def _save(self):
        """Save cache and analytics to disk."""
        # Save cache
        cache_data = {k: asdict(v) for k, v in self.cache.items()}
        # Remove embeddings from saved data (too large)
        for entry in cache_data.values():
            entry['embedding'] = None
        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)

        # Save analytics
        analytics_data = {k: asdict(v) for k, v in self.clusters.items()}
        with open(self.analytics_file, 'w') as f:
            json.dump(analytics_data, f, indent=2)

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords for fallback similarity matching."""
        # Normalize
        text = text.lower()

        # Remove common words
        stopwords = {'what', 'is', 'the', 'a', 'an', 'for', 'in', 'on', 'at', 'to',
                     'how', 'do', 'i', 'can', 'you', 'we', 'does', 'it', 'this', 'that'}

        # Extract words
        words = re.findall(r'\b\w+\b', text)
        keywords = [w for w in words if w not in stopwords and len(w) > 2]

        return keywords

    def _get_embedding(self, text: str) -> Optional[list]:
        """Get embedding vector for text."""
        if not self.voyage_client:
            return None

        try:
            result = self.voyage_client.embed(
                texts=[text],
                model="voyage-2",
                input_type="query"
            )
            return result.embeddings[0]
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
            return None

    def _cosine_similarity(self, vec1: list, vec2: list) -> float:
        """Calculate cosine similarity between two vectors."""
        if not vec1 or not vec2:
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _keyword_similarity(self, keywords1: list, keywords2: list) -> float:
        """Calculate Jaccard similarity between keyword sets."""
        if not keywords1 or not keywords2:
            return 0.0

        set1 = set(keywords1)
        set2 = set(keywords2)

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def _categorize_question(self, question: str) -> str:
        """Categorize question for analytics."""
        q_lower = question.lower()

        if any(w in q_lower for w in ['far', 'setback', 'height', 'bulk', 'yard', 'coverage']):
            return "zoning_bulk"
        elif any(w in q_lower for w in ['use group', 'permitted', 'allowed', 'can i build']):
            return "zoning_use"
        elif any(w in q_lower for w in ['objection', 'examiner', 'plan exam', 'audit']):
            return "objections"
        elif any(w in q_lower for w in ['permit', 'filing', 'alt 1', 'alt 2', 'alt 3', 'nb']):
            return "permits"
        elif any(w in q_lower for w in ['violation', 'ecb', 'dob violation']):
            return "violations"
        elif any(w in q_lower for w in ['co', 'tco', 'certificate', 'sign off']):
            return "certificates"
        elif any(w in q_lower for w in ['landmark', 'lpc', 'historic']):
            return "landmarks"
        else:
            return "general"

    def get(self, question: str) -> Optional[str]:
        """
        Get cached response for a question.

        Uses semantic similarity to match similar questions.

        Returns:
            Cached response or None if not found
        """
        question_keywords = self._extract_keywords(question)
        question_embedding = self._get_embedding(question)

        best_match = None
        best_score = 0.0

        for cache_key, entry in self.cache.items():
            # Skip expired entries
            if entry.is_expired(CACHE_CONFIG["cache_ttl_hours"]):
                continue

            # Try embedding similarity first (more accurate)
            if question_embedding and entry.embedding:
                score = self._cosine_similarity(question_embedding, entry.embedding)
            else:
                # Fall back to keyword similarity
                score = self._keyword_similarity(question_keywords, entry.keywords)

            if score > best_score:
                best_score = score
                best_match = entry

        # Check if match is good enough
        if best_match and best_score >= CACHE_CONFIG["similarity_threshold"]:
            # Update hit stats
            best_match.hit_count += 1
            best_match.last_hit = datetime.now().isoformat()
            self._save()

            logger.info(f"Cache HIT (score={best_score:.2f}): {question[:50]}...")
            return best_match.response

        logger.info(f"Cache MISS: {question[:50]}...")
        return None

    def set(self, question: str, response: str):
        """Cache a response for a question."""
        # Generate cache key
        cache_key = hashlib.md5(question.lower().encode()).hexdigest()[:12]

        # Create entry
        entry = CacheEntry(
            question=question,
            response=response,
            embedding=self._get_embedding(question),
            keywords=self._extract_keywords(question),
            created_at=datetime.now().isoformat(),
            hit_count=0,
        )

        self.cache[cache_key] = entry

        # Track for analytics
        self._track_question(question)

        # Prune if too large
        if len(self.cache) > CACHE_CONFIG["max_cache_entries"]:
            self._prune_cache()

        self._save()

    def _track_question(self, question: str):
        """Track question for analytics/clustering."""
        if not CACHE_CONFIG["track_frequency"]:
            return

        question_keywords = self._extract_keywords(question)
        question_embedding = self._get_embedding(question)
        category = self._categorize_question(question)

        # Find existing cluster or create new one
        best_cluster = None
        best_score = 0.0

        for cluster_key, cluster in self.clusters.items():
            # Compare to canonical question
            canonical_keywords = self._extract_keywords(cluster.canonical_question)

            if question_embedding:
                canonical_embedding = self._get_embedding(cluster.canonical_question)
                if canonical_embedding:
                    score = self._cosine_similarity(question_embedding, canonical_embedding)
                else:
                    score = self._keyword_similarity(question_keywords, canonical_keywords)
            else:
                score = self._keyword_similarity(question_keywords, canonical_keywords)

            if score > best_score:
                best_score = score
                best_cluster = cluster

        # Add to existing cluster or create new
        if best_cluster and best_score >= 0.7:
            best_cluster.count += 1
            best_cluster.last_asked = datetime.now().isoformat()
            if question not in best_cluster.variations:
                best_cluster.variations.append(question)
                # Keep only 10 variations
                best_cluster.variations = best_cluster.variations[-10:]
        else:
            # Create new cluster
            cluster_key = hashlib.md5(question.lower().encode()).hexdigest()[:12]
            self.clusters[cluster_key] = QuestionCluster(
                canonical_question=question,
                variations=[],
                count=1,
                last_asked=datetime.now().isoformat(),
                category=category,
            )

    def _prune_cache(self):
        """Remove old/unused cache entries."""
        # Sort by last hit time (oldest first)
        sorted_entries = sorted(
            self.cache.items(),
            key=lambda x: x[1].last_hit or x[1].created_at
        )

        # Remove oldest 20%
        remove_count = len(sorted_entries) // 5
        for key, _ in sorted_entries[:remove_count]:
            del self.cache[key]

        logger.info(f"Pruned {remove_count} cache entries")

    def get_top_questions(self, n: int = 20, category: Optional[str] = None) -> list[dict]:
        """
        Get most frequently asked questions.

        Args:
            n: Number of questions to return
            category: Filter by category (optional)

        Returns:
            List of {question, count, category, variations}
        """
        clusters = list(self.clusters.values())

        # Filter by category if specified
        if category:
            clusters = [c for c in clusters if c.category == category]

        # Sort by count
        clusters.sort(key=lambda x: x.count, reverse=True)

        return [
            {
                "question": c.canonical_question,
                "count": c.count,
                "category": c.category,
                "variations": c.variations[:5],
                "last_asked": c.last_asked,
            }
            for c in clusters[:n]
        ]

    def get_category_stats(self) -> dict:
        """Get question counts by category."""
        stats = {}

        for cluster in self.clusters.values():
            cat = cluster.category
            if cat not in stats:
                stats[cat] = {"count": 0, "questions": 0}
            stats[cat]["count"] += cluster.count
            stats[cat]["questions"] += 1

        return stats

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        total_entries = len(self.cache)
        total_hits = sum(e.hit_count for e in self.cache.values())

        return {
            "total_entries": total_entries,
            "total_hits": total_hits,
            "hit_rate": total_hits / total_entries if total_entries > 0 else 0,
            "categories": self.get_category_stats(),
        }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cache analytics")
    parser.add_argument("--top", "-t", type=int, default=10, help="Show top N questions")
    parser.add_argument("--category", "-c", help="Filter by category")
    parser.add_argument("--stats", "-s", action="store_true", help="Show stats")

    args = parser.parse_args()

    cache = SemanticCache()

    if args.stats:
        stats = cache.get_cache_stats()
        print("\n📊 Cache Statistics:")
        print(f"   Total entries: {stats['total_entries']}")
        print(f"   Total hits: {stats['total_hits']}")
        print(f"   Hit rate: {stats['hit_rate']:.1%}")
        print("\n   By category:")
        for cat, data in stats['categories'].items():
            print(f"     {cat}: {data['count']} questions, {data['questions']} unique")

    if args.top:
        questions = cache.get_top_questions(args.top, args.category)
        print(f"\n🔥 Top {len(questions)} Questions:")
        for i, q in enumerate(questions, 1):
            print(f"\n{i}. [{q['category']}] ({q['count']} asks)")
            print(f"   {q['question'][:80]}...")
            if q['variations']:
                print(f"   Also asked as: {q['variations'][0][:50]}...")
