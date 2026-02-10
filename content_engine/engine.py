"""
Beacon Content Intelligence Engine

Main orchestrator for analyzing DOB newsletters and generating content.
"""

import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import uuid

from llm_client import ClaudeClient
from retriever import Retriever
from .parser import DOBNewsletterParser


@dataclass
class ContentCandidate:
    """Content recommendation"""
    id: str
    title: str
    content_type: str  # "blog_post", "newsletter", "uncertain"
    priority: str  # "high", "medium", "low", "needs_review"
    
    relevance_score: int
    search_interest: str
    affects_services: List[str]
    key_topics: List[str]
    reasoning: str
    review_question: Optional[str]
    
    team_questions_count: int
    team_questions: List[str]
    most_common_angle: Optional[str]
    
    source_url: str
    content_preview: str
    
    status: str  # "pending", "published", "skipped"
    created_at: str


class ContentEngine:
    """Main content intelligence engine"""
    
    def __init__(self, db_path: str = "beacon_content.db"):
        self.db_path = db_path
        self.claude = ClaudeClient()
        self.retriever = Retriever()
        self.parser = DOBNewsletterParser()
        self._init_db()
    
    def _init_db(self):
        """Initialize database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS content_candidates (
                id TEXT PRIMARY KEY,
                title TEXT,
                content_type TEXT,
                priority TEXT,
                relevance_score INTEGER,
                search_interest TEXT,
                affects_services TEXT,
                key_topics TEXT,
                reasoning TEXT,
                review_question TEXT,
                team_questions_count INTEGER,
                team_questions TEXT,
                most_common_angle TEXT,
                source_url TEXT,
                content_preview TEXT,
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
                generated_at TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def analyze_update(self, title: str, summary: str, source_url: str) -> ContentCandidate:
        """Analyze a DOB update and create recommendation"""
        
        # Check team questions
        team_context = self._check_team_questions(title, summary)
        
        # Analyze with Claude
        analysis = self._analyze_with_claude(title, summary, team_context)
        
        # Create candidate
        candidate = ContentCandidate(
            id=f"cand_{uuid.uuid4().hex[:12]}",
            title=analysis.get("title", title),
            content_type=analysis.get("content_type", "uncertain"),
            priority=analysis.get("priority", "medium"),
            relevance_score=analysis.get("relevance_score", 50),
            search_interest=analysis.get("search_interest", "unknown"),
            affects_services=analysis.get("affects_services", []),
            key_topics=analysis.get("key_topics", []),
            reasoning=analysis.get("reasoning", ""),
            review_question=analysis.get("review_question"),
            team_questions_count=team_context.get("count", 0),
            team_questions=team_context.get("questions", []),
            most_common_angle=team_context.get("angle"),
            source_url=source_url,
            content_preview=summary[:500],
            status="pending",
            created_at=datetime.now().isoformat()
        )
        
        # Save to DB
        self._save_candidate(candidate)
        
        return candidate
    
    def _check_team_questions(self, title: str, summary: str, days: int = 60) -> Dict:
        """Check if team has been asking about this topic"""
        
        # Extract keywords
        text = f"{title} {summary}".lower()
        keywords = [w for w in text.split() if len(w) > 4][:5]
        
        if not keywords:
            return {"count": 0}
        
        try:
            # Query analytics
            conn = sqlite3.connect("beacon_analytics.db")
            c = conn.cursor()
            
            where_clauses = " OR ".join([f"LOWER(question) LIKE '%{kw}%'" for kw in keywords])
            
            c.execute(f"""
                SELECT question, user_name 
                FROM analytics 
                WHERE ({where_clauses})
                AND timestamp > datetime('now', '-{days} days')
                LIMIT 10
            """)
            
            results = c.fetchall()
            conn.close()
            
            if not results:
                return {"count": 0}
            
            questions = [r[0] for r in results]
            users = list(set([r[1] for r in results]))
            
            # Get angle with Claude
            if len(questions) > 0:
                angle_prompt = f"What's the main concern in these questions: {', '.join(questions[:3])}? One sentence."
                angle = self.claude.get_response(angle_prompt, [])
            else:
                angle = None
            
            return {
                "count": len(questions),
                "questions": questions[:5],
                "users": users,
                "angle": angle
            }
            
        except Exception as e:
            print(f"Error checking questions: {e}")
            return {"count": 0}
    
    def _analyze_with_claude(self, title: str, summary: str, team_context: Dict) -> Dict:
        """Get AI analysis"""
        
        prompt = f"""Analyze this DOB update for Green Light Expediting.

Title: {title}
Summary: {summary}

Team asked {team_context.get('count', 0)} questions about this in last 60 days.
{f"Most common concern: {team_context.get('angle')}" if team_context.get('angle') else ""}

GLE Services: ALT1/ALT2/ALT3 filings, Certificate of Occupancy, FISP, zoning, permits

