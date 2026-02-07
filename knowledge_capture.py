"""
Knowledge capture system for improving Claude's responses.
Captures Q&A pairs, corrections, and team knowledge from conversations.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeEntry:
    """A piece of captured knowledge."""

    entry_id: str
    entry_type: str  # "qa_pair", "correction", "procedure", "tip"

    # Content
    question: str  # The question or scenario
    answer: str  # The correct answer or guidance
    context: str = ""  # Additional context

    # Metadata
    source: str = "team"  # Who provided this (team member, expert, etc.)
    confidence: str = "verified"  # verified, suggested, needs_review
    topics: list[str] = field(default_factory=list)  # DOB, DHCR, zoning, etc.

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "question": self.question,
            "answer": self.answer,
            "context": self.context,
            "source": self.source,
            "confidence": self.confidence,
            "topics": self.topics,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEntry":
        return cls(**data)

    def to_training_format(self) -> str:
        """Format for inclusion in RAG context."""
        lines = [
            f"**Q:** {self.question}",
            f"**A:** {self.answer}",
        ]
        if self.context:
            lines.append(f"**Context:** {self.context}")
        if self.topics:
            lines.append(f"**Topics:** {', '.join(self.topics)}")
        return "\n".join(lines)


class KnowledgeBase:
    """
    Captures and stores team knowledge for improving Claude's responses.

    Usage:
        kb = KnowledgeBase()

        # Add a Q&A pair
        kb.add_qa("What form do I need for a CCD1?",
                  "Use the ZRD1 form for zoning determinations...",
                  topics=["DOB", "zoning"])

        # Add a correction
        kb.add_correction("Claude said X but the correct answer is Y",
                          topics=["DHCR"])

        # Export for RAG ingestion
        kb.export_for_rag()
    """

    def __init__(self, storage_path: str = "knowledge_base.json"):
        self.storage_path = Path(storage_path)
        self.entries: dict[str, KnowledgeEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load knowledge base from disk."""
        if self.storage_path.exists():
            try:
                with self.storage_path.open() as f:
                    data = json.load(f)
                    self.entries = {
                        entry_id: KnowledgeEntry.from_dict(entry_data)
                        for entry_id, entry_data in data.items()
                    }
                logger.info(f"Loaded {len(self.entries)} knowledge entries")
            except Exception as e:
                logger.error(f"Failed to load knowledge base: {e}")

    def save(self) -> None:
        """Save knowledge base to disk."""
        try:
            with self.storage_path.open("w") as f:
                data = {
                    entry_id: entry.to_dict()
                    for entry_id, entry in self.entries.items()
                }
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save knowledge base: {e}")

    def _generate_id(self) -> str:
        """Generate a unique entry ID."""
        import hashlib
        timestamp = datetime.now().isoformat()
        return hashlib.md5(timestamp.encode()).hexdigest()[:12]

    def add_qa(
        self,
        question: str,
        answer: str,
        context: str = "",
        topics: Optional[list[str]] = None,
        source: str = "team",
    ) -> KnowledgeEntry:
        """Add a question-answer pair.

        Use this to capture:
        - Common questions your team gets
        - Expert answers that Claude should learn
        - Specific NYC scenarios with correct guidance
        """
        entry = KnowledgeEntry(
            entry_id=self._generate_id(),
            entry_type="qa_pair",
            question=question,
            answer=answer,
            context=context,
            topics=topics or [],
            source=source,
        )
        self.entries[entry.entry_id] = entry
        self.save()
        logger.info(f"Added Q&A pair: {entry.entry_id}")
        return entry

    def add_correction(
        self,
        original_response: str,
        correct_answer: str,
        context: str = "",
        topics: Optional[list[str]] = None,
    ) -> KnowledgeEntry:
        """Add a correction for when Claude was wrong.

        Use this when Claude gives incorrect information and you
        want to make sure it gets it right next time.
        """
        entry = KnowledgeEntry(
            entry_id=self._generate_id(),
            entry_type="correction",
            question=f"Correction needed: {original_response[:200]}...",
            answer=correct_answer,
            context=context,
            topics=topics or [],
            source="correction",
        )
        self.entries[entry.entry_id] = entry
        self.save()
        logger.info(f"Added correction: {entry.entry_id}")
        return entry

    def add_procedure(
        self,
        scenario: str,
        steps: str,
        topics: Optional[list[str]] = None,
        source: str = "team",
    ) -> KnowledgeEntry:
        """Add a procedure or decision tree.

        Use this to capture your team's processes, like:
        - "When a client asks about X, first check Y, then Z"
        - Step-by-step filing procedures
        """
        entry = KnowledgeEntry(
            entry_id=self._generate_id(),
            entry_type="procedure",
            question=scenario,
            answer=steps,
            topics=topics or [],
            source=source,
        )
        self.entries[entry.entry_id] = entry
        self.save()
        logger.info(f"Added procedure: {entry.entry_id}")
        return entry

    def add_tip(
        self,
        tip: str,
        context: str = "",
        topics: Optional[list[str]] = None,
    ) -> KnowledgeEntry:
        """Add a quick tip or gotcha.

        Use for things like:
        - "DOB often misses X, always double-check"
        - "The form says Y but they actually want Z"
        """
        entry = KnowledgeEntry(
            entry_id=self._generate_id(),
            entry_type="tip",
            question="Pro tip:",
            answer=tip,
            context=context,
            topics=topics or [],
            source="team",
        )
        self.entries[entry.entry_id] = entry
        self.save()
        logger.info(f"Added tip: {entry.entry_id}")
        return entry

    def get_by_topic(self, topic: str) -> list[KnowledgeEntry]:
        """Get all entries for a specific topic."""
        return [
            entry for entry in self.entries.values()
            if topic.lower() in [t.lower() for t in entry.topics]
        ]

    def export_for_rag(self, output_path: str = "knowledge_export.txt") -> str:
        """Export all knowledge entries as a text file for RAG ingestion.

        Returns:
            Path to the exported file
        """
        output = Path(output_path)

        lines = [
            "# Beacon Team Knowledge Base",
            f"# Exported: {datetime.now().isoformat()}",
            f"# Entries: {len(self.entries)}",
            "",
            "---",
            "",
        ]

        # Group by type
        by_type: dict[str, list[KnowledgeEntry]] = {}
        for entry in self.entries.values():
            if entry.entry_type not in by_type:
                by_type[entry.entry_type] = []
            by_type[entry.entry_type].append(entry)

        type_titles = {
            "qa_pair": "## Common Questions & Answers",
            "correction": "## Important Corrections",
            "procedure": "## Procedures & Workflows",
            "tip": "## Tips & Gotchas",
        }

        for entry_type, title in type_titles.items():
            entries = by_type.get(entry_type, [])
            if entries:
                lines.append(title)
                lines.append("")
                for entry in entries:
                    lines.append(entry.to_training_format())
                    lines.append("")
                    lines.append("---")
                    lines.append("")

        with output.open("w") as f:
            f.write("\n".join(lines))

        logger.info(f"Exported {len(self.entries)} entries to {output}")
        return str(output)

    def get_stats(self) -> dict:
        """Get statistics about the knowledge base."""
        by_type = {}
        by_topic = {}

        for entry in self.entries.values():
            by_type[entry.entry_type] = by_type.get(entry.entry_type, 0) + 1
            for topic in entry.topics:
                by_topic[topic] = by_topic.get(topic, 0) + 1

        return {
            "total_entries": len(self.entries),
            "by_type": by_type,
            "by_topic": by_topic,
        }


