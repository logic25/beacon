"""
Parking requirements calculator.
Based on NYC Zoning Resolution Article I, Chapter 3 and Article II, Chapter 5.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ParkingRequirements:
    """Parking requirements for a development."""

    district: str
    use_type: str

    # Required spaces
    required_spaces: float
    bicycle_spaces: int = 0

    # Calculation details
    ratio: str = ""  # e.g., "1 per 400 sf" or "0.5 per DU"
    basis: str = ""  # What the ratio is based on (DUs, sq ft, seats, etc.)

    # Modifiers
    transit_zone_reduction: bool = False
    reduction_percent: int = 0

    # Notes
    notes: list[str] = field(default_factory=list)
    accessible_spaces: int = 0

    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [f"Parking Requirements for {self.use_type} in {self.district}:"]

        lines.append(f"  Required Spaces: {self.required_spaces:.1f}")
        if self.ratio:
            lines.append(f"  Ratio: {self.ratio}")

        if self.transit_zone_reduction:
            lines.append(f"  Transit Zone Reduction: {self.reduction_percent}%")

        if self.bicycle_spaces > 0:
            lines.append(f"  Bicycle Spaces: {self.bicycle_spaces}")

        if self.accessible_spaces > 0:
            lines.append(f"  Accessible Spaces: {self.accessible_spaces}")

        for note in self.notes:
            lines.append(f"  ⚠️ {note}")

        return "\n".join(lines)


# Parking ratios by use type
# Format: (spaces_per_unit, unit_type, minimum_threshold)
PARKING_RATIOS = {
    # Residential (Use Groups 1-2)
    "residential": {
        # R1-R5: typically 1 per DU
        "low_density": (1.0, "dwelling_unit", 0),
        # R6-R7: varies by transit zone
        "medium_density": (0.5, "dwelling_unit", 0),
        # R8-R10: lower requirements, transit-oriented
        "high_density": (0.4, "dwelling_unit", 0),
    },

    # Community Facility (Use Groups 3-4)
    "hospital": (1.0, "4_beds", 0),
    "school": (1.0, "20_students", 0),
    "house_of_worship": (1.0, "10_seats", 0),
    "college": (1.0, "6_students", 0),
    "medical_office": (1.0, "400_sf", 0),
    "child_care": (1.0, "20_children", 0),

    # Commercial (Use Groups 5-9)
    "hotel": (1.0, "4_rooms", 0),
    "retail": (1.0, "400_sf", 10000),  # Only if > 10,000 sf
    "restaurant": (1.0, "400_sf", 2500),
    "office": (1.0, "400_sf", 10000),
    "grocery": (1.0, "400_sf", 10000),

    # Entertainment (Use Group 8-10)
    "gym": (1.0, "500_sf", 10000),
    "theater": (1.0, "10_seats", 0),
    "bowling": (4.0, "lane", 0),

    # Manufacturing (Use Groups 11-18)
    "manufacturing": (1.0, "1000_sf", 0),
    "warehouse": (1.0, "2000_sf", 0),
}

# Transit zones - reduced or no parking required
TRANSIT_ZONES = {
    "Manhattan Core": {"reduction": 100, "area": "south_of_96th"},
    "Transit Zone": {"reduction": 50, "area": "within_0.5_mile_of_subway"},
    "None": {"reduction": 0, "area": "outside_transit_zone"},
}

# Districts with no parking requirements
NO_PARKING_REQUIRED = [
    "M1-5", "M1-6",  # Manhattan manufacturing
    "C5-1", "C5-2", "C5-3", "C5-4", "C5-5",  # Manhattan commercial
    "C6-4", "C6-5", "C6-6", "C6-7", "C6-8", "C6-9",  # High density commercial
]


class ParkingCalculator:
    """Calculate parking requirements for developments."""

    def __init__(self):
        self.ratios = PARKING_RATIOS
        self.transit_zones = TRANSIT_ZONES

    def _get_district_category(self, district: str) -> str:
        """Determine density category from district."""
        if not district:
            return "medium_density"

        district = district.upper()

        # Residential
        if district.startswith("R"):
            num = int("".join(c for c in district if c.isdigit())[:2])
            if num <= 5:
                return "low_density"
            elif num <= 7:
                return "medium_density"
            else:
                return "high_density"

        # Commercial/Manufacturing generally medium
        return "medium_density"

    def _is_transit_zone(self, district: str, borough: Optional[str] = None) -> tuple[bool, int]:
        """Check if district is in a transit zone.

        Returns: (is_transit_zone, reduction_percent)
        """
        district = district.upper() if district else ""

        # Manhattan Core - no parking required for most uses
        if borough and borough.upper() in ["MANHATTAN", "MN", "1"]:
            # Most of Manhattan is transit zone
            return (True, 50)

        # Check if it's a no-parking-required district
        for no_park in NO_PARKING_REQUIRED:
            if district.startswith(no_park):
                return (True, 100)

        # High density residential typically in transit zones
        if district.startswith("R") and any(d in district for d in ["8", "9", "10"]):
            return (True, 50)

        # High density commercial
        if district.startswith("C") and any(d in district for d in ["5", "6"]):
            return (True, 50)

        return (False, 0)

    def calculate(
        self,
        district: str,
        use_type: str,
        dwelling_units: Optional[int] = None,
        floor_area: Optional[float] = None,
        seats: Optional[int] = None,
        rooms: Optional[int] = None,
        borough: Optional[str] = None,
    ) -> ParkingRequirements:
        """Calculate parking requirements.

        Args:
            district: Zoning district
            use_type: Type of use (residential, retail, office, etc.)
            dwelling_units: Number of dwelling units (residential)
            floor_area: Floor area in square feet
            seats: Number of seats (theaters, etc.)
            rooms: Number of rooms (hotels)
            borough: Borough name for transit zone check

        Returns:
            ParkingRequirements object
        """
        use_lower = use_type.lower()
        reqs = ParkingRequirements(
            district=district,
            use_type=use_type,
            required_spaces=0,
        )

        # Check transit zone
        is_transit, reduction = self._is_transit_zone(district, borough)
        if is_transit:
            reqs.transit_zone_reduction = True
            reqs.reduction_percent = reduction

        # Calculate based on use type
        if "residential" in use_lower or "apartment" in use_lower or "dwelling" in use_lower:
            reqs = self._calc_residential(reqs, district, dwelling_units)

        elif "retail" in use_lower or "store" in use_lower:
            reqs = self._calc_by_area(reqs, "retail", floor_area)

        elif "office" in use_lower:
            reqs = self._calc_by_area(reqs, "office", floor_area)

        elif "restaurant" in use_lower or "cafe" in use_lower:
            reqs = self._calc_by_area(reqs, "restaurant", floor_area)

        elif "hotel" in use_lower or "motel" in use_lower:
            reqs = self._calc_hotel(reqs, rooms)

        elif "theater" in use_lower or "cinema" in use_lower:
            reqs = self._calc_by_seats(reqs, "theater", seats)

        elif "gym" in use_lower or "fitness" in use_lower:
            reqs = self._calc_by_area(reqs, "gym", floor_area)

        elif "warehouse" in use_lower or "storage" in use_lower:
            reqs = self._calc_by_area(reqs, "warehouse", floor_area)

        elif "manufacturing" in use_lower or "industrial" in use_lower:
            reqs = self._calc_by_area(reqs, "manufacturing", floor_area)

        elif "hospital" in use_lower:
            reqs.notes.append("Hospital parking varies - consult ZR 25-00")

        elif "school" in use_lower:
            reqs.notes.append("School parking varies by enrollment - consult ZR 25-00")

        else:
            reqs.notes.append(f"Use type '{use_type}' not found - verify requirements with DCP")
            # Default to commercial ratio
            if floor_area:
                reqs = self._calc_by_area(reqs, "retail", floor_area)

        # Apply transit zone reduction
        if reqs.transit_zone_reduction and reqs.required_spaces > 0:
            original = reqs.required_spaces
            reqs.required_spaces *= (1 - reqs.reduction_percent / 100)
            if reqs.reduction_percent == 100:
                reqs.notes.append(f"Transit zone - no parking required (would be {original:.0f})")

        # Calculate bicycle parking
        reqs.bicycle_spaces = self._calc_bicycle(use_lower, dwelling_units, floor_area)

        # Accessible spaces
        if reqs.required_spaces > 0:
            reqs.accessible_spaces = self._calc_accessible(int(reqs.required_spaces))

        return reqs

    def _calc_residential(
        self,
        reqs: ParkingRequirements,
        district: str,
        dwelling_units: Optional[int],
    ) -> ParkingRequirements:
        """Calculate residential parking."""
        if not dwelling_units:
            reqs.notes.append("Dwelling units not provided - cannot calculate")
            return reqs

        category = self._get_district_category(district)
        ratio_data = self.ratios["residential"].get(category, (0.5, "dwelling_unit", 0))
        ratio, unit, _ = ratio_data

        reqs.required_spaces = dwelling_units * ratio
        reqs.ratio = f"{ratio} per dwelling unit"
        reqs.basis = f"{dwelling_units} dwelling units"

        return reqs

    def _calc_by_area(
        self,
        reqs: ParkingRequirements,
        use_key: str,
        floor_area: Optional[float],
    ) -> ParkingRequirements:
        """Calculate parking based on floor area."""
        if not floor_area:
            reqs.notes.append("Floor area not provided - cannot calculate")
            return reqs

        ratio_data = self.ratios.get(use_key, (1.0, "400_sf", 0))
        spaces_per_unit, unit_str, threshold = ratio_data

        # Parse unit string to get sf amount
        if "_sf" in unit_str:
            sf_per_space = int(unit_str.replace("_sf", ""))
        else:
            sf_per_space = 400  # default

        # Check threshold
        if threshold > 0 and floor_area < threshold:
            reqs.required_spaces = 0
            reqs.notes.append(f"Below {threshold:,} sf threshold - no parking required")
            return reqs

        reqs.required_spaces = (floor_area / sf_per_space) * spaces_per_unit
        reqs.ratio = f"{spaces_per_unit} per {sf_per_space} sf"
        reqs.basis = f"{floor_area:,.0f} sf floor area"

        return reqs

    def _calc_hotel(
        self,
        reqs: ParkingRequirements,
        rooms: Optional[int],
    ) -> ParkingRequirements:
        """Calculate hotel parking."""
        if not rooms:
            reqs.notes.append("Room count not provided - cannot calculate")
            return reqs

        # 1 space per 4 rooms
        reqs.required_spaces = rooms / 4
        reqs.ratio = "1 per 4 rooms"
        reqs.basis = f"{rooms} rooms"

        return reqs

    def _calc_by_seats(
        self,
        reqs: ParkingRequirements,
        use_key: str,
        seats: Optional[int],
    ) -> ParkingRequirements:
        """Calculate parking based on seats."""
        if not seats:
            reqs.notes.append("Seat count not provided - cannot calculate")
            return reqs

        ratio_data = self.ratios.get(use_key, (1.0, "10_seats", 0))
        spaces_per_unit, unit_str, _ = ratio_data

        # Parse unit string
        if "_seats" in unit_str:
            seats_per_space = int(unit_str.replace("_seats", ""))
        else:
            seats_per_space = 10  # default

        reqs.required_spaces = (seats / seats_per_space) * spaces_per_unit
        reqs.ratio = f"{spaces_per_unit} per {seats_per_space} seats"
        reqs.basis = f"{seats} seats"

        return reqs

    def _calc_bicycle(
        self,
        use_type: str,
        dwelling_units: Optional[int],
        floor_area: Optional[float],
    ) -> int:
        """Calculate bicycle parking requirement (Local Law 51 of 2020)."""
        # Residential: 1 per DU
        if "residential" in use_type or "apartment" in use_type:
            if dwelling_units:
                return dwelling_units

        # Commercial: 1 per 5,000 sf, min 3
        if floor_area and floor_area > 10000:
            spaces = max(3, int(floor_area / 5000))
            return spaces

        return 0

    def _calc_accessible(self, total_spaces: int) -> int:
        """Calculate accessible parking spaces required."""
        if total_spaces <= 0:
            return 0
        elif total_spaces <= 25:
            return 1
        elif total_spaces <= 50:
            return 2
        elif total_spaces <= 75:
            return 3
        elif total_spaces <= 100:
            return 4
        elif total_spaces <= 150:
            return 5
        elif total_spaces <= 200:
            return 6
        elif total_spaces <= 300:
            return 7
        elif total_spaces <= 400:
            return 8
        elif total_spaces <= 500:
            return 9
        else:
            # 2% of total for 501+
            return int(total_spaces * 0.02)
