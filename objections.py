"""
DOB Objections Knowledge Base

Provides:
1. Common objections by filing type
2. Suggested resolutions
3. Team tips and learnings
4. Capture new objections from team
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data" / "common_objections.json"


@dataclass
class Objection:
    """A DOB objection record."""
    code: str
    category: str
    objection: str
    code_reference: str
    typical_resolution: str
    frequency: str  # high, medium, low
    notes: Optional[str] = None
    filing_type: Optional[str] = None


class ObjectionsKB:
    """Knowledge base for DOB objections."""

    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        """Load objections data."""
        if DATA_FILE.exists():
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        return {}

    def _save(self):
        """Save objections data."""
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump(self.data, f, indent=2)

    def get_objections_for_filing(self, filing_type: str) -> list[Objection]:
        """
        Get common objections for a filing type.

        Args:
            filing_type: ALT1, ALT2, ALT3, NB, DM, SIGN, PAA, etc.

        Returns:
            List of Objection objects
        """
        filing_type = filing_type.upper().replace(" ", "").replace("-", "")

        # Handle variations
        type_map = {
            "ALT1": "ALT1", "ALTERATION1": "ALT1", "ALTERATIONTYPE1": "ALT1",
            "ALT2": "ALT2", "ALTERATION2": "ALT2", "ALTERATIONTYPE2": "ALT2",
            "ALT3": "ALT3", "ALTERATION3": "ALT3", "ALTERATIONTYPE3": "ALT3",
            "NB": "NB", "NEWBUILDING": "NB",
            "DM": "DM", "DEMO": "DM", "DEMOLITION": "DM",
            "SIGN": "SIGN",
            "PAA": "PAA", "POSTAPPROVALAMENDMENT": "PAA",
        }

        normalized = type_map.get(filing_type, filing_type)

        if normalized not in self.data:
            return []

        filing_data = self.data[normalized]
        objections = []

        for obj_data in filing_data.get("common_objections", []):
            objections.append(Objection(
                filing_type=normalized,
                **obj_data
            ))

        return objections

    def get_objections_by_category(self, category: str) -> list[Objection]:
        """
        Get objections by category across all filing types.

        Args:
            category: egress, structural, zoning, sprinkler, etc.

        Returns:
            List of Objection objects
        """
        category = category.lower()
        objections = []

        for filing_type, filing_data in self.data.items():
            if filing_type.startswith("_"):
                continue

            for obj_data in filing_data.get("common_objections", []):
                if obj_data.get("category", "").lower() == category:
                    objections.append(Objection(
                        filing_type=filing_type,
                        **obj_data
                    ))

        return objections

    def search_objections(self, query: str) -> list[Objection]:
        """
        Search objections by keyword.

        Args:
            query: Search term

        Returns:
            List of matching Objection objects
        """
        query = query.lower()
        results = []

        for filing_type, filing_data in self.data.items():
            if filing_type.startswith("_"):
                continue

            for obj_data in filing_data.get("common_objections", []):
                # Search in objection text, resolution, and code reference
                searchable = " ".join([
                    obj_data.get("objection", ""),
                    obj_data.get("typical_resolution", ""),
                    obj_data.get("code_reference", ""),
                    obj_data.get("category", ""),
                    obj_data.get("notes", "") or "",
                ]).lower()

                if query in searchable:
                    results.append(Objection(
                        filing_type=filing_type,
                        **obj_data
                    ))

        return results

    def add_objection(
        self,
        filing_type: str,
        objection: str,
        resolution: str,
        category: str,
        code_reference: str = "",
        notes: str = "",
    ):
        """
        Add a new objection learned from team experience.

        Args:
            filing_type: ALT1, ALT2, etc.
            objection: The objection text
            resolution: How it was resolved
            category: Category (egress, zoning, etc.)
            code_reference: Code section if known
            notes: Additional notes
        """
        filing_type = filing_type.upper()

        if filing_type not in self.data:
            self.data[filing_type] = {
                "description": f"{filing_type} filings",
                "common_objections": []
            }

        # Generate code
        existing = self.data[filing_type].get("common_objections", [])
        next_num = len(existing) + 1
        code = f"OBJ-{filing_type}-{next_num:03d}"

        new_objection = {
            "code": code,
            "category": category,
            "objection": objection,
            "code_reference": code_reference,
            "typical_resolution": resolution,
            "frequency": "new",  # Mark as newly added
            "notes": notes,
            "added_date": datetime.now().isoformat(),
        }

        self.data[filing_type]["common_objections"].append(new_objection)
        self._save()

        logger.info(f"Added new objection {code} for {filing_type}")
        return code

    def get_tips(self, category: str = "general") -> list[str]:
        """Get tips for a category."""
        tips_data = self.data.get("_tips", {})
        return tips_data.get(category, tips_data.get("general", []))

    def format_for_chat(self, objections: list[Objection]) -> str:
        """Format objections for chat response."""
        if not objections:
            return "No common objections found for this filing type."

        lines = []
        for obj in objections:
            freq_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢", "new": "🆕"}.get(
                obj.frequency, "⚪"
            )

            lines.append(f"\n{freq_emoji} **{obj.category.upper()}**: {obj.objection}")
            lines.append(f"   📖 Code: {obj.code_reference}")
            lines.append(f"   ✅ Resolution: {obj.typical_resolution}")
            if obj.notes:
                lines.append(f"   💡 Note: {obj.notes}")

        return "\n".join(lines)


def get_objections_response(filing_type: str) -> str:
    """
    Get a formatted response about common objections for a filing type.

    For use in the chat bot.
    """
    kb = ObjectionsKB()
    objections = kb.get_objections_for_filing(filing_type)

    if not objections:
        return f"I don't have specific objection data for {filing_type} filings yet. Want to add some from your experience?"

    # Group by frequency
    high = [o for o in objections if o.frequency == "high"]
    medium = [o for o in objections if o.frequency == "medium"]
    low = [o for o in objections if o.frequency == "low"]

    response = f"## Common Objections for {filing_type} Filings\n"

    if high:
        response += "\n### 🔴 Most Common (expect these)\n"
        response += kb.format_for_chat(high)

    if medium:
        response += "\n\n### 🟡 Sometimes (depends on scope)\n"
        response += kb.format_for_chat(medium)

    if low:
        response += "\n\n### 🟢 Less Common\n"
        response += kb.format_for_chat(low)

    # Add tips
    tips = kb.get_tips("plan_exam")
    if tips:
        response += "\n\n### 💡 Tips\n"
        for tip in tips[:3]:
            response += f"• {tip}\n"

    return response


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Objections knowledge base")
    parser.add_argument("--filing", "-f", help="Get objections for filing type")
    parser.add_argument("--search", "-s", help="Search objections")
    parser.add_argument("--category", "-c", help="Get by category")
    parser.add_argument("--add", action="store_true", help="Add new objection (interactive)")

    args = parser.parse_args()

    kb = ObjectionsKB()

    if args.filing:
        print(get_objections_response(args.filing))

    elif args.search:
        results = kb.search_objections(args.search)
        print(f"\n🔍 Found {len(results)} objections matching '{args.search}':\n")
        print(kb.format_for_chat(results))

    elif args.category:
        results = kb.get_objections_by_category(args.category)
        print(f"\n📁 {len(results)} objections in category '{args.category}':\n")
        print(kb.format_for_chat(results))

    elif args.add:
        print("\n➕ Add New Objection")
        filing = input("Filing type (ALT1, ALT2, NB, etc.): ")
        objection = input("Objection text: ")
        resolution = input("How was it resolved: ")
        category = input("Category (egress, zoning, sprinkler, etc.): ")
        code_ref = input("Code reference (optional): ")
        notes = input("Notes (optional): ")

        code = kb.add_objection(filing, objection, resolution, category, code_ref, notes)
        print(f"\n✅ Added as {code}")

    else:
        # Show summary
        print("\n📋 Objections Knowledge Base Summary:\n")
        for filing_type, data in kb.data.items():
            if filing_type.startswith("_"):
                continue
            count = len(data.get("common_objections", []))
            print(f"   {filing_type}: {count} objections")
