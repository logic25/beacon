"""
Bulk regulations calculator - FAR, height, setbacks, lot coverage.
Based on NYC Zoning Resolution Articles III (Residential) and IV (Commercial).
"""

import logging
from dataclasses import dataclass
from typing import Optional
import re

logger = logging.getLogger(__name__)


@dataclass
class BulkRegulations:
    """Bulk regulations for a zoning district."""

    district: str

    # Floor Area Ratio
    max_far: float
    max_far_with_bonus: Optional[float] = None
    community_facility_far: Optional[float] = None

    # Height
    base_height_min: Optional[int] = None  # feet
    base_height_max: Optional[int] = None  # feet
    max_building_height: Optional[int] = None  # feet
    sky_exposure_plane: bool = False

    # Setbacks
    front_setback: Optional[int] = None  # feet
    side_setback: Optional[int] = None  # feet
    rear_setback: int = 30  # default 30 feet

    # Lot coverage
    max_lot_coverage: Optional[int] = None  # percentage
    open_space_ratio: Optional[float] = None

    # Yards
    front_yard: Optional[int] = None  # feet
    side_yard: Optional[int] = None  # feet (total for both sides)
    rear_yard: int = 30  # feet

    # Other
    dwelling_units_per_acre: Optional[int] = None
    quality_housing: bool = False
    notes: list[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []

    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [f"Bulk Regulations for {self.district}:"]

        # FAR
        if self.max_far_with_bonus:
            lines.append(f"  FAR: {self.max_far} (up to {self.max_far_with_bonus} with bonus)")
        else:
            lines.append(f"  FAR: {self.max_far}")

        if self.community_facility_far:
            lines.append(f"  Community Facility FAR: {self.community_facility_far}")

        # Height
        if self.max_building_height:
            lines.append(f"  Max Height: {self.max_building_height} ft")
        if self.base_height_min and self.base_height_max:
            lines.append(f"  Street Wall: {self.base_height_min}-{self.base_height_max} ft")

        # Yards
        if self.front_yard:
            lines.append(f"  Front Yard: {self.front_yard} ft")
        if self.side_yard:
            lines.append(f"  Side Yards: {self.side_yard} ft total")
        lines.append(f"  Rear Yard: {self.rear_yard} ft")

        # Lot coverage
        if self.max_lot_coverage:
            lines.append(f"  Max Lot Coverage: {self.max_lot_coverage}%")
        if self.open_space_ratio:
            lines.append(f"  Open Space Ratio: {self.open_space_ratio}")

        # Notes
        for note in self.notes:
            lines.append(f"  ⚠️ {note}")

        return "\n".join(lines)


# Residential district bulk parameters
# Source: ZR Article III, Appendix A
RESIDENTIAL_BULK = {
    # Low density
    "R1": {"far": 0.5, "lot_coverage": 35, "front_yard": 20, "side_yard": 10, "rear_yard": 30, "height": None},
    "R2": {"far": 0.5, "lot_coverage": 40, "front_yard": 15, "side_yard": 5, "rear_yard": 30, "height": None},
    "R3": {"far": 0.5, "lot_coverage": 35, "front_yard": 15, "side_yard": 8, "rear_yard": 30, "height": 35},
    "R4": {"far": 0.75, "lot_coverage": 45, "front_yard": 10, "side_yard": 8, "rear_yard": 30, "height": 35},
    "R5": {"far": 1.25, "lot_coverage": 55, "front_yard": 10, "side_yard": 8, "rear_yard": 30, "height": 40},

    # Medium density
    "R6": {"far": 2.43, "far_bonus": 3.0, "cf_far": 4.8, "height": 70, "osr": 27.5},
    "R7": {"far": 3.44, "far_bonus": 4.0, "cf_far": 6.5, "height": 80, "osr": 15.5},
    "R8": {"far": 6.02, "far_bonus": 7.2, "cf_far": 6.5, "height": 120, "osr": 5.9},

    # High density
    "R9": {"far": 7.52, "far_bonus": 9.0, "cf_far": 10.0, "height": None, "osr": 1.0},
    "R10": {"far": 10.0, "far_bonus": 12.0, "cf_far": 10.0, "height": None, "osr": None},
}

# Commercial district bulk parameters
# Source: ZR Article IV
COMMERCIAL_BULK = {
    "C1": {"far": 2.0, "cf_far": 2.0, "height": None},  # Mapped within R district
    "C2": {"far": 2.0, "cf_far": 2.0, "height": None},  # Mapped within R district
    "C3": {"far": 0.5, "cf_far": 1.0, "height": None},
    "C4": {"far": 3.4, "far_bonus": 4.0, "cf_far": 6.5, "height": None},
    "C5": {"far": 10.0, "far_bonus": 15.0, "cf_far": 10.0, "height": None},
    "C6": {"far": 6.0, "far_bonus": 10.0, "cf_far": 10.0, "height": None},
    "C7": {"far": 2.0, "cf_far": 2.0, "height": None},
    "C8": {"far": 2.0, "cf_far": 2.0, "height": None},
}

# Manufacturing district bulk
MANUFACTURING_BULK = {
    "M1": {"far": 1.0, "cf_far": 2.4, "height": None, "rear_yard": 0},
    "M2": {"far": 2.0, "cf_far": 4.8, "height": None, "rear_yard": 0},
    "M3": {"far": 2.0, "cf_far": 4.8, "height": None, "rear_yard": 0},
}

# Quality Housing contextual districts (suffix A, B, X)
CONTEXTUAL_MODIFIERS = {
    "A": {"quality_housing": True, "street_wall": True},
    "B": {"quality_housing": True, "street_wall": True, "height_limited": True},
    "X": {"lower_density": True},
}


class BulkCalculator:
    """Calculate bulk regulations for zoning districts."""

    def __init__(self):
        self.residential = RESIDENTIAL_BULK
        self.commercial = COMMERCIAL_BULK
        self.manufacturing = MANUFACTURING_BULK

    def _parse_district(self, district: str) -> tuple[str, str, Optional[str]]:
        """Parse district into type, base, and suffix.

        Examples:
            R7A -> (R, R7, A)
            C4-4 -> (C, C4, 4)
            M1-1 -> (M, M1, 1)
        """
        if not district:
            return ("", "", None)

        district = district.upper().strip()

        # Match pattern: type + number + optional suffix
        match = re.match(r'^([RCM])(\d+)([A-Z])?(?:-(\d+))?', district)
        if match:
            district_type = match.group(1)
            number = match.group(2)
            letter_suffix = match.group(3)
            dash_suffix = match.group(4)

            base = f"{district_type}{number}"
            suffix = letter_suffix or dash_suffix

            return (district_type, base, suffix)

        return ("", district, None)

    def get_regulations(
        self,
        district: str,
        lot_area: Optional[float] = None,
        lot_width: Optional[float] = None,
        is_corner: bool = False,
        overlay: Optional[str] = None,
        special_district: Optional[str] = None,
    ) -> BulkRegulations:
        """Get bulk regulations for a district.

        Args:
            district: Zoning district (e.g., "R7A", "C4-4")
            lot_area: Lot area in square feet
            lot_width: Lot width/frontage in feet
            is_corner: Whether lot is a corner lot
            overlay: Commercial overlay if any
            special_district: Special district if any

        Returns:
            BulkRegulations object
        """
        district_type, base, suffix = self._parse_district(district)

        # Start with base regulations
        if district_type == "R":
            regs = self._get_residential(base, suffix)
        elif district_type == "C":
            regs = self._get_commercial(base, suffix)
        elif district_type == "M":
            regs = self._get_manufacturing(base, suffix)
        else:
            # Unknown district type
            logger.warning(f"Unknown district type: {district}")
            regs = BulkRegulations(
                district=district,
                max_far=1.0,
            )
            regs.notes.append("District not recognized - using conservative defaults")
            return regs

        regs.district = district

        # Apply lot-specific adjustments
        if lot_width and lot_width < 18:
            regs.notes.append("Narrow lot (<18ft) - special rules may apply")

        if is_corner:
            regs.notes.append("Corner lot - may have adjusted side yard requirements")

        # Special district note
        if special_district:
            regs.notes.append(f"Special District {special_district} may override these regulations")

        return regs

    def _get_residential(self, base: str, suffix: Optional[str]) -> BulkRegulations:
        """Get residential bulk regulations."""
        params = self.residential.get(base, {})

        if not params:
            # Default for unknown R district
            return BulkRegulations(
                district=base,
                max_far=1.0,
                notes=["District not found in database - verify with DCP"]
            )

        regs = BulkRegulations(
            district=base,
            max_far=params.get("far", 1.0),
            max_far_with_bonus=params.get("far_bonus"),
            community_facility_far=params.get("cf_far"),
            max_building_height=params.get("height"),
            max_lot_coverage=params.get("lot_coverage"),
            open_space_ratio=params.get("osr"),
            front_yard=params.get("front_yard"),
            side_yard=params.get("side_yard"),
            rear_yard=params.get("rear_yard", 30),
        )

        # Apply contextual suffix adjustments
        if suffix in CONTEXTUAL_MODIFIERS:
            mods = CONTEXTUAL_MODIFIERS[suffix]
            regs.quality_housing = mods.get("quality_housing", False)

            if mods.get("street_wall"):
                # Contextual districts have street wall requirements
                if base in ["R6", "R7"]:
                    regs.base_height_min = 40
                    regs.base_height_max = 65
                elif base in ["R8", "R9", "R10"]:
                    regs.base_height_min = 60
                    regs.base_height_max = 85

            if mods.get("height_limited"):
                # B suffix typically limits height
                if base == "R6":
                    regs.max_building_height = 55
                elif base == "R7":
                    regs.max_building_height = 75

            if mods.get("lower_density"):
                # X suffix is typically lower density variant
                if regs.max_far:
                    regs.max_far *= 0.8

        return regs

    def _get_commercial(self, base: str, suffix: Optional[str]) -> BulkRegulations:
        """Get commercial bulk regulations."""
        params = self.commercial.get(base, {})

        if not params:
            return BulkRegulations(
                district=base,
                max_far=2.0,
                notes=["District not found in database - verify with DCP"]
            )

        regs = BulkRegulations(
            district=base,
            max_far=params.get("far", 2.0),
            max_far_with_bonus=params.get("far_bonus"),
            community_facility_far=params.get("cf_far"),
            max_building_height=params.get("height"),
            rear_yard=0,  # Commercial typically no rear yard required
        )

        # Numeric suffix can modify FAR (e.g., C4-4 vs C4-5)
        if suffix and suffix.isdigit():
            suffix_num = int(suffix)
            # Higher numbers generally mean higher density
            if suffix_num >= 5:
                regs.notes.append("High-density commercial variant")
            elif suffix_num <= 2:
                regs.notes.append("Lower-density commercial variant")
                if regs.max_far:
                    regs.max_far *= 0.8

        return regs

    def _get_manufacturing(self, base: str, suffix: Optional[str]) -> BulkRegulations:
        """Get manufacturing bulk regulations."""
        params = self.manufacturing.get(base, {})

        if not params:
            return BulkRegulations(
                district=base,
                max_far=1.0,
                notes=["District not found in database - verify with DCP"]
            )

        regs = BulkRegulations(
            district=base,
            max_far=params.get("far", 1.0),
            community_facility_far=params.get("cf_far"),
            rear_yard=params.get("rear_yard", 0),
        )

        regs.notes.append("Manufacturing district - no residential use permitted")

        return regs

    def calculate_max_building_area(
        self,
        regulations: BulkRegulations,
        lot_area: float,
        use_bonus: bool = False,
    ) -> dict:
        """Calculate maximum building area based on lot and FAR.

        Args:
            regulations: BulkRegulations for the district
            lot_area: Lot area in square feet
            use_bonus: Whether to use bonus FAR (requires IH, etc.)

        Returns:
            Dict with max_zfa, max_floors_estimate, etc.
        """
        far = regulations.max_far
        if use_bonus and regulations.max_far_with_bonus:
            far = regulations.max_far_with_bonus

        max_zfa = lot_area * far

        # Estimate floors based on height limit and typical floor height
        max_floors = None
        if regulations.max_building_height:
            # Assume 10ft residential, 12ft commercial floor-to-floor
            max_floors = regulations.max_building_height // 10

        # Building footprint based on lot coverage
        max_footprint = None
        if regulations.max_lot_coverage:
            max_footprint = lot_area * (regulations.max_lot_coverage / 100)

        return {
            "max_zoning_floor_area": max_zfa,
            "far_used": far,
            "max_floors_estimate": max_floors,
            "max_building_footprint": max_footprint,
            "lot_area": lot_area,
        }
