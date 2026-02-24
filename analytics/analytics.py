"""
Enhanced Analytics v2 for Beacon bot.
Tracks everything: interactions, costs, topics, failed queries, document citations.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import re
from analytics.topic_classifier import get_classifier

logger = logging.getLogger(__name__)


@dataclass
class Interaction:
    """A single user interaction with the bot."""
    timestamp: str
    user_id: str
    user_name: str
    space_name: str
    question: str
    response: str  # NEW - full response text
    command: Optional[str]
    answered: bool
    response_length: int
    had_sources: bool
    sources_used: Optional[str]  # NEW - JSON list of sources cited
    tokens_used: int
    cost_usd: float
    response_time_ms: int
    confidence: Optional[float]
    topic: Optional[str]  # NEW - auto-categorized topic


@dataclass
class APIUsage:
    """Track usage across all APIs."""
    timestamp: str
    api_name: str  # "anthropic", "pinecone", "voyage"
    operation: str  # "chat", "search", "embed"
    tokens_used: int
    cost_usd: float


class AnalyticsDB:
    """
    Enhanced SQLite database for comprehensive bot analytics.
    
    New Features:
    - Full conversation storage
    - Multi-API cost tracking
    - Topic categorization
    - Failed query tracking
    - Document citation analytics
    - Slash command usage
    """
    
    def __init__(self, db_path: str = "beacon_analytics.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Enhanced interactions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                space_name TEXT,
                question TEXT NOT NULL,
                response TEXT,
                command TEXT,
                answered BOOLEAN NOT NULL,
                response_length INTEGER,
                had_sources BOOLEAN,
                sources_used TEXT,
                tokens_used INTEGER,
                cost_usd REAL,
                response_time_ms INTEGER,
                confidence REAL,
                topic TEXT
            )
        """)
        
        # API usage tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                api_name TEXT NOT NULL,
                operation TEXT NOT NULL,
                tokens_used INTEGER,
                cost_usd REAL
            )
        """)
        
        # Suggestions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                wrong_answer TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                topics TEXT,
                status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TEXT
            )
        """)
        
        # Corrections table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                wrong_answer TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                topics TEXT,
                applied BOOLEAN DEFAULT 1
            )
        """)
        
        # Feedback table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                feedback_text TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                responded_by TEXT,
                responded_at TEXT,
                roadmap_status TEXT DEFAULT 'backlog',
                priority TEXT DEFAULT 'medium',
                target_quarter TEXT,
                notes TEXT
            )
        """)
        
        # Add roadmap columns to existing feedback table if they don't exist
        try:
            cursor.execute("ALTER TABLE feedback ADD COLUMN roadmap_status TEXT DEFAULT 'backlog'")
        except:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE feedback ADD COLUMN priority TEXT DEFAULT 'medium'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE feedback ADD COLUMN target_quarter TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE feedback ADD COLUMN notes TEXT")
        except:
            pass
        
        # Add command column to interactions table if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE interactions ADD COLUMN command TEXT")
        except:
            pass  # Column already exists
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_topic ON interactions(topic)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_answered ON interactions(answered)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_timestamp ON api_usage(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_name ON api_usage(api_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(status)")
        
        conn.commit()
        conn.close()
        logger.info(f"Enhanced analytics database initialized at {self.db_path}")
    
    def _categorize_topic(self, question: str, response: str = "") -> str:
        """Auto-categorize question into topics using LLM.
        
        Falls back to keyword matching if LLM classification fails.
        """
        try:
            # Try LLM classification first
            classifier = get_classifier()
            topic = classifier.classify(question, response)
            return topic
        except Exception as e:
            logger.warning(f"LLM classification failed, using keyword fallback: {e}")
            # Fallback to keyword matching
            return self._categorize_topic_keywords(question, response)
    
    def _categorize_topic_keywords(self, question: str, response: str = "") -> str:
        """Keyword-based topic categorization (fallback)."""
        combined = (question + " " + response).lower()
        
        # Topic keywords - ORDER MATTERS (most specific first)
        topics = {
            "Noise/Hours": ["what time", "work until", "noise", "after hours", "construction hours"],
            "FDNY": ["fdny", "fire alarm", "sprinkler", "standpipe", "suppression", "ansul"],
            "Certificates": ["co", "certificate of occupancy", "tco", "temporary co"],
            "Violations": ["violation", "ecb", "bis", "hpd violation", "dob violation"],
            "DHCR": ["dhcr", "rent", "stabiliz", "mci", "iai", "lease", "rent increase"],
            "DOB Filings": ["dob", "permit", "filing", "alt1", "alt2", "nb", "dm", "paa", "objection"],
            "Building Code": ["building code", "egress", "fire safety", "occupancy group"],
            "MDL": ["mdl", "multiple dwelling", "class a", "class b"],
            "Zoning": ["zoning", "use group", "far", "setback", "variance", "zr"],
            "Property Lookup": ["lookup", "address", "bin", "block", "lot"],
            "Plans/Drawings": ["plan", "drawing", "elevation", "floor plan", "blueprint"],
        }
        
        for topic, keywords in topics.items():
            if any(kw in combined for kw in keywords):
                return topic
        
        return "General"
    
    def log_interaction(self, interaction: Interaction) -> None:
        """Log a user interaction with enhanced tracking."""
        # Auto-categorize if not provided
        if not interaction.topic:
            interaction.topic = self._categorize_topic(interaction.question, interaction.response)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO interactions (
                timestamp, user_id, user_name, space_name, question, response,
                command, answered, response_length, had_sources, sources_used,
                tokens_used, cost_usd, response_time_ms, confidence, topic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            interaction.timestamp,
            interaction.user_id,
            interaction.user_name,
            interaction.space_name,
            interaction.question,
            interaction.response,
            interaction.command,
            interaction.answered,
            interaction.response_length,
            interaction.had_sources,
            interaction.sources_used,
            interaction.tokens_used,
            interaction.cost_usd,
            interaction.response_time_ms,
            interaction.confidence,
            interaction.topic,
        ))
        
        conn.commit()
        conn.close()
    
    def log_api_usage(self, api_name: str, operation: str, tokens: int, cost: float) -> None:
        """Log API usage for cost tracking."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO api_usage (timestamp, api_name, operation, tokens_used, cost_usd)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), api_name, operation, tokens, cost))
        
        conn.commit()
        conn.close()
    
    def log_suggestion(self, user_id: str, user_name: str, wrong: str, correct: str, topics: list[str]) -> int:
        """Log a correction suggestion from team."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO suggestions (
                timestamp, user_id, user_name, wrong_answer,
                correct_answer, topics, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """, (
            datetime.now().isoformat(),
            user_id,
            user_name,
            wrong,
            correct,
            json.dumps(topics),
        ))
        
        suggestion_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return suggestion_id
    
    def log_correction(self, user_id: str, user_name: str, wrong: str, correct: str, topics: list[str]) -> int:
        """Log an admin correction."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO corrections (
                timestamp, user_id, user_name, wrong_answer,
                correct_answer, topics, applied
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            datetime.now().isoformat(),
            user_id,
            user_name,
            wrong,
            correct,
            json.dumps(topics),
        ))
        
        correction_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return correction_id
    
    def log_feedback(self, user_id: str, user_name: str, feedback: str) -> int:
        """Log a feature request / feedback."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO feedback (
                timestamp, user_id, user_name, feedback_text, status
            ) VALUES (?, ?, ?, ?, 'new')
        """, (
            datetime.now().isoformat(),
            user_id,
            user_name,
            feedback,
        ))

        feedback_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return feedback_id

    def create_roadmap_item(self, title: str, priority: str = "medium",
                            roadmap_status: str = "backlog",
                            target_quarter: str = None,
                            notes: str = None,
                            created_by: str = "admin") -> int:
        """Create a standalone roadmap item (not tied to user feedback)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO feedback (
                timestamp, user_id, user_name, feedback_text, status,
                roadmap_status, priority, target_quarter, notes
            ) VALUES (?, ?, ?, ?, 'roadmap', ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            f"admin:{created_by}",
            created_by,
            title,
            roadmap_status,
            priority,
            target_quarter,
            notes,
        ))

        item_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return item_id
    
    def get_feedback(self, limit: int = 50, status: str = None) -> list[dict]:
        """Get user feedback submissions with roadmap tracking."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if status:
            cursor.execute("""
                SELECT id, timestamp, user_name, feedback_text, status,
                       roadmap_status, priority, target_quarter, notes
                FROM feedback
                WHERE status = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (status, limit))
        else:
            cursor.execute("""
                SELECT id, timestamp, user_name, feedback_text, status,
                       roadmap_status, priority, target_quarter, notes
                FROM feedback
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        feedback = []
        for row in cursor.fetchall():
            feedback.append({
                "id": row[0],
                "timestamp": row[1],
                "user_name": row[2],
                "feedback_text": row[3],
                "status": row[4],
                "roadmap_status": row[5] or 'backlog',
                "priority": row[6] or 'medium',
                "target_quarter": row[7],
                "notes": row[8]
            })
        
        conn.close()
        return feedback
    
    def update_feedback_roadmap(self, feedback_id: int, roadmap_status: str = None, 
                                priority: str = None, target_quarter: str = None, 
                                notes: str = None) -> bool:
        """Update roadmap tracking for a feedback item."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if roadmap_status:
            updates.append("roadmap_status = ?")
            params.append(roadmap_status)
        if priority:
            updates.append("priority = ?")
            params.append(priority)
        if target_quarter:
            updates.append("target_quarter = ?")
            params.append(target_quarter)
        if notes is not None:  # Allow empty string
            updates.append("notes = ?")
            params.append(notes)
        
        if not updates:
            conn.close()
            return False
        
        params.append(feedback_id)
        query = f"UPDATE feedback SET {', '.join(updates)} WHERE id = ?"
        
        cursor.execute(query, params)
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        
        return success
    
    def get_roadmap_summary(self) -> dict:
        """Get roadmap overview grouped by status."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get counts by roadmap status
        cursor.execute("""
            SELECT roadmap_status, COUNT(*) as count
            FROM feedback
            GROUP BY roadmap_status
            ORDER BY 
                CASE roadmap_status
                    WHEN 'shipped' THEN 1
                    WHEN 'in-progress' THEN 2
                    WHEN 'planned' THEN 3
                    WHEN 'backlog' THEN 4
                    WHEN 'archived' THEN 5
                    ELSE 6
                END
        """)
        
        summary = {
            "by_status": {row[0]: row[1] for row in cursor.fetchall()}
        }
        
        # Get items by status
        cursor.execute("""
            SELECT roadmap_status, id, feedback_text, priority, target_quarter, user_name
            FROM feedback
            ORDER BY 
                CASE roadmap_status
                    WHEN 'in-progress' THEN 1
                    WHEN 'planned' THEN 2
                    WHEN 'backlog' THEN 3
                    WHEN 'shipped' THEN 4
                    ELSE 5
                END,
                CASE priority
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END
        """)
        
        items_by_status = {}
        for row in cursor.fetchall():
            status = row[0] or 'backlog'
            if status not in items_by_status:
                items_by_status[status] = []
            items_by_status[status].append({
                "id": row[1],
                "feedback_text": row[2],
                "priority": row[3] or 'medium',
                "target_quarter": row[4],
                "user_name": row[5]
            })
        
        summary["items_by_status"] = items_by_status
        
        conn.close()
        return summary
    
    def get_approved_corrections(self, limit: int = 50) -> list[dict]:
        """Get history of approved corrections."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, timestamp, reviewed_at, reviewed_by, 
                   wrong_answer, correct_answer
            FROM suggestions
            WHERE status = 'approved'
            ORDER BY reviewed_at DESC
            LIMIT ?
        """, (limit,))
        
        corrections = []
        for row in cursor.fetchall():
            corrections.append({
                "id": row[0],
                "timestamp": row[1],
                "reviewed_at": row[2],
                "reviewed_by": row[3],
                "wrong_answer": row[4],
                "correct_answer": row[5]
            })
        
        conn.close()
        return corrections
    
    def get_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: Optional[int] = None
    ) -> dict:
        """
        Get comprehensive statistics for a date range.
        
        Args:
            start_date: ISO format datetime string
            end_date: ISO format datetime string
            days: Number of days to look back (alternative to start/end)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Determine date range
        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            where_clause = "WHERE timestamp > ?"
            params = (cutoff,)
        elif start_date and end_date:
            where_clause = "WHERE timestamp BETWEEN ? AND ?"
            params = (start_date, end_date)
        elif start_date:
            where_clause = "WHERE timestamp > ?"
            params = (start_date,)
        else:
            where_clause = ""
            params = ()
        
        # Total questions
        cursor.execute(f"SELECT COUNT(*) FROM interactions {where_clause}", params)
        total_questions = cursor.fetchone()[0]
        
        # Success rate
        cursor.execute(f"""
            SELECT COUNT(*) FROM interactions 
            {where_clause} {"AND" if where_clause else "WHERE"} answered = 1
        """, params)
        answered = cursor.fetchone()[0]
        success_rate = (answered / total_questions * 100) if total_questions > 0 else 0
        
        # Active users
        cursor.execute(f"""
            SELECT COUNT(DISTINCT user_id) FROM interactions {where_clause}
        """, params)
        active_users = cursor.fetchone()[0]
        
        # Total cost (all APIs)
        cursor.execute(f"""
            SELECT SUM(cost_usd) FROM interactions {where_clause}
        """, params)
        interaction_cost = cursor.fetchone()[0] or 0.0
        
        # API costs breakdown
        api_where = where_clause.replace("timestamp", "api_usage.timestamp") if where_clause else ""
        cursor.execute(f"""
            SELECT api_name, SUM(cost_usd) FROM api_usage 
            {api_where}
            GROUP BY api_name
        """, params)
        api_costs = {row[0]: row[1] for row in cursor.fetchall()}
        
        total_cost = interaction_cost + sum(api_costs.values())
        
        # Top users
        cursor.execute(f"""
            SELECT user_name, COUNT(*) as count 
            FROM interactions 
            {where_clause}
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 10
        """, params)
        top_users = [{"name": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Top questions
        cursor.execute(f"""
            SELECT question, COUNT(*) as count 
            FROM interactions 
            {where_clause} {"AND" if where_clause else "WHERE"} command IS NULL
            GROUP BY question 
            ORDER BY count DESC 
            LIMIT 20
        """, params)
        top_questions = [{"question": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Questions by topic
        cursor.execute(f"""
            SELECT topic, COUNT(*) as count 
            FROM interactions 
            {where_clause}
            GROUP BY topic 
            ORDER BY count DESC
        """, params)
        topics = [{"topic": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Failed queries (not answered or low confidence)
        cursor.execute(f"""
            SELECT question, response, confidence 
            FROM interactions 
            {where_clause} {"AND" if where_clause else "WHERE"} 
            (answered = 0 OR confidence < 0.7)
            ORDER BY timestamp DESC
            LIMIT 20
        """, params)
        failed_queries = [{
            "question": row[0],
            "response": row[1][:100] if row[1] else "",
            "confidence": row[2]
        } for row in cursor.fetchall()]
        
        # Slash command usage
        cursor.execute(f"""
            SELECT command, COUNT(*) as count 
            FROM interactions 
            {where_clause} {"AND" if where_clause else "WHERE"} command IS NOT NULL
            GROUP BY command 
            ORDER BY count DESC
        """, params)
        command_usage = [{"command": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Response time stats
        cursor.execute(f"""
            SELECT AVG(response_time_ms), MIN(response_time_ms), MAX(response_time_ms)
            FROM interactions {where_clause}
        """, params)
        rt_row = cursor.fetchone()
        response_time_stats = {
            "avg_ms": int(rt_row[0]) if rt_row[0] else 0,
            "min_ms": int(rt_row[1]) if rt_row[1] else 0,
            "max_ms": int(rt_row[2]) if rt_row[2] else 0,
        }
        
        # Pending suggestions
        cursor.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'pending'")
        pending_suggestions = cursor.fetchone()[0]
        
        # New feedback
        cursor.execute("SELECT COUNT(*) FROM feedback WHERE status = 'new'")
        new_feedback = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "date_range": {
                "start": start_date or (datetime.now() - timedelta(days=days or 7)).isoformat() if days else "all time",
                "end": end_date or datetime.now().isoformat(),
                "days": days
            },
            "total_questions": total_questions,
            "answered": answered,
            "success_rate": round(success_rate, 1),
            "active_users": active_users,
            "total_cost_usd": round(total_cost, 4),
            "api_costs": {k: round(v, 4) for k, v in api_costs.items()},
            "top_users": top_users,
            "top_questions": top_questions,
            "topics": topics,
            "failed_queries": failed_queries,
            "command_usage": command_usage,
            "response_time": response_time_stats,
            "pending_suggestions": pending_suggestions,
            "new_feedback": new_feedback,
        }
    
    def get_recent_conversations(self, limit: int = 20, user_id: Optional[str] = None) -> list[dict]:
        """Get recent Q&A conversations with full responses."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        where_clause = "WHERE user_id = ?" if user_id else ""
        params = (user_id, limit) if user_id else (limit,)
        
        cursor.execute(f"""
            SELECT timestamp, user_name, question, response, sources_used, 
                   topic, confidence, response_time_ms, cost_usd
            FROM interactions 
            {where_clause}
            ORDER BY timestamp DESC 
            LIMIT ?
        """, params)
        
        conversations = []
        for row in cursor.fetchall():
            conversations.append({
                "timestamp": row[0],
                "user_name": row[1],
                "question": row[2],
                "response": row[3],
                "sources": json.loads(row[4]) if row[4] else [],
                "topic": row[5],
                "confidence": row[6],
                "response_time_ms": row[7],
                "cost_usd": row[8],
            })
        
        conn.close()
        return conversations
    
    def get_pending_suggestions(self) -> list[dict]:
        """Get all pending suggestions for review."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, timestamp, user_name, wrong_answer, 
                   correct_answer, topics
            FROM suggestions 
            WHERE status = 'pending'
            ORDER BY timestamp DESC
        """)
        
        suggestions = []
        for row in cursor.fetchall():
            suggestions.append({
                "id": row[0],
                "timestamp": row[1],
                "user_name": row[2],
                "wrong_answer": row[3],
                "correct_answer": row[4],
                "topics": json.loads(row[5]) if row[5] else [],
            })
        
        conn.close()
        return suggestions
    
    
    def get_question_clusters(self, threshold: float = 0.85, min_questions: int = 2) -> list[dict]:
        """Group similar questions using semantic similarity with Voyage AI."""
        try:
            import os
            voyage_api_key = os.getenv("VOYAGE_API_KEY")
            if not voyage_api_key:
                return self._get_exact_questions_fallback()
            
            try:
                from voyageai import Client as VoyageClient
            except ImportError:
                logger.warning("voyageai not installed, using exact matching")
                return self._get_exact_questions_fallback()
            
            voyage = VoyageClient(api_key=voyage_api_key)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT question, COUNT(*) as count
                FROM interactions
                WHERE command IS NULL AND question IS NOT NULL AND question != ''
                GROUP BY question
                ORDER BY count DESC
                LIMIT 50
            """)
            questions_data = cursor.fetchall()
            conn.close()
            
            if len(questions_data) < min_questions:
                return self._get_exact_questions_fallback()
            
            question_texts = [q[0] for q in questions_data]
            question_counts = {q[0]: q[1] for q in questions_data}
            
            result = voyage.embed(question_texts, model="voyage-2", input_type="document")
            embeddings = result.embeddings
            
            clusters = []
            used = set()
            
            for i, q1 in enumerate(question_texts):
                if i in used:
                    continue
                
                cluster = {
                    "representative": q1,
                    "variations": [q1],
                    "total_count": question_counts[q1],
                    "example_variations": [q1]
                }
                used.add(i)
                
                for j in range(i + 1, len(question_texts)):
                    if j in used:
                        continue
                    
                    q2 = question_texts[j]
                    similarity = self._cosine_similarity(embeddings[i], embeddings[j])
                    
                    if similarity >= threshold:
                        cluster["variations"].append(q2)
                        cluster["total_count"] += question_counts[q2]
                        if len(cluster["example_variations"]) < 3:
                            cluster["example_variations"].append(q2)
                        used.add(j)
                
                clusters.append(cluster)
            
            clusters.sort(key=lambda x: x["total_count"], reverse=True)
            return clusters[:20]
        
        except Exception as e:
            logger.error(f"Question clustering failed: {e}", exc_info=True)
            return self._get_exact_questions_fallback()
    
    def _cosine_similarity(self, a: list, b: list) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        dot_product = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        return dot_product / (mag_a * mag_b) if mag_a and mag_b else 0.0
    
    def _get_exact_questions_fallback(self) -> list[dict]:
        """Fallback to exact matching when clustering unavailable."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT question, COUNT(*) as count
            FROM interactions
            WHERE command IS NULL AND question IS NOT NULL
            GROUP BY question
            ORDER BY count DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            "representative": row[0],
            "variations": [row[0]],
            "total_count": row[1],
            "example_variations": [row[0]]
        } for row in rows]


    def approve_suggestion(self, suggestion_id: int, reviewed_by: str) -> dict:
        """Approve a suggestion and return the correction data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT wrong_answer, correct_answer, topics 
            FROM suggestions WHERE id = ?
        """, (suggestion_id,))
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Suggestion {suggestion_id} not found")
        
        wrong, correct, topics = row
        
        cursor.execute("""
            UPDATE suggestions 
            SET status = 'approved', 
                reviewed_by = ?, 
                reviewed_at = ?
            WHERE id = ?
        """, (reviewed_by, datetime.now().isoformat(), suggestion_id))
        
        conn.commit()
        conn.close()
        
        return {
            "wrong_answer": wrong,
            "correct_answer": correct,
            "topics": json.loads(topics) if topics else [],
        }
    
    def reject_suggestion(self, suggestion_id: int, reviewed_by: str) -> None:
        """Reject a suggestion."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE suggestions 
            SET status = 'rejected', 
                reviewed_by = ?, 
                reviewed_at = ?
            WHERE id = ?
        """, (reviewed_by, datetime.now().isoformat(), suggestion_id))
        
        conn.commit()
        conn.close()


def get_analytics_db() -> AnalyticsDB:
    """Get the analytics database instance."""
    return AnalyticsDB()