Respond JSON:
{{
  "title": "Better title for content",
  "content_type": "blog_post" | "newsletter" | "uncertain",
  "priority": "high" | "medium" | "low" | "needs_review",
  "relevance_score": 0-100 (add +20 if team asked 3+ times),
  "search_interest": "high" | "medium" | "low",
  "affects_services": ["ALT2", etc],
  "key_topics": ["sidewalk shed", etc],
  "reasoning": "why this matters",
  "review_question": "question if uncertain"
}}"""
        
        response = self.claude.get_response(prompt, [])
        
        # Parse JSON
        try:
            response = response.replace("```json", "").replace("```", "").strip()
            return json.loads(response)
        except:
            return {
                "title": title,
                "content_type": "uncertain",
                "priority": "needs_review",
                "relevance_score": 50,
                "reasoning": "Failed to parse",
                "affects_services": [],
                "key_topics": []
            }
    
    def _save_candidate(self, c: ContentCandidate):
        """Save to database"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO content_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            c.id, c.title, c.content_type, c.priority, c.relevance_score,
            c.search_interest, json.dumps(c.affects_services), json.dumps(c.key_topics),
            c.reasoning, c.review_question, c.team_questions_count,
            json.dumps(c.team_questions), c.most_common_angle,
            c.source_url, c.content_preview, c.status, c.created_at
        ))
        
        conn.commit()
        conn.close()
    
    def get_pending_candidates(self, priority: Optional[str] = None) -> List[ContentCandidate]:
        """Get pending candidates"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        query = "SELECT * FROM content_candidates WHERE status = 'pending'"
        if priority:
            query += f" AND priority = '{priority}'"
        query += " ORDER BY relevance_score DESC"
        
        c.execute(query)
        rows = c.fetchall()
        conn.close()
        
        candidates = []
        for row in rows:
            candidates.append(ContentCandidate(
                id=row[0], title=row[1], content_type=row[2], priority=row[3],
                relevance_score=row[4], search_interest=row[5],
                affects_services=json.loads(row[6]), key_topics=json.loads(row[7]),
                reasoning=row[8], review_question=row[9], team_questions_count=row[10],
                team_questions=json.loads(row[11]), most_common_angle=row[12],
                source_url=row[13], content_preview=row[14], status=row[15],
                created_at=row[16]
            ))
        
        return candidates
    
    def generate_blog_post(self, candidate_id: str) -> str:
        """Generate blog post for candidate"""
        
        # Get candidate
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM content_candidates WHERE id = ?", (candidate_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            raise ValueError(f"Candidate {candidate_id} not found")
        
        candidate = ContentCandidate(
            id=row[0], title=row[1], content_type=row[2], priority=row[3],
            relevance_score=row[4], search_interest=row[5],
            affects_services=json.loads(row[6]), key_topics=json.loads(row[7]),
            reasoning=row[8], review_question=row[9], team_questions_count=row[10],
            team_questions=json.loads(row[11]), most_common_angle=row[12],
            source_url=row[13], content_preview=row[14], status=row[15],
            created_at=row[16]
        )
        
        # Get context from Beacon
        context_docs = self.retriever.retrieve(candidate.title, top_k=3)
        context = "\n\n".join([doc.get("content", "")[:500] for doc in context_docs])
        
        # Build prompt
        prompt = f"""Write a blog post for Green Light Expediting.

Title: {candidate.title}

Context from our knowledge base:
{context}

Team has been asking about this {candidate.team_questions_count} times.
{f"Most common concern: {candidate.most_common_angle}" if candidate.most_common_angle else ""}

Sample questions they asked:
{chr(10).join(f"- {q}" for q in candidate.team_questions[:3])}

Write 1200-1500 words:
- Open with: "We've been getting questions about..."
- Address the main concern: {candidate.most_common_angle}
- Include FAQ section with their actual questions
- SEO keyword: {candidate.key_topics[0] if candidate.key_topics else candidate.title}
- Actionable, expert but approachable tone

Format: Markdown with # headers"""

        content = self.claude.get_response(prompt, [])
        
        # Save generated content
        gen_id = f"gen_{uuid.uuid4().hex[:12]}"
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO generated_content VALUES (?,?,?,?,?,?,?)
        """, (gen_id, candidate_id, "blog_post", candidate.title, content, 
              len(content.split()), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        return content
    
    def generate_newsletter(self, candidate_id: str) -> str:
        """Generate newsletter for candidate"""
        
        # Similar to blog post but shorter
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM content_candidates WHERE id = ?", (candidate_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            raise ValueError(f"Candidate {candidate_id} not found")
        
        title = row[1]
        preview = row[14]
        
        prompt = f"""Write a brief newsletter about: {title}

{preview}

300-400 words, format:
- What changed
- Why it matters
- What to do

Tone: Direct, actionable"""

        content = self.claude.get_response(prompt, [])
        
        # Save
        gen_id = f"gen_{uuid.uuid4().hex[:12]}"
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO generated_content VALUES (?,?,?,?,?,?,?)
        """, (gen_id, candidate_id, "newsletter", title, content,
              len(content.split()), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        return content