# CLI for quick knowledge capture
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Capture team knowledge")
    parser.add_argument("--add-qa", action="store_true", help="Add a Q&A pair")
    parser.add_argument("--add-correction", action="store_true", help="Add a correction")
    parser.add_argument("--add-tip", action="store_true", help="Add a tip")
    parser.add_argument("--export", action="store_true", help="Export for RAG")
    parser.add_argument("--stats", action="store_true", help="Show statistics")

    args = parser.parse_args()
    kb = KnowledgeBase()

    if args.stats:
        stats = kb.get_stats()
        print(f"\nðŸ“Š Knowledge Base Statistics")
        print(f"{'='*40}")
        print(f"Total entries: {stats['total_entries']}")
        print(f"\nBy type:")
        for t, count in stats['by_type'].items():
            print(f"  {t}: {count}")
        print(f"\nBy topic:")
        for t, count in sorted(stats['by_topic'].items(), key=lambda x: -x[1]):
            print(f"  {t}: {count}")

    elif args.export:
        path = kb.export_for_rag()
        print(f"âœ… Exported to {path}")
        print(f"Now run: python ingest.py {path} --type knowledge_base")

    elif args.add_qa:
        print("Add a Q&A pair")
        q = input("Question: ")
        a = input("Answer: ")
        topics = input("Topics (comma-separated): ").split(",")
        kb.add_qa(q, a.strip(), topics=[t.strip() for t in topics if t.strip()])
        print("âœ… Added!")

    elif args.add_correction:
        print("Add a correction")
        wrong = input("What was Claude's wrong response? ")
        right = input("What's the correct answer? ")
        topics = input("Topics (comma-separated): ").split(",")
        kb.add_correction(wrong, right, topics=[t.strip() for t in topics if t.strip()])
        print("âœ… Added!")

    elif args.add_tip:
        print("Add a tip")
        tip = input("Tip: ")
        topics = input("Topics (comma-separated): ").split(",")
        kb.add_tip(tip, topics=[t.strip() for t in topics if t.strip()])
        print("âœ… Added!")

    else:
        parser.print_help()
