"""
Main Zoning Analyzer - orchestrates all data sources for full zoning analysis.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .data_sources.pluto import PLUTOClient, SiteInfo
from .data_sources.landmarks import LandmarksClient, LandmarkStatus
from .data_sources.flood_zones import FloodZoneClient, FloodStatus
from .data_sources.tax_maps import TaxMapClient, LotDimensions
from .rules.bulk import BulkCalculator, BulkRegulations
from .rules.use_groups import UseGroupLookup, PermittedUses
from .rules.parking import ParkingCalculator, ParkingRequirements

logger = logging.getLogger(__name__)


@dataclass
class ZoningAnalysis:
    """Complete zoning analysis for a property."""

    # Site info
    address: str
    borough: str
    bbl: Optional[str] = None
    bin: Optional[str] = None

    # Site dimensions
    lot_area: Optional[float] = None
    lot_frontage: Optional[float] = None
    lot_depth: Optional[float] = None

    # Zoning
    zoning_district: Optional[str] = None
    overlay: Optional[str] = None
    special_district: Optional[str] = None

    # Analysis results
    permitted_uses: Optional[PermittedUses] = None
    bulk: Optional[BulkRegulations] = None
    parking: Optional[ParkingRequirements] = None
    landmark_status: Optional[LandmarkStatus] = None
    flood_status: Optional[FloodStatus] = None

    # Building info
    year_built: Optional[int] = None
    building_class: Optional[str] = None
    num_floors: Optional[int] = None

    # Warnings and notes
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # Confidence score (0-100)
    confidence: int = 0

    def to_report(self) -> str:
        """Generate formatted analysis report."""
        lines = []

        # Header
        lines.append("═" * 65)
        lines.append(f"  ZONING ANALYSIS: {self.address}, {self.borough}")
        lines.append("═" * 65)
        lines.append("")

        # Site Information
        lines.append("📍 SITE INFORMATION")
        lines.append(f"   BBL: {self.bbl or 'Unknown'}")
        if self.lot_area:
            lines.append(f"   Lot Area: {self.lot_area:,.0f} SF")
        if self.lot_frontage and self.lot_depth:
            lines.append(f"   Dimensions: {self.lot_frontage:.0f}' × {self.lot_depth:.0f}' (approx)")
        if self.year_built:
            lines.append(f"   Year Built: {self.year_built}")
        if self.building_class:
            lines.append(f"   Building Class: {self.building_class}")
        lines.append("")

        # Zoning District
        lines.append(f"🏗️ ZONING DISTRICT: {self.zoning_district or 'Unknown'}")
        if self.overlay:
            lines.append(f"   Overlay: {self.overlay}")
        if self.special_district:
            lines.append(f"   Special District: {self.special_district}")
        lines.append("")

        # Permitted Uses
        if self.permitted_uses:
            lines.append("✅ PERMITTED USES")
            lines.append(f"   Use Groups Allowed: {self.permitted_uses.use_groups_allowed}")
            if self.permitted_uses.common_uses:
                lines.append("   Common uses include:")
                for use in self.permitted_uses.common_uses[:8]:
                    lines.append(f"     • {use}")
            if self.permitted_uses.special_permit_uses:
                lines.append("   Special Permit required for:")
                for use in self.permitted_uses.special_permit_uses[:5]:
                    lines.append(f"     • {use}")
            lines.append("")

        # Bulk Regulations
        if self.bulk:
            lines.append("📐 BULK REGULATIONS")
            lines.append(f"   Max FAR: {self.bulk.max_far}")
            if self.bulk.max_far_with_bonus:
                lines.append(f"   Max FAR (with bonus): {self.bulk.max_far_with_bonus}")
            if self.bulk.community_facility_far:
                lines.append(f"   Community Facility FAR: {self.bulk.community_facility_far}")
            if self.bulk.max_building_height:
                lines.append(f"   Max Height: {self.bulk.max_building_height} ft")
            if self.bulk.base_height_min and self.bulk.base_height_max:
                lines.append(f"   Street Wall: {self.bulk.base_height_min}-{self.bulk.base_height_max} ft")
            lines.append("   Required Yards:")
            lines.append(f"     • Front: {self.bulk.front_yard or 0} ft")
            lines.append(f"     • Side: {self.bulk.side_yard or 0} ft")
            lines.append(f"     • Rear: {self.bulk.rear_yard or 30} ft")
            if self.bulk.max_lot_coverage:
                lines.append(f"   Max Lot Coverage: {self.bulk.max_lot_coverage}%")
            if self.bulk.open_space_ratio:
                lines.append(f"   Open Space Ratio: {self.bulk.open_space_ratio}")
            if self.bulk.notes:
                for note in self.bulk.notes:
                    lines.append(f"   ⚠️ {note}")
            lines.append("")

        # Parking
        if self.parking:
            lines.append("🚗 PARKING REQUIREMENTS")
            lines.append(f"   {self.parking.to_summary()}")
            lines.append("")

        # Landmarks
        if self.landmark_status:
            lines.append("🏛️ LANDMARK STATUS")
            lines.append(f"   Individual Landmark: {'Yes' if self.landmark_status.is_landmark else 'No'}")
            lines.append(f"   Historic District: {'Yes - ' + self.landmark_status.historic_district if self.landmark_status.historic_district else 'No'}")
            if self.landmark_status.is_landmark or self.landmark_status.historic_district:
                lines.append("   ⚠️ LPC approval required for exterior alterations")
            lines.append("")

        # Flood Zone
        if self.flood_status:
            lines.append("🌊 FLOOD ZONE")
            lines.append(f"   Zone: {self.flood_status.zone}")
            if self.flood_status.zone not in ['X', 'Minimal']:
                lines.append(f"   Base Flood Elevation: {self.flood_status.bfe or 'See FIRM'}")
                lines.append("   ⚠️ Flood insurance may be required")
            lines.append("")

        # Warnings
        if self.warnings:
            lines.append("⚠️ WARNINGS")
            for warning in self.warnings:
                lines.append(f"   • {warning}")
            lines.append("")

        # Notes
        if self.notes:
            lines.append("📝 NOTES")
            for note in self.notes:
                lines.append(f"   • {note}")
            lines.append("")

        # Footer
        lines.append("─" * 65)
        lines.append(f"Confidence: {self.confidence}% | Generated by Greenlight AI")
        lines.append("⚠️ For internal use only. Verify with DOB before filing.")
        lines.append("═" * 65)

        return "\n".join(lines)


class ZoningAnalyzer:
    """Orchestrates full zoning analysis for any NYC address."""

    def __init__(self):
        """Initialize all data source clients."""
        self.pluto = PLUTOClient()
        self.landmarks = LandmarksClient()
        self.flood = FloodZoneClient()
        self.tax_maps = TaxMapClient()
        self.bulk_calc = BulkCalculator()
        self.use_groups = UseGroupLookup()
        self.parking_calc = ParkingCalculator()

    def analyze(self, address: str, borough: str) -> ZoningAnalysis:
        """Run complete zoning analysis for an address.

        Args:
            address: Street address
            borough: NYC borough name

        Returns:
            ZoningAnalysis with all findings
        """
        analysis = ZoningAnalysis(address=address, borough=borough)
        confidence_points = 0
        max_points = 0

        # 1. Get basic site info from PLUTO
        max_points += 30
        try:
            site = self.pluto.lookup(address, borough)
            if site:
                analysis.bbl = site.bbl
                analysis.bin = site.bin
                analysis.lot_area = site.lot_area
                analysis.zoning_district = site.zoning_district
                analysis.overlay = site.overlay
                analysis.special_district = site.special_district
                analysis.year_built = site.year_built
                analysis.building_class = site.building_class
                analysis.num_floors = site.num_floors
                confidence_points += 30
                logger.info(f"PLUTO lookup successful: {site.bbl}")
            else:
                analysis.warnings.append("Could not find property in PLUTO database")
        except Exception as e:
            logger.error(f"PLUTO lookup failed: {e}")
            analysis.warnings.append("PLUTO data unavailable")

        # 2. Get lot dimensions from tax maps
        max_points += 10
        if analysis.bbl:
            try:
                dimensions = self.tax_maps.get_dimensions(analysis.bbl)
                if dimensions:
                    analysis.lot_frontage = dimensions.frontage
                    analysis.lot_depth = dimensions.depth
                    confidence_points += 10
            except Exception as e:
                logger.warning(f"Tax map lookup failed: {e}")

        # 3. Determine permitted uses
        max_points += 20
        if analysis.zoning_district:
            try:
                analysis.permitted_uses = self.use_groups.get_permitted(
                    analysis.zoning_district,
                    analysis.overlay,
                    analysis.special_district,
                )
                confidence_points += 20
            except Exception as e:
                logger.error(f"Use group lookup failed: {e}")
                analysis.warnings.append("Could not determine permitted uses")

        # 4. Calculate bulk regulations
        max_points += 20
        if analysis.zoning_district:
            try:
                analysis.bulk = self.bulk_calc.get_regulations(
                    district=analysis.zoning_district,
                    lot_area=analysis.lot_area,
                    lot_width=analysis.lot_frontage,
                    overlay=analysis.overlay,
                    special_district=analysis.special_district,
                )
                confidence_points += 20
            except Exception as e:
                logger.error(f"Bulk calculation failed: {e}")
                analysis.warnings.append("Could not calculate bulk regulations")

        # 5. Calculate parking requirements (default to residential)
        max_points += 5
        if analysis.zoning_district:
            try:
                # Default parking calc for residential - specific use can be calculated separately
                analysis.parking = self.parking_calc.calculate(
                    district=analysis.zoning_district,
                    use_type="residential",
                    dwelling_units=10,  # Placeholder - actual DUs would come from proposal
                    borough=analysis.borough,
                )
                confidence_points += 5
            except Exception as e:
                logger.warning(f"Parking calculation failed: {e}")

        # 6. Check landmark status
        max_points += 10
        if analysis.bbl:
            try:
                analysis.landmark_status = self.landmarks.check(analysis.bbl)
                confidence_points += 10
                if analysis.landmark_status.is_landmark:
                    analysis.warnings.append("Property is a designated landmark - LPC approval required")
                if analysis.landmark_status.historic_district:
                    analysis.notes.append(f"Located in {analysis.landmark_status.historic_district} Historic District")
            except Exception as e:
                logger.warning(f"Landmark check failed: {e}")

        # 7. Check flood zone
        max_points += 5
        if analysis.bbl:
            try:
                analysis.flood_status = self.flood.check(analysis.bbl)
                confidence_points += 5
                if analysis.flood_status.zone not in ['X', 'Minimal']:
                    analysis.warnings.append(f"Property is in Flood Zone {analysis.flood_status.zone}")
            except Exception as e:
                logger.warning(f"Flood zone check failed: {e}")

        # Calculate overall confidence
        analysis.confidence = int((confidence_points / max_points) * 100) if max_points > 0 else 0

        # Add general notes
        if analysis.special_district:
            analysis.notes.append(f"Special district rules may override base zoning")

        return analysis

    def quick_check(self, address: str, borough: str, proposed_use: str) -> str:
        """Quick check if a use is permitted at an address.

        Args:
            address: Street address
            borough: Borough name
            proposed_use: What the user wants to do (e.g., "restaurant", "gym")

        Returns:
            Simple yes/no answer with explanation
        """
        analysis = self.analyze(address, borough)

        if not analysis.zoning_district:
            return f"❌ Could not find zoning for {address}, {borough}"

        if not analysis.permitted_uses:
            return f"❌ Could not determine permitted uses for {analysis.zoning_district}"

        # Check if use is permitted
        use_lower = proposed_use.lower()
        permitted = analysis.permitted_uses.is_use_permitted(use_lower)

        if permitted == "as_of_right":
            return f"✅ **Yes**, a {proposed_use} is permitted as-of-right at {address}.\n\nZoning: {analysis.zoning_district}\nUse Group: {analysis.permitted_uses.get_use_group(use_lower)}"
        elif permitted == "special_permit":
            return f"⚠️ A {proposed_use} requires a **Special Permit** at {address}.\n\nZoning: {analysis.zoning_district}"
        else:
            return f"❌ **No**, a {proposed_use} is not permitted at {address}.\n\nZoning: {analysis.zoning_district}\nThis use is not allowed in this district."
