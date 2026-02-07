"""
Google Chat History Ingestion Script

Parses exported Google Chat conversations and extracts valuable Q&A pairs
for ingestion into the RAG knowledge base.

Uses smart filtering to separate industry knowledge from casual chat.
"""

import re
import json
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
import hashlib

# For reading .docx files
try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    print("Warning: python-docx not installed. Install with: pip install python-docx")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION - Customize these for your industry
# ============================================================================

# Keywords that indicate valuable industry content
INDUSTRY_TERMS = [
    # DOB / Permits
    "dob", "permit", "filing", "zoning", "code", "violation", "objection",
    "alt 1", "alt 2", "alt 3", "nb", "dm", "sign off", "sign-off", "approval",
    "bis", "bisweb", "now", "dob now", "plan exam", "examiner", "审查",

    # Building types / classifications
    "building class", "occupancy", "use group", "assembly", "mercantile",
    "residential", "commercial", "mixed use", "mixed-use",

    # Zoning
    "far", "setback", "lot coverage", "yard", "height limit", "bulk",
    "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10",
    "c1", "c2", "c3", "c4", "c5", "c6", "m1", "m2", "m3",

    # Certificates
    "co", "tco", "certificate of occupancy", "temporary certificate",
    "letter of completion", "loc", "final inspection",

    # Other agencies
    "lpc", "landmark", "fdny", "dep", "dot", "hpd", "ecc", "mta",
    "landmarks preservation", "fire department", "environmental",

    # Construction
    "sprinkler", "standpipe", "egress", "stairs", "elevator", "boiler",
    "plumbing", "electrical", "mechanical", "structural",

    # Documents
    "tr1", "tr2", "tr3", "tr8", "pai", "paa", "ppo", "lno",
    "plans", "drawings", "specs", "survey", "i-card",

    # Process terms
    "reinstate", "supersede", "amend", "withdraw", "appeal",
    "audit", "hold", "objections", "items required", "required items",

    # NYC specific
    "manhattan", "brooklyn", "bronx", "queens", "staten island",
    "borough", "bbl", "bin", "block", "lot",
]

# Patterns that indicate a question
QUESTION_PATTERNS = [
    r'\?$',                                    # Ends with question mark
    r'\?\s*$',                                 # Question mark with trailing space
    r'^(how|what|when|where|why|who|which)',   # Question words at start
    r'^(can|could|do|does|did|is|are|was|were|has|have|should|would)',  # Auxiliary verbs
    r'anyone know',
    r'does anyone',
    r'has anyone',
    r'do we have',
    r'do you know',
    r'what\'s the',
    r'how do (i|you|we)',
    r'is there a',
    r'are there any',
]

# Signals of a good answer
ANSWER_QUALITY_SIGNALS = [
    r'https?://',                              # Contains URL
    r'\d{2,}',                                 # Contains numbers (code refs, dates)
    r'§\s*\d',                                 # Section symbol with number
    r'\b\d{1,3}-\d{1,3}\b',                    # Code pattern like 27-751
    r'(correct|yes|no,?\s|exactly|right)',     # Affirmation/negation
    r'(you need|you have to|required|must)',   # Procedural language
    r'(according to|per the|based on)',        # Citation language
    r'(always|never|typically|usually)',       # Authoritative language
    r'(i think|i believe|in my experience)',   # Experience-based
]

# Patterns to EXCLUDE (casual chat, social messages)
EXCLUDE_PATTERNS = [
    r'^(hi|hey|hello|morning|afternoon|evening)\s*!?\s*$',
    r'^(thanks|thank you|thx|ty)\s*!?\s*$',
    r'^(ok|okay|k|got it|sounds good)\s*!?\s*$',
    r'^(lol|haha|lmao|😂|🤣|😅)',
    r'^(yes|no|yeah|yep|nope)\s*!?\s*$',
    r'happy (birthday|thanksgiving|holiday|new year)',
    r'(lunch|dinner|coffee|tea|break)\??\s*$',
    r'^(brb|bbl|gtg|ttyl)',
    r'^\s*$',                                   # Empty messages
]


