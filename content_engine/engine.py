"""
Beacon Content Intelligence Engine

Main orchestrator for analyzing questions, emails, and newsletters
to generate content opportunities and drafts.

Uses Supabase (via edge function) for persistence, with SQLite fallback.
"""

import json
import sqlite3
import logging
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

from core.llm_client import ClaudeClient
from core.retriever import Retriever
from .parser import DOBNewsletterParser

logger = logging.getLogger(__name__)


@dataclass
class ContentCandidate:
    """Content recommendation"""
    id: str
    title: str
    content_type: str  # "blog_post", "newsletter", "case_study", "guide"
    priority: str  # "high", "medium", "low", "needs_review"

    relevance_score: int
    demand_score: Optional[int] = None
    expertise_score: Optional[int] = None
    search_interest: str = "unknown"
    affects_services: List[str] = None
    key_topics: List[str] = None
    reasoning: str = ""
    review_question: Optional[str] = None
    content_angle: Optional[str] = None

    team_questions_count: int = 0
    team_questions: List[str] = None
    most_common_angle: Optional[str] = None

    source_type: str = "question_cluster"  # question_cluster, email, newsletter, manual
    source_url: Optional[str] = None
    source_email_id: Optional[str] = None
    content_preview: Optional[str] = None
    recommended_format: Optional[str] = None
    estimated_minutes: Optional[int] = None

    status: str = "pending"  # pending, drafted, review, approved, published, skipped
    created_at: str = ""


class ContentEngine:
    """Main content intelligence engine.

    Tries Supabase first for all persistence, falls back to SQLite.
    """

    def __init__(self, db_path: str = "beacon_content.db"):
        self.db_path = db_path
        self.claude = ClaudeClient()
        self.retriever = Retriever()
        self.parser = DOBNewsletterParser()
        self._analytics_db = None
        self._init_sqlite_fallback()

    @property
    def analytics_db(self):
        """Lazy-load the Supabase analytics backend."""
        if self._analytics_db is None:
            try:
                from analytics.analytics_supabase import SupabaseAnalytics
                self._analytics_db = SupabaseAnalytics()
                logger.info("Content engine using Supabase backend")
            except Exception as e:
                logger.warning(f"Supabase not available, using SQLite: {e}")
        return self._analytics_db

    @property
    def use_supabase(self) -> bool:
        return self.analytics_db is not None

    def _init_sqlite_fallback(self):
        """Initialize SQLite as fallback (for local dev or when Supabase is down)."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS content_candidates (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    content_type TEXT,
                    priority TEXT,
                    relevance_score INTEGER,
                    demand_score INTEGER,
                    expertise_score INTEGER,
                    search_interest TEXT,
                    affects_services TEXT,
                    key_topics TEXT,
                    reasoning TEXT,
                    review_question TEXT,
                    content_angle TEXT,
                    team_questions_count INTEGER,
                    team_questions TEXT,
                    most_common_angle TEXT,
                    source_type TEXT DEFAULT 'question_cluster',
                    source_url TEXT,
                    source_email_id TEXT,
                    content_preview TEXT,
                    recommended_format TEXT,
                    estimated_minutes INTEGER,
                    status TEXT,
                    created_at TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS generated_content (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT,
                    content_type TEXT,
                    title TEXT,
                    content TEXT,
                    word_count INTEGER,
                    status TEXT DEFAULT 'draft',
                    generated_at TEXT,
                    approved_by TEXT,
                    approved_at TEXT,
                    published_at TEXT,
                    published_url TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"SQLite init failed: {e}")

    # ------------------------------------------------------------------
    # Analyze & Create Candidates
    # ------------------------------------------------------------------

    def analyze_update(self, title: str, summary: str, source_url: str,
                       source_type: str = "newsletter") -> ContentCandidate:
        """Analyze a DOB update / email / topic and create a content recommendation."""
        team_context = self._check_team_questions(title, summary)
        analysis = self._analyze_with_claude(title, summary, team_context)

        candidate = ContentCandidate(
            id=f"cand_{uuid.uuid4().hex[:12]}",
            title=analysis.get("title", title),
            content_type=analysis.get("content_type", "uncertain"),
            priority=analysis.get("priority", "medium"),
            relevance_score=analysis.get("relevance_score", 50),
            demand_score=analysis.get("demand_score"),
            expertise_score=analysis.get("expertise_score"),
            search_interest=analysis.get("search_interest", "unknown"),
            affects_services=analysis.get("affects_services", []),
            key_topics=analysis.get("key_topics", []),
            reasoning=analysis.get("reasoning", ""),
            review_question=analysis.get("review_question"),
            content_angle=analysis.get("content_angle"),
            team_questions_count=team_context.get("count", 0),
            team_questions=team_context.get("questions", []),
            most_common_angle=team_context.get("angle"),
            source_type=source_type,
            source_url=source_url,
            content_preview=summary[:500],
            recommended_format=analysis.get("recommended_format"),
            estimated_minutes=analysis.get("estimated_minutes"),
            status="pending",
            created_at=datetime.now().isoformat()
        )

        self._save_candidate(candidate)
        return candidate

    def analyze_email_thread(self, subject: str, body: str,
                              sender: str = "", email_id: str = None) -> ContentCandidate:
        """Analyze an email thread for content opportunities.

        Long-form client emails often contain real-world scenarios,
        specific questions, and expert explanations that make great
        case studies or guides.
        """
        # Summarize the email for analysis
        summary = self._summarize_email(subject, body, sender)

        candidate = self.analyze_update(
            title=subject,
            summary=summary,
            source_url=f"email:{email_id}" if email_id else "email",
            source_type="email",
        )

        if email_id:
            candidate.source_email_id = email_id
            # Update the saved candidate with email_id
            if self.use_supabase:
                self.analytics_db.update_content_candidate(
                    candidate.id, source_email_id=email_id
                )

        return candidate

    def _summarize_email(self, subject: str, body: str, sender: str) -> str:
        """Use Claude to extract the content-worthy substance from an email."""
        from core.llm_client import Message

        prompt = f"""Extract the key information from this email that could be turned into content for Green Light Expediting's blog or newsletter.

