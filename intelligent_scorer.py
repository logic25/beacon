"""
Intelligent Content Scoring Engine
Uses Claude + RAG to analyze team questions and score content opportunities
"""

import logging
import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import anthropic
from dataclasses import dataclass

from config import get_settings
from retriever import RAGRetriever

logger = logging.getLogger(__name__)


@dataclass
class ContentOpportunity:
    """Scored content opportunity from intelligent analysis."""
    title: str
    cluster: List[str]
    demand_score: int
    expertise_score: int
    relevance_score: int
    overall_score: int
    question_count: int
    knowledge_docs: List[str]
    content_angle: str
    recommended_format: str
    reasoning: str
    priority: str
    estimated_minutes: int


class IntelligentScorer:
    """Analyzes team questions + knowledge base to score content opportunities."""
    
    SYSTEM_PROMPT = """You are a content strategy advisor for Green Light Expediting, an NYC permit expediting firm.

Your job: Analyze team questions and available knowledge to score content opportunities.

**Available Knowledge Base:**
- DOB filing guides (Alt-1, Alt-2, Alt-3, NB, PAA)
- Zoning regulations and use groups
- DHCR rent stabilization procedures
- Building code compliance
- FDNY requirements
- MDL (Multiple Dwelling Law)
- Landmarks procedures

**Your Analysis:**
For each cluster of questions, evaluate:

1. **Demand Score (0-100):** How much do clients need this?
   - 90+: Asked 10+ times, critical pain point
   - 70-89: Asked 5-9 times, common question
   - 50-69: Asked 2-4 times, occasional need
   - <50: Asked once, low priority

2. **Expertise Score (0-100):** Do we have knowledge to write authoritatively?
   - 90+: Comprehensive guide exists, we're experts
   - 70-89: Some documentation, can write confidently
   - 50-69: Basic knowledge, need research
   - <50: No docs, would need to build expertise first

3. **Relevance Score (0-100):** Does this affect GLE's client projects?
   - 90+: Core service offering, directly relevant
   - 70-89: Common project requirement
   - 50-69: Occasional project need
   - <50: Interesting but not core business

4. **Content Angle:** What specific aspect should we cover?
   - Focus on recent changes
   - Address common mistakes
   - Explain confusing requirements
   - Provide step-by-step process

5. **Format Recommendation:**
   - blog_post: Substantial topic, SEO value, evergreen
   - newsletter_mention: Timely update, 2-3 paragraphs
   - comprehensive_guide: Need to create new knowledge base doc
   - skip: Already covered or not relevant

6. **Priority:** HIGH / MEDIUM / LOW
   - HIGH: 80+ overall score, publish this week/month
   - MEDIUM: 60-79, good opportunity when we have time
   - LOW: <60, backlog or skip

**Response Format:**
Return JSON with intelligent analysis:
```json
{
  "title": "Specific, SEO-friendly title",
  "content_angle": "What makes this valuable to write about",
  "demand_score": 85,
  "expertise_score": 90,
  "relevance_score": 88,
  "recommended_format": "blog_post",
  "reasoning": "Why this scores high/low",
  "priority": "HIGH",
  "estimated_minutes": 30
}
```

**Important:**
- Be honest about expertise gaps (if no docs, say so)
- Don't recommend content on topics we don't know
- Cluster similar questions (don't create duplicate opportunities)
- Consider if we've published on this recently
- Focus on what helps clients navigate NYC regulations"""

    def __init__(self, db_path: str = "beacon_analytics.db"):
        """Initialize the intelligent scorer."""
        self.db_path = db_path
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        self.retriever = RAGRetriever()
        self._cache = {}  # Simple in-memory cache
        self._cache_ttl = timedelta(hours=1)
        
    def analyze_opportunities(
        self,
        days_back: int = 30,
        min_questions: int = 2
    ) -> List[ContentOpportunity]:
        """Analyze team questions and return scored content opportunities.
        
        Args:
            days_back: Analyze questions from last N days
            min_questions: Minimum times a topic must be asked
            
        Returns:
            List of scored content opportunities
        """
        start_time = datetime.now()
        
        try:
            # 1. Get trending questions from analytics
            questions = self._get_trending_questions(days_back, min_questions)
            logger.info(f"Found {len(questions)} question clusters to analyze")
            
            if not questions:
                return []
            
            # 2. Cluster similar questions
            clusters = self._cluster_questions(questions)
            logger.info(f"Clustered into {len(clusters)} topics")
            
            # 3. Get published content (avoid duplicates)
            published = self._get_published_content()
            
            # 4. Analyze each cluster with Claude + RAG
            opportunities = []
            for cluster_name, cluster_questions in clusters.items():
                try:
                    opportunity = self._analyze_cluster(
                        cluster_name,
                        cluster_questions,
                        published
                    )
                    if opportunity and opportunity.overall_score >= 50:
                        opportunities.append(opportunity)
                except Exception as e:
                    logger.error(f"Error analyzing cluster '{cluster_name}': {e}")
                    continue
            
            # 5. Sort by overall score
            opportunities.sort(key=lambda x: x.overall_score, reverse=True)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"Analysis complete: {len(opportunities)} opportunities found "
                f"in {elapsed:.1f}s from {len(questions)} questions"
            )
            
            return opportunities
            
        except Exception as e:
            logger.error(f"Error in analyze_opportunities: {e}")
            return []
    
    def _get_trending_questions(
        self,
        days_back: int,
        min_count: int
    ) -> List[Dict]:
        """Get trending questions from analytics DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get questions from last N days, grouped and counted
            cutoff_date = (datetime.now() - timedelta(days=days_back)).isoformat()
            
            cursor.execute("""
                SELECT 
                    question,
                    topic,
                    COUNT(*) as ask_count,
                    MAX(timestamp) as last_asked
                FROM interactions
                WHERE timestamp > ?
                  AND question NOT LIKE '/feedback%'
                  AND question NOT LIKE '/correct%'
                  AND question NOT LIKE '/help%'
                GROUP BY LOWER(question)
                HAVING COUNT(*) >= ?
                ORDER BY ask_count DESC
            """, (cutoff_date, min_count))
            
            questions = []
            for row in cursor.fetchall():
                questions.append({
                    "question": row[0],
                    "topic": row[1] or "General",
                    "count": row[2],
                    "last_asked": row[3]
                })
            
            conn.close()
            return questions
            
        except Exception as e:
            logger.error(f"Error getting trending questions: {e}")
            return []
    
    def _cluster_questions(self, questions: List[Dict]) -> Dict[str, List[Dict]]:
        """Cluster similar questions together.
        
        Simple keyword-based clustering. Could be enhanced with embeddings.
        """
        clusters = defaultdict(list)
        
        # Keywords that indicate same topic
        topic_keywords = {
            "Alt-2 Filing": ["alt-2", "alt2", "alteration type 2", "alteration-2"],
            "Alt-1 Filing": ["alt-1", "alt1", "alteration type 1"],
            "DOB Permits": ["dob permit", "dob filing", "permit process"],
            "Zoning": ["zoning", "use group", "far", "setback"],
            "DHCR": ["dhcr", "rent stabilization", "mci", "rent increase"],
            "Violations": ["violation", "ecb", "dob violation"],
            "Certificates": ["certificate of occupancy", "tco", "co"],
            "FDNY": ["fdny", "fire alarm", "sprinkler"],
            "MDL": ["mdl", "multiple dwelling", "class a", "class b"],
            "Building Code": ["building code", "egress", "means of egress"],
        }
        
        # Cluster by topic keywords
        for q in questions:
            question_lower = q["question"].lower()
            matched = False
            
            for topic, keywords in topic_keywords.items():
                if any(kw in question_lower for kw in keywords):
                    clusters[topic].append(q)
                    matched = True
                    break
            
            if not matched:
                # Use existing topic from analytics
                topic = q.get("topic", "General")
                clusters[topic].append(q)
        
        return dict(clusters)
    
    def _get_published_content(self) -> List[Dict]:
        """Get recently published content to avoid duplicates."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get content published in last 60 days
            cutoff_date = (datetime.now() - timedelta(days=60)).isoformat()
            
            cursor.execute("""
                SELECT title, created_at
                FROM content_candidates
                WHERE status = 'published'
                  AND created_at > ?
                ORDER BY created_at DESC
            """, (cutoff_date,))
            
            published = []
            for row in cursor.fetchall():
                published.append({
                    "title": row[0],
                    "published_at": row[1]
                })
            
            conn.close()
            return published
            
        except Exception as e:
            logger.error(f"Error getting published content: {e}")
            return []
    
    def _analyze_cluster(
        self,
        cluster_name: str,
        questions: List[Dict],
        published: List[Dict]
    ) -> Optional[ContentOpportunity]:
        """Analyze a question cluster with Claude + RAG."""
        
        # Check cache
        cache_key = f"{cluster_name}_{len(questions)}"
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            if datetime.now() - cached_time < self._cache_ttl:
                logger.debug(f"Cache hit for '{cluster_name}'")
                return cached_result
        
        try:
            # Query RAG for relevant knowledge
            sample_question = questions[0]["question"]
            rag_results = self.retriever.search(sample_question, top_k=5)
            
            # Build context for Claude
            total_count = sum(q["count"] for q in questions)
            question_list = "\n".join([
                f"- \"{q['question']}\" (asked {q['count']}x)"
                for q in questions[:5]  # Top 5 questions
            ])
            
            knowledge_context = ""
            knowledge_files = []
            if rag_results:
                knowledge_context = "\n\n**Available Knowledge Base:**\n"
                for i, result in enumerate(rag_results[:3], 1):
                    knowledge_files.append(result["source_file"])
                    knowledge_context += f"\n{i}. {result['source_file']} ({result['score']:.0%} match)\n"
                    knowledge_context += f"   Content: {result['content'][:200]}...\n"
            else:
                knowledge_context = "\n\n**No relevant knowledge base documents found.**\n"
            
            published_context = ""
            if published:
                published_context = "\n\n**Recently Published (last 60 days):**\n"
                for p in published[:5]:
                    published_context += f"- \"{p['title']}\"\n"
            
            # Build prompt for Claude
            prompt = f"""Analyze this content opportunity:

**Topic:** {cluster_name}

**Team Questions ({total_count} total):**
{question_list}

{knowledge_context}

{published_context}

**Your Task:**
Score this content opportunity and recommend whether/how to create content about it.

Consider:
1. How much do clients need this? (demand score)
2. Do we have expertise to write authoritatively? (expertise score)
3. Is this relevant to GLE's services? (relevance score)
4. Have we already covered this recently?
5. What specific angle would be most valuable?

Return ONLY valid JSON (no markdown, no explanation):"""

            # Call Claude with Sonnet 4.5 for intelligence
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1000,
                temperature=0.3,  # Some creativity but mostly consistent
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse response
            response_text = response.content[0].text.strip()
            
            # Remove markdown if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            
            analysis = json.loads(response_text)
            
            # Calculate overall score (weighted average)
            overall_score = int(
                analysis["demand_score"] * 0.4 +
                analysis["expertise_score"] * 0.3 +
                analysis["relevance_score"] * 0.3
            )
            
            # Create opportunity
            opportunity = ContentOpportunity(
                title=analysis["title"],
                cluster=[q["question"] for q in questions[:10]],
                demand_score=analysis["demand_score"],
                expertise_score=analysis["expertise_score"],
                relevance_score=analysis["relevance_score"],
                overall_score=overall_score,
                question_count=total_count,
                knowledge_docs=list(set(knowledge_files)),
                content_angle=analysis["content_angle"],
                recommended_format=analysis["recommended_format"],
                reasoning=analysis["reasoning"],
                priority=analysis["priority"],
                estimated_minutes=analysis.get("estimated_minutes", 60)
            )
            
            # Cache result
            self._cache[cache_key] = (datetime.now(), opportunity)
            
            logger.info(
                f"Analyzed '{cluster_name}': "
                f"score={overall_score}, format={opportunity.recommended_format}"
            )
            
            return opportunity
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response for '{cluster_name}': {e}")
            logger.error(f"Response was: {response_text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Error analyzing cluster '{cluster_name}': {e}")
            return None
