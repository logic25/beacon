"""
Architectural Plan Reading Capabilities

Claude CAN read architectural/construction plans as images, with some limitations.
This module provides guidance and structured analysis.

CAPABILITIES:
✅ Identify drawing type (floor plan, elevation, section, detail)
✅ Read text labels and annotations
✅ Identify rooms and spaces
✅ Spot obvious issues (missing labels, unclear elements)
✅ Compare to code requirements (general)
✅ Read title blocks and drawing info

LIMITATIONS:
❌ Precise measurements (use CAD/scale for accuracy)
❌ Layer information (can't see hidden layers)
❌ 100% code compliance verification (always verify with PE/RA)
❌ Complex structural analysis
❌ MEP coordination

CONFIDENCE LEVELS:
- Drawing identification: 90%+
- Text/label reading: 85%+ (depends on legibility)
- Room identification: 80%+
- Code compliance: 60-70% (use as preliminary check only)
- Measurements: NOT RELIABLE (always verify)
"""

import base64
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class DrawingType(Enum):
    """Types of architectural drawings."""
    FLOOR_PLAN = "floor_plan"
    SITE_PLAN = "site_plan"
    ELEVATION = "elevation"
    SECTION = "section"
    DETAIL = "detail"
    SCHEDULE = "schedule"
    DIAGRAM = "diagram"
    TITLE_SHEET = "title_sheet"
    UNKNOWN = "unknown"


class ConfidenceLevel(Enum):
    """Confidence levels for analysis."""
    HIGH = "high"       # 85%+ certain
    MEDIUM = "medium"   # 65-85% certain
    LOW = "low"         # Below 65% - needs verification
    UNKNOWN = "unknown"


@dataclass
class PlanAnalysis:
    """Analysis results from reading a plan."""
    drawing_type: DrawingType
    confidence: ConfidenceLevel

    # What we found
    title_block: Optional[dict] = None  # job number, address, sheet number
    rooms_identified: list = None
    labels_read: list = None
    dimensions_found: list = None

    # Potential issues
    issues_found: list = None
    missing_items: list = None

    # Warnings
    warnings: list = None

    def __post_init__(self):
        self.rooms_identified = self.rooms_identified or []
        self.labels_read = self.labels_read or []
        self.dimensions_found = self.dimensions_found or []
        self.issues_found = self.issues_found or []
        self.missing_items = self.missing_items or []
        self.warnings = self.warnings or []

    def to_report(self) -> str:
        """Generate analysis report."""
        lines = [
            f"## Plan Analysis",
            f"**Drawing Type:** {self.drawing_type.value}",
            f"**Confidence:** {self.confidence.value}",
            "",
        ]

        if self.title_block:
            lines.append("### Title Block Info")
            for key, value in self.title_block.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        if self.rooms_identified:
            lines.append("### Rooms/Spaces Identified")
            for room in self.rooms_identified:
                lines.append(f"- {room}")
            lines.append("")

        if self.issues_found:
            lines.append("### ⚠️ Potential Issues")
            for issue in self.issues_found:
                lines.append(f"- {issue}")
            lines.append("")

        if self.missing_items:
            lines.append("### ❓ Possibly Missing")
            for item in self.missing_items:
                lines.append(f"- {item}")
            lines.append("")

        if self.warnings:
            lines.append("### ⚡ Warnings")
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        # Always add disclaimer
        lines.extend([
            "---",
            "**⚠️ Disclaimer:** This is a preliminary AI analysis. Always verify with a licensed PE/RA.",
            "Measurements and code compliance MUST be verified manually.",
        ])

        return "\n".join(lines)


# Analysis prompts for different drawing types
ANALYSIS_PROMPTS = {
    "general": """
Analyze this architectural/construction drawing. Please identify:

1. **Drawing Type**: Is this a floor plan, elevation, section, site plan, detail, or other?

2. **Title Block** (if visible): Job number, address, sheet number, date, architect

3. **Rooms/Spaces**: List all labeled rooms or spaces you can identify

4. **Key Elements**: Note important features like:
   - Stairs and exits
   - Doors and windows
   - Structural elements (columns, beams)
   - Any dimensions shown

5. **Potential Issues**: Flag anything that looks incomplete or unclear:
   - Missing labels
   - Unclear dimensions
   - Inconsistencies

6. **For DOB Review**: Note if you see:
   - Exit signs/paths marked
   - Room areas/occupant loads
   - Fire-rated assemblies noted
   - Accessibility features

Be specific about what you CAN clearly see vs. what you're uncertain about.
""",

    "floor_plan": """
Analyze this floor plan for a DOB filing review. Check for:

1. **Room Labels**: Are all spaces labeled with names and areas (SF)?

2. **Exits**:
   - Are exits clearly marked?
   - Is there a path of egress shown?
   - Door swings correct (out for exits)?

3. **Accessibility**:
   - Accessible route indicated?
   - Accessible bathroom if required?

4. **Dimensions**:
   - Are overall dimensions shown?
   - Room dimensions provided?

5. **Code Compliance Indicators**:
   - Occupancy classification noted?
   - Occupant load calculations?
   - Exit width adequate for occupant load?

6. **Missing Elements**: What should be there but isn't?

Provide confidence level (high/medium/low) for each finding.
""",

    "zoning": """
Analyze this drawing for zoning compliance. Check for:

1. **Setbacks**: Are required yards/setbacks dimensioned?

2. **Height**: Building height clearly indicated?

3. **FAR Calculation**: Is there a zoning calculation table?

4. **Lot Coverage**: Open space/lot coverage shown?

5. **Parking**: Required parking spaces indicated?

6. **Use**: Building use/occupancy type noted?

Flag any potential zoning issues or missing information.
""",
}