@dataclass
class ChatMessage:
    """A single chat message."""
    sender: str
    timestamp: Optional[datetime]
    content: str

    def has_industry_terms(self) -> bool:
        """Check if message contains industry-relevant terms."""
        content_lower = self.content.lower()
        return any(term in content_lower for term in INDUSTRY_TERMS)

    def is_question(self) -> bool:
        """Check if message appears to be a question."""
        content_lower = self.content.lower().strip()
        return any(re.search(pattern, content_lower, re.IGNORECASE)
                   for pattern in QUESTION_PATTERNS)

    def is_excluded(self) -> bool:
        """Check if message matches exclusion patterns (casual chat)."""
        content_lower = self.content.lower().strip()
        # Short messages without industry terms are likely casual
        if len(self.content.strip()) < 10 and not self.has_industry_terms():
            return True
        return any(re.search(pattern, content_lower, re.IGNORECASE)
                   for pattern in EXCLUDE_PATTERNS)

    def answer_quality_score(self) -> int:
        """Score how good this message is as an answer (0-10)."""
        score = 0
        content = self.content

        # Length bonus (longer = more informative, up to a point)
        if len(content) > 50:
            score += 1
        if len(content) > 100:
            score += 1
        if len(content) > 200:
            score += 1

        # Quality signals
        for pattern in ANSWER_QUALITY_SIGNALS:
            if re.search(pattern, content, re.IGNORECASE):
                score += 1

        # Industry terms bonus
        if self.has_industry_terms():
            score += 2

        return min(score, 10)


@dataclass
class QAPair:
    """A question-answer pair extracted from chat."""
    question: str
    answer: str
    question_author: str
    answer_author: str
    timestamp: Optional[str]
    confidence: float  # 0-1, how confident we are this is valuable
    source: str = "google_chat"
    review_status: str = "pending"  # pending, approved, rejected

    def to_dict(self) -> dict:
        return asdict(self)

    def content_hash(self) -> str:
        """Generate unique hash for deduplication."""
        content = f"{self.question}|{self.answer}".lower()
        return hashlib.md5(content.encode()).hexdigest()[:12]


