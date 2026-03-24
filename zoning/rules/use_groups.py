"""
Use Group lookup - determines what uses are permitted in each zoning district.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PermittedUses:
    """Permitted uses for a zoning district."""

    district: str
    use_groups_allowed: str  # e.g., "1-6" or "1-14"
    common_uses: list[str] = field(default_factory=list)
    special_permit_uses: list[str] = field(default_factory=list)
    prohibited_uses: list[str] = field(default_factory=list)

    # Internal mapping for quick lookups
    _use_map: dict = field(default_factory=dict, repr=False)

    def is_use_permitted(self, use: str) -> str:
        """Check if a specific use is permitted.

        Returns: "as_of_right", "special_permit", or "not_permitted"
        """
        use_lower = use.lower()

        # Check common uses
        for common in self.common_uses:
            if use_lower in common.lower():
                return "as_of_right"

        # Check special permit uses
        for sp in self.special_permit_uses:
            if use_lower in sp.lower():
                return "special_permit"

        # Check prohibited
        for prohibited in self.prohibited_uses:
            if use_lower in prohibited.lower():
                return "not_permitted"

        # Default based on use group range
        return "unknown"

    def get_use_group(self, use: str) -> Optional[str]:
        """Get the Use Group number for a specific use."""
        return self._use_map.get(use.lower())


# Use Group definitions
USE_GROUP_USES = {
    1: ["single-family detached residence"],
    2: ["apartments", "multi-family dwelling", "two-family home", "residential"],
    3: ["school", "college", "university", "hospital", "house of worship", "church", "museum", "library"],
    4: ["medical office", "doctor office", "clinic", "child care", "community center", "ambulatory care"],
    5: ["hotel", "motel", "transient hotel"],
    6: ["restaurant", "cafe", "grocery", "supermarket", "food store", "bakery", "bank", "barber",
        "salon", "dry cleaner", "pharmacy", "florist", "laundromat", "retail"],
    7: ["hardware store", "appliance repair", "paint store", "electrical supply"],
    8: ["gym", "health club", "fitness", "bowling", "skating rink", "movie theater", "billiards"],
    9: ["department store", "furniture store", "clothing store", "antique", "art gallery", "bookstore"],
    10: ["arena", "stadium", "concert hall", "cabaret", "nightclub", "convention center"],
    11: ["custom furniture", "jewelry manufacturing", "musical instrument maker", "artisan"],
    12: ["auto repair", "car repair", "body shop", "carpentry shop", "welding"],
    13: ["marina", "boat repair", "ferry terminal", "dock"],
    14: ["airport", "heliport", "seaplane"],
    15: ["lumber yard", "building materials", "wholesale", "storage", "warehouse"],
    16: ["light manufacturing", "printing", "food processing", "bottling", "clothing manufacturing"],
    17: ["cement", "chemical manufacturing", "foundry", "stone cutting"],
    18: ["asphalt", "petroleum", "incinerator", "heavy industrial"],
}

# District to permitted Use Groups mapping
DISTRICT_USE_GROUPS = {
    # Residential - only UG 1-4
    "R1": (1, 4), "R2": (1, 4), "R3": (1, 4), "R4": (1, 4), "R5": (1, 4),
    "R6": (2, 4), "R7": (2, 4), "R8": (2, 4), "R9": (2, 4), "R10": (2, 4),

    # Commercial - varying ranges
    "C1": (1, 6), "C2": (1, 9), "C3": (1, 6), "C4": (1, 14),
    "C5": (1, 12), "C6": (1, 12), "C7": (1, 14), "C8": (1, 16),

    # Manufacturing
    "M1": (4, 16), "M2": (4, 17), "M3": (4, 18),
}


class UseGroupLookup:
    """Lookup permitted uses by zoning district."""

    def __init__(self):
        self.use_groups = USE_GROUP_USES
        self.district_mapping = DISTRICT_USE_GROUPS

    def _parse_district(self, district: str) -> str:
        """Parse district to base type (R7A -> R7, C4-4 -> C4)."""
        if not district:
            return ""

        # Remove suffix letters and numbers after dash
        import re
        match = re.match(r'^([RCM]\d+)', district.upper())
        return match.group(1) if match else district.upper()

    def get_permitted(
        self,
        district: str,
        overlay: Optional[str] = None,
        special_district: Optional[str] = None,
    ) -> PermittedUses:
        """Get permitted uses for a zoning district.

        Args:
            district: Zoning district (e.g., "R7A", "C4-4")
            overlay: Commercial overlay if any
            special_district: Special district if any

        Returns:
            PermittedUses object
        """
        base_district = self._parse_district(district)

        # Get use group range
        ug_range = self.district_mapping.get(base_district, (1, 4))
        min_ug, max_ug = ug_range

        # Build permitted uses
        permitted = PermittedUses(
            district=district,
            use_groups_allowed=f"{min_ug}-{max_ug}",
        )

        # Populate common uses from allowed Use Groups
        use_map = {}
        for ug in range(min_ug, max_ug + 1):
            uses = self.use_groups.get(ug, [])
            for use in uses:
                permitted.common_uses.append(f"{use} (UG {ug})")
                use_map[use.lower()] = f"UG {ug}"

        permitted._use_map = use_map

        # Add special permit uses (next Use Group up)
        if max_ug < 18:
            next_uses = self.use_groups.get(max_ug + 1, [])
            for use in next_uses[:3]:
                permitted.special_permit_uses.append(use)

        # Add prohibited uses (way outside range)
        if max_ug < 16:
            for use in self.use_groups.get(17, [])[:2]:
                permitted.prohibited_uses.append(use)
            for use in self.use_groups.get(18, [])[:2]:
                permitted.prohibited_uses.append(use)

        # Handle commercial overlay in residential
        if overlay and overlay.startswith("C") and base_district.startswith("R"):
            # C1/C2 overlay adds UG 6
            permitted.common_uses.append("local retail (UG 6 via overlay)")
            permitted.common_uses.append("restaurant (UG 6 via overlay)")
            permitted.use_groups_allowed += f" + {overlay} overlay"

        # Note special district
        if special_district:
            permitted.special_permit_uses.append(
                f"(Special district {special_district} rules may apply)"
            )

        return permitted