def get_plan_reading_prompt(
    drawing_type: Optional[str] = None,
    specific_question: Optional[str] = None,
) -> str:
    """
    Get the appropriate prompt for analyzing a plan.

    Args:
        drawing_type: floor_plan, elevation, zoning, etc.
        specific_question: User's specific question about the plan

    Returns:
        Prompt string for Claude
    """
    base_prompt = ANALYSIS_PROMPTS.get(drawing_type, ANALYSIS_PROMPTS["general"])

    if specific_question:
        base_prompt += f"\n\n**User's specific question:** {specific_question}\n"
        base_prompt += "Please address this question specifically in your analysis."

    return base_prompt


def encode_image_for_claude(image_path: str) -> tuple[str, str]:
    """
    Encode an image file for sending to Claude.

    Returns:
        (base64_data, media_type)
    """
    path = Path(image_path)

    # Determine media type
    suffix = path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    media_type = media_types.get(suffix, "image/png")

    # Read and encode
    with open(path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    return image_data, media_type


# ============================================================================
# CAPABILITIES EXPLANATION (for user questions)
# ============================================================================

CAPABILITIES_EXPLANATION = """
## 🏗️ AI Plan Reading Capabilities

### What I CAN Do Well:
✅ **Identify drawing types** (floor plan, elevation, section) - 90%+ accuracy
✅ **Read text and labels** - 85%+ accuracy (if legible)
✅ **Identify rooms and spaces** - 80%+ accuracy
✅ **Spot obvious issues** (missing labels, unclear elements)
✅ **Read title block info** (job number, address, dates)
✅ **General code compliance check** - preliminary only

### What I CANNOT Do Reliably:
❌ **Precise measurements** - Always verify with scale/CAD
❌ **Hidden layers** - I only see what's visible
❌ **Full code compliance** - Use as preliminary check only
❌ **Structural calculations** - Requires PE review
❌ **MEP coordination** - Too complex for visual analysis

### How to Use This:
1. **Preliminary Review**: I can do a first-pass check before submitting
2. **Spot Check**: "Does this floor plan have all the required labels?"
3. **Learning**: "What type of drawing is this?"
4. **Questions**: "Does this show accessible route?"

### ⚠️ Important:
- All findings should be verified by licensed PE/RA
- Measurements are estimates only
- Code compliance is preliminary, not authoritative
- DOB may still issue objections not caught by AI

### Confidence Levels:
- 🟢 **High**: I'm 85%+ confident
- 🟡 **Medium**: 65-85% confident, verify important items
- 🔴 **Low**: Below 65%, definitely verify
"""


def get_capabilities_response() -> str:
    """Get explanation of plan reading capabilities."""
    return CAPABILITIES_EXPLANATION


# ============================================================================
# Example integration with Claude client
# ============================================================================

def analyze_plan_with_claude(
    client,  # Anthropic client
    image_path: str,
    question: Optional[str] = None,
    drawing_type: Optional[str] = None,
) -> str:
    """
    Analyze an architectural plan using Claude's vision capabilities.

    Args:
        client: Anthropic client instance
        image_path: Path to the plan image (PNG, JPG, etc.)
        question: Specific question about the plan
        drawing_type: Known drawing type for specialized prompts

    Returns:
        Analysis response from Claude
    """
    # Encode image
    image_data, media_type = encode_image_for_claude(image_path)

    # Get appropriate prompt
    prompt = get_plan_reading_prompt(drawing_type, question)

    # Add disclaimer prefix
    system_context = """You are an expert architectural plan reviewer helping with NYC DOB filings.
    Analyze drawings carefully but always note your confidence level.
    Be specific about what you can and cannot determine from the image.
    Always recommend verification by a licensed professional for code compliance."""

    # Call Claude with vision
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  # Haiku is good enough for most plan reading
        max_tokens=2000,
        system=system_context,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    )

    return response.content[0].text


# ============================================================================
# CLI for testing
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Plan reading utilities")
    parser.add_argument("--capabilities", "-c", action="store_true",
                        help="Show capabilities explanation")
    parser.add_argument("--analyze", "-a", help="Analyze a plan image (requires API key)")
    parser.add_argument("--question", "-q", help="Specific question about the plan")

    args = parser.parse_args()

    if args.capabilities:
        print(get_capabilities_response())

    elif args.analyze:
        print("To analyze plans, use this in your bot with an Anthropic client.")
        print("\nExample:")
        print("  from plan_reader import analyze_plan_with_claude")
        print("  result = analyze_plan_with_claude(client, 'floor_plan.png')")