class ChatParser:
    """Parse Google Chat exports into messages."""

    def parse_docx(self, filepath: str) -> list[ChatMessage]:
        """Parse a .docx export from Google Chat."""
        if not HAS_DOCX:
            raise ImportError("python-docx required. Install with: pip install python-docx")

        doc = Document(filepath)
        messages = []

        current_sender = None
        current_timestamp = None
        current_content_lines = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # Try to detect sender line (e.g., "Chris Henry, Dec 6, 10:20 AM")
            sender_match = re.match(
                r'^([A-Za-z\s]+),\s*(\w+\s+\d+,?\s*\d*:?\d*\s*[AP]?M?)',
                text
            )

            if sender_match:
                # Save previous message if exists
                if current_sender and current_content_lines:
                    content = "\n".join(current_content_lines).strip()
                    if content:
                        messages.append(ChatMessage(
                            sender=current_sender,
                            timestamp=current_timestamp,
                            content=content
                        ))

                # Start new message
                current_sender = sender_match.group(1).strip()
                timestamp_str = sender_match.group(2).strip()
                current_timestamp = self._parse_timestamp(timestamp_str)
                current_content_lines = []
            else:
                # Continue current message
                current_content_lines.append(text)

        # Don't forget last message
        if current_sender and current_content_lines:
            content = "\n".join(current_content_lines).strip()
            if content:
                messages.append(ChatMessage(
                    sender=current_sender,
                    timestamp=current_timestamp,
                    content=content
                ))

        return messages

    def parse_text(self, filepath: str) -> list[ChatMessage]:
        """Parse a plain text chat export."""
        messages = []

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Try to split by common patterns
        # Pattern: "Name, Date Time" or "[Date Time] Name:"
        lines = content.split('\n')

        current_sender = None
        current_content_lines = []

        for line in lines:
            # Try different sender patterns
            sender_match = (
                re.match(r'^([A-Za-z\s]+),\s*(.+)$', line) or
                re.match(r'^\[(.+)\]\s*([A-Za-z\s]+):', line)
            )

            if sender_match:
                if current_sender and current_content_lines:
                    messages.append(ChatMessage(
                        sender=current_sender,
                        timestamp=None,
                        content="\n".join(current_content_lines).strip()
                    ))

                current_sender = sender_match.group(1).strip()
                current_content_lines = []
            else:
                current_content_lines.append(line)

        if current_sender and current_content_lines:
            messages.append(ChatMessage(
                sender=current_sender,
                timestamp=None,
                content="\n".join(current_content_lines).strip()
            ))

        return messages

    def _parse_timestamp(self, ts_str: str) -> Optional[datetime]:
        """Try to parse various timestamp formats."""
        formats = [
            "%b %d, %I:%M %p",
            "%b %d, %Y %I:%M %p",
            "%B %d, %I:%M %p",
            "%m/%d/%Y %I:%M %p",
            "%Y-%m-%d %H:%M",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue

        return None


class QAExtractor:
    """Extract Q&A pairs from chat messages."""

    def __init__(self, min_confidence: float = 0.5):
        self.min_confidence = min_confidence

    def extract(self, messages: list[ChatMessage]) -> list[QAPair]:
        """Extract Q&A pairs from a list of messages."""
        qa_pairs = []

        i = 0
        while i < len(messages):
            msg = messages[i]

            # Skip excluded messages
            if msg.is_excluded():
                i += 1
                continue

            # Look for questions
            if msg.is_question() and msg.has_industry_terms():
                # Look for answer in next few messages
                best_answer = None
                best_score = 0
                answer_author = None

                # Check next 3 messages for potential answers
                for j in range(i + 1, min(i + 4, len(messages))):
                    candidate = messages[j]

                    # Answer should be from different person
                    if candidate.sender == msg.sender:
                        continue

                    # Skip excluded
                    if candidate.is_excluded():
                        continue

                    score = candidate.answer_quality_score()
                    if score > best_score:
                        best_score = score
                        best_answer = candidate
                        answer_author = candidate.sender

                # If we found a decent answer, create Q&A pair
                if best_answer and best_score >= 2:
                    confidence = self._calculate_confidence(msg, best_answer, best_score)

                    if confidence >= self.min_confidence:
                        qa_pairs.append(QAPair(
                            question=msg.content,
                            answer=best_answer.content,
                            question_author=msg.sender,
                            answer_author=answer_author,
                            timestamp=msg.timestamp.isoformat() if msg.timestamp else None,
                            confidence=confidence,
                        ))

            i += 1

        return self._deduplicate(qa_pairs)

    def _calculate_confidence(
        self,
        question: ChatMessage,
        answer: ChatMessage,
        answer_score: int
    ) -> float:
        """Calculate confidence score for a Q&A pair."""
        confidence = 0.0

        # Base score from answer quality
        confidence += answer_score * 0.08  # Max 0.8 from score

        # Bonus if question has strong industry terms
        industry_count = sum(
            1 for term in INDUSTRY_TERMS
            if term in question.content.lower()
        )
        confidence += min(industry_count * 0.05, 0.15)

        # Bonus if answer also has industry terms
        if answer.has_industry_terms():
            confidence += 0.1

        # Bonus for longer, more detailed answers
        if len(answer.content) > 150:
            confidence += 0.05

        return min(confidence, 1.0)

    def _deduplicate(self, qa_pairs: list[QAPair]) -> list[QAPair]:
        """Remove duplicate Q&A pairs."""
        seen = set()
        unique = []

        for qa in qa_pairs:
            hash_key = qa.content_hash()
            if hash_key not in seen:
                seen.add(hash_key)
                unique.append(qa)

        return unique


def ingest_chat_file(
    filepath: str,
    output_dir: str = "data/qa_pairs",
    min_confidence: float = 0.5,
) -> dict:
    """
    Ingest a chat export file and extract Q&A pairs.

    Args:
        filepath: Path to chat export (.docx or .txt)
        output_dir: Directory to save extracted Q&A pairs
        min_confidence: Minimum confidence threshold (0-1)

    Returns:
        Summary of extraction results
    """
    filepath = Path(filepath)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse messages
    parser = ChatParser()

    if filepath.suffix.lower() == '.docx':
        messages = parser.parse_docx(str(filepath))
    else:
        messages = parser.parse_text(str(filepath))

    logger.info(f"Parsed {len(messages)} messages from {filepath.name}")

    # Extract Q&A pairs
    extractor = QAExtractor(min_confidence=min_confidence)
    qa_pairs = extractor.extract(messages)

    logger.info(f"Extracted {len(qa_pairs)} Q&A pairs")

    # Separate by confidence for review
    high_confidence = [qa for qa in qa_pairs if qa.confidence >= 0.7]
    medium_confidence = [qa for qa in qa_pairs if 0.5 <= qa.confidence < 0.7]

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # High confidence - ready to ingest
    if high_confidence:
        high_file = output_dir / f"qa_high_confidence_{timestamp}.json"
        with open(high_file, 'w') as f:
            json.dump([qa.to_dict() for qa in high_confidence], f, indent=2)
        logger.info(f"Saved {len(high_confidence)} high-confidence pairs to {high_file}")

    # Medium confidence - needs review
    if medium_confidence:
        review_file = output_dir / f"qa_needs_review_{timestamp}.json"
        with open(review_file, 'w') as f:
            json.dump([qa.to_dict() for qa in medium_confidence], f, indent=2)
        logger.info(f"Saved {len(medium_confidence)} pairs for review to {review_file}")

    # Summary
    return {
        "total_messages": len(messages),
        "qa_pairs_extracted": len(qa_pairs),
        "high_confidence": len(high_confidence),
        "needs_review": len(medium_confidence),
        "output_files": {
            "high_confidence": str(high_file) if high_confidence else None,
            "needs_review": str(review_file) if medium_confidence else None,
        }
    }


def ingest_qa_to_rag(qa_file: str):
    """
    Ingest approved Q&A pairs into the RAG vector store.

    Args:
        qa_file: Path to JSON file with Q&A pairs
    """
    from vector_store import VectorStore
    from config import get_settings

    settings = get_settings()
    vector_store = VectorStore(settings)

    with open(qa_file, 'r') as f:
        qa_pairs = json.load(f)

    for qa in qa_pairs:
        # Format as a knowledge document
        content = f"Q: {qa['question']}\n\nA: {qa['answer']}"

        metadata = {
            "source": "team_chat",
            "type": "qa_pair",
            "question_author": qa.get("question_author", "unknown"),
            "answer_author": qa.get("answer_author", "unknown"),
            "confidence": qa.get("confidence", 0.5),
            "timestamp": qa.get("timestamp"),
        }

        vector_store.upsert(
            content=content,
            metadata=metadata,
        )

    logger.info(f"Ingested {len(qa_pairs)} Q&A pairs into RAG")


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Q&A pairs from Google Chat exports"
    )
    parser.add_argument(
        "filepath",
        help="Path to chat export file (.docx or .txt)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="data/qa_pairs",
        help="Directory to save extracted Q&A pairs"
    )
    parser.add_argument(
        "--min-confidence", "-c",
        type=float,
        default=0.5,
        help="Minimum confidence threshold (0-1, default 0.5)"
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Immediately ingest high-confidence pairs to RAG"
    )

    args = parser.parse_args()

    print(f"\n📥 Processing: {args.filepath}")
    print("=" * 50)

    results = ingest_chat_file(
        args.filepath,
        output_dir=args.output_dir,
        min_confidence=args.min_confidence,
    )

    print(f"\n📊 Results:")
    print(f"   Total messages parsed: {results['total_messages']}")
    print(f"   Q&A pairs extracted: {results['qa_pairs_extracted']}")
    print(f"   High confidence (ready): {results['high_confidence']}")
    print(f"   Needs review: {results['needs_review']}")

    if results['output_files']['high_confidence']:
        print(f"\n✅ High confidence pairs: {results['output_files']['high_confidence']}")
    if results['output_files']['needs_review']:
        print(f"⚠️  Review needed: {results['output_files']['needs_review']}")

    if args.ingest and results['output_files']['high_confidence']:
        print("\n🔄 Ingesting to RAG...")
        ingest_qa_to_rag(results['output_files']['high_confidence'])
        print("✅ Done!")
