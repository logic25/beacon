"""
Analytics tracking for Beacon bot.
Logs every question, answer, and user interaction for dashboard.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Interaction:
    """A single user interaction with the bot."""
    timestamp: str
    user_id: str
    user_name: str
    space_name: str
    question: str
    command: Optional[str]  # /lookup, /correct, etc. or None for chat
    answered: bool  # Did bot provide an answer?
    response_length: int
    had_sources: bool  # Did response include RAG sources?
    tokens_used: int
    cost_usd: float
    response_time_ms: int
    confidence: Optional[float]  # 0.0-1.0 if we can estimate


class AnalyticsDB:
    """
    SQLite database for tracking bot usage.
    
    Tables:
    - interactions: Every question asked
    - suggestions: Team suggestions via /suggest
    - corrections: Admin corrections via /correct
    - feedback: Feature requests via /feedback
    """
    
    def __init__(self, db_path: str = "beacon_analytics.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Interactions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                space_name TEXT,
                question TEXT NOT NULL,
                command TEXT,
                answered BOOLEAN NOT NULL,
                response_length INTEGER,
                had_sources BOOLEAN,
                tokens_used INTEGER,
                cost_usd REAL,
                response_time_ms INTEGER,
                confidence REAL
            )
        """)
        
        # Suggestions table (from /suggest)
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
        
        # Corrections table (from /correct)
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
        
        # Feedback table (from /feedback)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                feedback_text TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                responded_by TEXT,
                responded_at TEXT
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_interactions_timestamp 
            ON interactions(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_interactions_user 
            ON interactions(user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_suggestions_status 
            ON suggestions(status)
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Analytics database initialized at {self.db_path}")
    
    def log_interaction(self, interaction: Interaction) -> None:
        """Log a user interaction."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO interactions (
                timestamp, user_id, user_name, space_name, question,
                command, answered, response_length, had_sources,
                tokens_used, cost_usd, response_time_ms, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            interaction.timestamp,
            interaction.user_id,
            interaction.user_name,
            interaction.space_name,
            interaction.question,
            interaction.command,
            interaction.answered,
            interaction.response_length,
            interaction.had_sources,
            interaction.tokens_used,
            interaction.cost_usd,
            interaction.response_time_ms,
            interaction.confidence,
        ))
        
        conn.commit()
        conn.close()
    
    def log_suggestion(
        self,
        user_id: str,
        user_name: str,
        wrong: str,
        correct: str,
        topics: list[str],
    ) -> int:
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
    
    def log_correction(
        self,
        user_id: str,
        user_name: str,
        wrong: str,
        correct: str,
        topics: list[str],
    ) -> int:
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
    
    def log_feedback(
        self,
        user_id: str,
        user_name: str,
        feedback: str,
    ) -> int:
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
    
    def get_stats(self, days: int = 7) -> dict:
        """Get usage statistics for the last N days."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        # Total questions
        cursor.execute("""
            SELECT COUNT(*) FROM interactions WHERE timestamp > ?
        """, (cutoff,))
        total_questions = cursor.fetchone()[0]
        
        # Success rate
        cursor.execute("""
            SELECT COUNT(*) FROM interactions 
            WHERE timestamp > ? AND answered = 1
        """, (cutoff,))
        answered = cursor.fetchone()[0]
        success_rate = (answered / total_questions * 100) if total_questions > 0 else 0
        
        # Active users
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) FROM interactions 
            WHERE timestamp > ?
        """, (cutoff,))
        active_users = cursor.fetchone()[0]
        
        # Total cost
        cursor.execute("""
            SELECT SUM(cost_usd) FROM interactions 
            WHERE timestamp > ?
        """, (cutoff,))
        total_cost = cursor.fetchone()[0] or 0.0
        
        # Top users
        cursor.execute("""
            SELECT user_name, COUNT(*) as count 
            FROM interactions 
            WHERE timestamp > ?
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 10
        """, (cutoff,))
        top_users = [{"name": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Top questions
        cursor.execute("""
            SELECT question, COUNT(*) as count 
            FROM interactions 
            WHERE timestamp > ? AND command IS NULL
            GROUP BY question 
            ORDER BY count DESC 
            LIMIT 20
        """, (cutoff,))
        top_questions = [{"question": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        # Pending suggestions
        cursor.execute("""
            SELECT COUNT(*) FROM suggestions WHERE status = 'pending'
        """)
        pending_suggestions = cursor.fetchone()[0]
        
        # New feedback
        cursor.execute("""
            SELECT COUNT(*) FROM feedback WHERE status = 'new'
        """)
        new_feedback = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "period_days": days,
            "total_questions": total_questions,
            "answered": answered,
            "success_rate": round(success_rate, 1),
            "active_users": active_users,
            "total_cost_usd": round(total_cost, 4),
            "top_users": top_users,
            "top_questions": top_questions,
            "pending_suggestions": pending_suggestions,
            "new_feedback": new_feedback,
        }
    
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
    
    def approve_suggestion(
        self,
        suggestion_id: int,
        reviewed_by: str,
    ) -> dict:
        """Approve a suggestion and return the correction data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get suggestion data
        cursor.execute("""
            SELECT wrong_answer, correct_answer, topics 
            FROM suggestions WHERE id = ?
        """, (suggestion_id,))
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Suggestion {suggestion_id} not found")
        
        wrong, correct, topics = row
        
        # Mark as approved
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
    
    def reject_suggestion(
        self,
        suggestion_id: int,
        reviewed_by: str,
    ) -> None:
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


# Convenience function for bot_v2.py
def get_analytics_db() -> AnalyticsDB:
    """Get the analytics database instance."""
    return AnalyticsDB()