From: {sender}
Subject: {subject}

{body[:3000]}

Summarize in 2-3 paragraphs:
1. What's the core topic/question/scenario?
2. What expert knowledge or process is discussed?
3. Why would GLE's clients find this valuable?"""

        msg = Message(role="user", content=prompt)
        response_text, _, _ = self.claude.get_response(
            user_message=prompt,
            conversation_history=[msg]
        )
        return response_text

    # ------------------------------------------------------------------
    # Generate Content
    # ------------------------------------------------------------------

    def generate_blog_post(self, candidate_id: str) -> str:
        """Generate a blog post draft for a candidate."""
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Get context from Beacon's knowledge base
        retrieval_result = self.retriever.retrieve(candidate.title, top_k=3)
        context = retrieval_result.context

        prompt = f"""Write a blog post for Green Light Expediting.

Title: {candidate.title}

Context from our knowledge base:
{context}

Team has been asking about this {candidate.team_questions_count} times.
{f"Most common concern: {candidate.most_common_angle}" if candidate.most_common_angle else ""}
{f"Content angle: {candidate.content_angle}" if candidate.content_angle else ""}

Sample questions they asked:
{chr(10).join(f"- {q}" for q in (candidate.team_questions or [])[:5])}

{f"Source: {candidate.source_type}" if candidate.source_type != "question_cluster" else ""}
{f"Preview: {candidate.content_preview[:500]}" if candidate.content_preview else ""}

Write 1200-1500 words:
- Open with: "We've been getting questions about..."
- Address the main concern: {candidate.most_common_angle or candidate.content_angle or "this topic"}
- Include FAQ section with their actual questions
- SEO keyword: {candidate.key_topics[0] if candidate.key_topics else candidate.title}
- Actionable, expert but approachable tone
- End with a CTA mentioning GLE's services

Format: Markdown with # headers"""

        from core.llm_client import Message
        prompt_msg = Message(role="user", content=prompt)

        content, _, _ = self.claude.get_response(
            user_message=prompt,
            conversation_history=[prompt_msg]
        )

        # Save the generated draft
        gen_id = f"gen_{uuid.uuid4().hex[:12]}"
        self._save_generated(gen_id, candidate_id, "blog_post", candidate.title, content)

        return content

    def generate_newsletter(self, candidate_id: str) -> str:
        """Generate a newsletter section for a candidate."""
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

        prompt = f"""Write a brief newsletter section for Green Light Expediting about: {candidate.title}

{candidate.content_preview or candidate.reasoning}

300-400 words, format:
- What changed / what's happening
- Why it matters for NYC building owners and developers
- What to do next

Tone: Direct, actionable, expert"""

        from core.llm_client import Message
        prompt_msg = Message(role="user", content=prompt)

        content, _, _ = self.claude.get_response(
            user_message=prompt,
            conversation_history=[prompt_msg]
        )

        gen_id = f"gen_{uuid.uuid4().hex[:12]}"
        self._save_generated(gen_id, candidate_id, "newsletter", candidate.title, content)

        return content

    # ------------------------------------------------------------------
    # Draft Lifecycle: draft → review → approved → published
    # ------------------------------------------------------------------

    def submit_for_review(self, content_id: str) -> dict:
        """Move a draft to review status."""
        if self.use_supabase:
            return self.analytics_db._call("save_generated_content", {
                "id": content_id, "status": "review"
            }) or {}
        return {}

    def approve_draft(self, content_id: str, approved_by: str) -> dict:
        """Approve a reviewed draft."""
        if self.use_supabase:
            return self.analytics_db._call("save_generated_content", {
                "id": content_id,
                "status": "approved",
                "approved_by": approved_by,
                "approved_at": datetime.now().isoformat(),
            }) or {}
        return {}

    def publish_content(self, content_id: str, published_url: str = None) -> dict:
        """Mark content as published."""
        if self.use_supabase:
            return self.analytics_db._call("save_generated_content", {
                "id": content_id,
                "status": "published",
                "published_at": datetime.now().isoformat(),
                "published_url": published_url,
            }) or {}
        return {}

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_pending_candidates(self, priority: str = None) -> List[ContentCandidate]:
        """Get pending content candidates."""
        if self.use_supabase:
            rows = self.analytics_db.get_content_candidates(
                status="pending",
                content_type=None,
            )
            return [self._dict_to_candidate(r) for r in rows]
        return self._get_candidates_sqlite(priority)

    def get_all_candidates(self, status: str = "all") -> List[ContentCandidate]:
        """Get all content candidates, optionally filtered by status."""
        if self.use_supabase:
            rows = self.analytics_db.get_content_candidates(status=status)
            return [self._dict_to_candidate(r) for r in rows]
        return self._get_candidates_sqlite(status=status)

    def get_drafts(self, status: str = "draft") -> list[dict]:
        """Get generated content drafts."""
        if self.use_supabase:
            return self.analytics_db.get_generated_content(status=status)
        return []

    def get_document_references(self, days: int = 30) -> list[dict]:
        """Get which knowledge base documents are cited most in Beacon's answers."""
        if self.use_supabase:
            return self.analytics_db.get_document_references(days=days)
        return []

    def get_content_stats(self) -> dict:
        """Get content pipeline statistics."""
        if self.use_supabase:
            return self.analytics_db.get_content_stats()
        return {"total_candidates": 0, "candidates_by_status": {}, "total_drafts": 0}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_team_questions(self, title: str, summary: str, days: int = 60) -> Dict:
        """Check if team has been asking about this topic."""
        text = f"{title} {summary}".lower()
        keywords = [w for w in text.split() if len(w) > 4][:5]
        if not keywords:
            return {"count": 0}

        # Try Supabase first
        try:
            results = self._query_team_questions_supabase(keywords, days)
        except Exception:
            results = None

        if results is None:
            try:
                results = self._query_team_questions_sqlite(keywords, days)
            except Exception as e:
                logger.warning(f"Error checking questions: {e}")
                return {"count": 0}

        if not results:
            return {"count": 0}

        questions = [r[0] for r in results]
        users = list(set([r[1] for r in results]))

        # Get angle with Claude
        if len(questions) > 0:
            from core.llm_client import Message
            angle_prompt = f"What's the main concern in these questions: {', '.join(questions[:3])}? One sentence."
            angle_msg = Message(role="user", content=angle_prompt)
            response_text, _, _ = self.claude.get_response(
                user_message=angle_prompt,
                conversation_history=[angle_msg]
            )
            angle = response_text
        else:
            angle = None

        return {
            "count": len(questions),
            "questions": questions[:5],
            "users": users,
            "angle": angle
        }

    def _query_team_questions_supabase(self, keywords: List[str], days: int) -> Optional[List]:
        """Query team questions via Supabase edge function."""
        import requests as req
        supabase_url = os.getenv("SUPABASE_URL", "")
        analytics_key = os.getenv("BEACON_ANALYTICS_KEY", "")
        if not supabase_url or not analytics_key:
            return None

        try:
            resp = req.post(
                f"{supabase_url.rstrip('/')}/functions/v1/beacon-analytics",
                json={"action": "get_recent_conversations", "data": {"limit": 50}},
                headers={
                    "Content-Type": "application/json",
                    "x-beacon-key": analytics_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            conversations = result if isinstance(result, list) else result.get("conversations", [])

            results = []
            for conv in conversations:
                q = conv.get("question", "").lower()
                if any(kw in q for kw in keywords):
                    results.append((conv.get("question", ""), conv.get("user_name", "")))

            return results[:10] if results else None
        except Exception:
            return None

    def _query_team_questions_sqlite(self, keywords: List[str], days: int) -> Optional[List]:
        """Query team questions from SQLite (fallback)."""
        try:
            conn = sqlite3.connect("beacon_analytics.db")
            c = conn.cursor()
            where_clauses = " OR ".join([f"LOWER(question) LIKE '%{kw}%'" for kw in keywords])
            c.execute(f"""
                SELECT question, user_name
                FROM interactions
                WHERE ({where_clauses})
                AND timestamp > datetime('now', '-{days} days')
                LIMIT 10
            """)
            results = c.fetchall()
            conn.close()
            return results
        except Exception:
            return None

    def _analyze_with_claude(self, title: str, summary: str, team_context: Dict) -> Dict:
        """Get AI analysis of a content opportunity."""
        prompt = f"""Analyze this content opportunity for Green Light Expediting.

Title: {title}
Summary: {summary}

Team asked {team_context.get('count', 0)} questions about this in last 60 days.
{f"Most common concern: {team_context.get('angle')}" if team_context.get('angle') else ""}

GLE Services: ALT1/ALT2/ALT3 filings, Certificate of Occupancy, FISP, zoning, permits, DHCR, violations

Respond JSON:
{{
  "title": "Better title for content",
  "content_type": "blog_post" | "newsletter" | "case_study" | "guide",
  "priority": "high" | "medium" | "low" | "needs_review",
  "relevance_score": 0-100 (add +20 if team asked 3+ times),
  "demand_score": 0-100,
  "expertise_score": 0-100,
  "search_interest": "high" | "medium" | "low",
  "affects_services": ["ALT2", etc],
  "key_topics": ["sidewalk shed", etc],
  "reasoning": "why this matters",
  "content_angle": "specific angle to cover",
  "review_question": "question if uncertain",
  "recommended_format": "blog_post" | "newsletter_mention" | "comprehensive_guide" | "case_study",
  "estimated_minutes": 30
}}"""

        from core.llm_client import Message
        user_msg = Message(role="user", content=prompt)

        response, _, _ = self.claude.get_response(
            user_message=prompt,
            conversation_history=[user_msg]
        )

        try:
            response = response.replace("```json", "").replace("```", "").strip()
            return json.loads(response)
        except Exception:
            return {
                "title": title,
                "content_type": "uncertain",
                "priority": "needs_review",
                "relevance_score": 50,
                "reasoning": "Failed to parse analysis",
                "affects_services": [],
                "key_topics": []
            }

    def _save_candidate(self, c: ContentCandidate):
        """Save candidate to Supabase (preferred) or SQLite (fallback)."""
        candidate_dict = {
            "id": c.id,
            "title": c.title,
            "content_type": c.content_type,
            "priority": c.priority,
            "status": c.status,
            "relevance_score": c.relevance_score,
            "demand_score": c.demand_score,
            "expertise_score": c.expertise_score,
            "search_interest": c.search_interest,
            "affects_services": c.affects_services or [],
            "key_topics": c.key_topics or [],
            "reasoning": c.reasoning,
            "review_question": c.review_question,
            "content_angle": c.content_angle,
            "team_questions_count": c.team_questions_count,
            "team_questions": c.team_questions or [],
            "most_common_angle": c.most_common_angle,
            "source_type": c.source_type,
            "source_url": c.source_url,
            "source_email_id": c.source_email_id,
            "content_preview": c.content_preview,
            "recommended_format": c.recommended_format,
            "estimated_minutes": c.estimated_minutes,
            "created_at": c.created_at,
        }

        if self.use_supabase:
            try:
                self.analytics_db.save_content_candidate(candidate_dict)
                return
            except Exception as e:
                logger.warning(f"Supabase save failed, falling back to SQLite: {e}")

        # SQLite fallback
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO content_candidates
            (id, title, content_type, priority, relevance_score, demand_score,
             expertise_score, search_interest, affects_services, key_topics,
             reasoning, review_question, content_angle, team_questions_count,
             team_questions, most_common_angle, source_type, source_url,
             source_email_id, content_preview, recommended_format,
             estimated_minutes, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            c.id, c.title, c.content_type, c.priority, c.relevance_score,
            c.demand_score, c.expertise_score, c.search_interest,
            json.dumps(c.affects_services or []), json.dumps(c.key_topics or []),
            c.reasoning, c.review_question, c.content_angle,
            c.team_questions_count, json.dumps(c.team_questions or []),
            c.most_common_angle, c.source_type, c.source_url,
            c.source_email_id, c.content_preview, c.recommended_format,
            c.estimated_minutes, c.status, c.created_at
        ))
        conn.commit()
        conn.close()

    def _save_generated(self, gen_id: str, candidate_id: str,
                         content_type: str, title: str, content: str):
        """Save generated content to Supabase or SQLite."""
        data = {
            "id": gen_id,
            "candidate_id": candidate_id,
            "content_type": content_type,
            "title": title,
            "content": content,
            "word_count": len(content.split()),
            "status": "draft",
            "generated_at": datetime.now().isoformat(),
        }

        if self.use_supabase:
            try:
                self.analytics_db.save_generated_content(data)
                return
            except Exception as e:
                logger.warning(f"Supabase save failed, falling back to SQLite: {e}")

        # SQLite fallback
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO generated_content
            (id, candidate_id, content_type, title, content, word_count, status, generated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (gen_id, candidate_id, content_type, title, content,
              len(content.split()), "draft", datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def _get_candidate(self, candidate_id: str) -> Optional[ContentCandidate]:
        """Get a single candidate by ID."""
        if self.use_supabase:
            candidates = self.analytics_db.get_content_candidates(status="all")
            for c in candidates:
                if c.get("id") == candidate_id:
                    return self._dict_to_candidate(c)

        # SQLite fallback
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM content_candidates WHERE id = ?", (candidate_id,))
            row = c.fetchone()
            conn.close()
            if row:
                return self._row_to_candidate(row)
        except Exception:
            pass
        return None

    def _get_candidates_sqlite(self, priority: str = None,
                                status: str = None) -> List[ContentCandidate]:
        """Get candidates from SQLite (fallback)."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            query = "SELECT * FROM content_candidates WHERE 1=1"
            if status and status != "all":
                query += f" AND status = '{status}'"
            elif not status:
                query += " AND status = 'pending'"
            if priority:
                query += f" AND priority = '{priority}'"
            query += " ORDER BY relevance_score DESC"

            c.execute(query)
            rows = c.fetchall()
            conn.close()
            return [self._row_to_candidate(row) for row in rows]
        except Exception as e:
            logger.error(f"SQLite query failed: {e}")
            return []

    def _dict_to_candidate(self, d: dict) -> ContentCandidate:
        """Convert a Supabase row dict to ContentCandidate."""
        return ContentCandidate(
            id=d.get("id", ""),
            title=d.get("title", ""),
            content_type=d.get("content_type", "blog_post"),
            priority=d.get("priority", "medium"),
            relevance_score=d.get("relevance_score", 50),
            demand_score=d.get("demand_score"),
            expertise_score=d.get("expertise_score"),
            search_interest=d.get("search_interest", "unknown"),
            affects_services=d.get("affects_services", []),
            key_topics=d.get("key_topics", []),
            reasoning=d.get("reasoning", ""),
            review_question=d.get("review_question"),
            content_angle=d.get("content_angle"),
            team_questions_count=d.get("team_questions_count", 0),
            team_questions=d.get("team_questions", []),
            most_common_angle=d.get("most_common_angle"),
            source_type=d.get("source_type", "question_cluster"),
            source_url=d.get("source_url"),
            source_email_id=d.get("source_email_id"),
            content_preview=d.get("content_preview"),
            recommended_format=d.get("recommended_format"),
            estimated_minutes=d.get("estimated_minutes"),
            status=d.get("status", "pending"),
            created_at=d.get("created_at", ""),
        )

    def _row_to_candidate(self, row: tuple) -> ContentCandidate:
        """Convert a SQLite row to ContentCandidate."""
        def _parse_json(val, default=None):
            if default is None:
                default = []
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return default
            return val if val else default

        return ContentCandidate(
            id=row[0], title=row[1], content_type=row[2], priority=row[3],
            relevance_score=row[4],
            demand_score=row[5] if len(row) > 5 else None,
            expertise_score=row[6] if len(row) > 6 else None,
            search_interest=row[7] if len(row) > 7 else "unknown",
            affects_services=_parse_json(row[8] if len(row) > 8 else "[]"),
            key_topics=_parse_json(row[9] if len(row) > 9 else "[]"),
            reasoning=row[10] if len(row) > 10 else "",
            review_question=row[11] if len(row) > 11 else None,
            content_angle=row[12] if len(row) > 12 else None,
            team_questions_count=row[13] if len(row) > 13 else 0,
            team_questions=_parse_json(row[14] if len(row) > 14 else "[]"),
            most_common_angle=row[15] if len(row) > 15 else None,
            source_type=row[16] if len(row) > 16 else "question_cluster",
            source_url=row[17] if len(row) > 17 else None,
            source_email_id=row[18] if len(row) > 18 else None,
            content_preview=row[19] if len(row) > 19 else None,
            recommended_format=row[20] if len(row) > 20 else None,
            estimated_minutes=row[21] if len(row) > 21 else None,
            status=row[22] if len(row) > 22 else "pending",
            created_at=row[23] if len(row) > 23 else "",
        )
