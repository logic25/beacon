"""
NYC Open Data API client for real-time property lookups.
Provides access to DOB violations, permits, zoning, and more.

Uses the Socrata Open Data API (SODA) - no API key required for basic usage.
For higher rate limits, get a free app token at: https://data.cityofnewyork.us/
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import requests

from config import Settings, get_settings

logger = logging.getLogger(__name__)

# NYC Open Data (Socrata) dataset IDs
DATASETS = {
    "dob_violations": "3h2n-5cm9",      # DOB Violations
    "dob_ecb_violations": "6bgk-3dad",  # DOB ECB Violations
    "dob_permits": "ipu4-2vj7",         # DOB Permits Issued
    "dob_jobs": "ic3t-wcy2",            # DOB Job Application Filings
    "dob_complaints": "eabe-havv",      # DOB Complaints Received
    "hpd_violations": "wvxf-dwi5",      # HPD Violations
    "pluto": "64uk-42ks",               # PLUTO (Property/Zoning)
    "dob_now_permits": "rbx6-tga4",     # DOB NOW Permits
}

BASE_URL = "https://data.cityofnewyork.us/resource"


@dataclass
class PropertyInfo:
    """Aggregated property information from multiple sources."""

    address: str
    borough: str
    bbl: Optional[str] = None
    bin: Optional[str] = None

    # Zoning info from PLUTO
    zoning_district: Optional[str] = None
    overlay: Optional[str] = None
    land_use: Optional[str] = None
    building_class: Optional[str] = None
    num_floors: Optional[int] = None
    year_built: Optional[int] = None
    lot_area: Optional[float] = None

    # Violation counts
    active_dob_violations: int = 0
    active_ecb_violations: int = 0
    active_hpd_violations: int = 0

    # Recent activity
    recent_permits: list[dict] = field(default_factory=list)
    recent_violations: list[dict] = field(default_factory=list)
    open_complaints: list[dict] = field(default_factory=list)

    # Raw data for detailed queries
    raw_data: dict = field(default_factory=dict)

    def to_context_string(self) -> str:
        """Format property info as context for the LLM."""
        lines = [
            f"\U0001f4cd *Property: {self.address}, {self.borough}*",
            f"BBL: {self.bbl or 'Unknown'} | BIN: {self.bin or 'Unknown'}",
        ]

        if self.zoning_district:
            zoning = self.zoning_district
            if self.overlay:
                zoning += f" / {self.overlay}"
            lines.append(f"Zoning: {zoning}")

        if self.year_built:
            lines.append(f"Year Built: {self.year_built} | Floors: {self.num_floors or 'Unknown'}")

        if self.building_class:
            lines.append(f"Building Class: {self.building_class}")

        if self.lot_area:
            lines.append(f"Lot Area: {self.lot_area:,.0f} SF")

        # Violation summary
        total_violations = (
            self.active_dob_violations +
            self.active_ecb_violations +
            self.active_hpd_violations
        )
        if total_violations > 0:
            lines.append(f"\n\u26a0\ufe0f *Active Violations: {total_violations}*")
            if self.active_dob_violations:
                lines.append(f"  - DOB: {self.active_dob_violations}")
            if self.active_ecb_violations:
                lines.append(f"  - ECB: {self.active_ecb_violations}")
            if self.active_hpd_violations:
                lines.append(f"  - HPD: {self.active_hpd_violations}")
        else:
            lines.append(f"\n\u2705 No active violations")

        # Recent violations detail
        if self.recent_violations:
            lines.append(f"\n\U0001f4cb *Recent Violations:*")
            for v in self.recent_violations[:5]:
                desc = v.get("description", "No description")[:80]
                date = v.get("issue_date", "Unknown date")
                vtype = v.get("type", "")
                lines.append(f"  \u2022 [{vtype}] {date}: {desc}")

        # Recent permits
        if self.recent_permits:
            lines.append(f"\n\U0001f528 *Recent Permits:*")
            for p in self.recent_permits[:5]:
                job_type = p.get("job_type", "Unknown")
                desc = p.get("job_description", "No description")[:60]
                date = p.get("issuance_date", "")
                lines.append(f"  \u2022 {job_type}: {desc}" + (f" ({date})" if date else ""))

        # Open complaints
        if self.open_complaints:
            lines.append(f"\n\U0001f4de *Open Complaints: {len(self.open_complaints)}*")
            for c in self.open_complaints[:3]:
                desc = c.get("complaint_category", "Unknown")
                lines.append(f"  \u2022 {desc}")

        return "\n".join(lines)


class NYCOpenDataClient:
    """Client for NYC Open Data API queries."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the client.

        Args:
            settings: Application settings (optional app token for higher rate limits)
        """
        self.settings = settings or get_settings()
        self.session = requests.Session()

        # Add app token if configured (increases rate limit from 1000 to 10000/hour)
        if hasattr(self.settings, 'nyc_open_data_token') and self.settings.nyc_open_data_token:
            self.session.headers["X-App-Token"] = self.settings.nyc_open_data_token

    def _query(
        self,
        dataset_id: str,
        where: Optional[str] = None,
        select: Optional[str] = None,
        order: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Execute a SODA query.

        Args:
            dataset_id: The Socrata dataset ID
            where: SoQL WHERE clause
            select: SoQL SELECT clause
            order: SoQL ORDER BY clause
            limit: Maximum results to return

        Returns:
            List of result dictionaries
        """
        url = f"{BASE_URL}/{dataset_id}.json"

        params = {"$limit": limit}
        if where:
            params["$where"] = where
        if select:
            params["$select"] = select
        if order:
            params["$order"] = order

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"NYC Open Data query failed: {e}")
            return []

    # Street abbreviation mappings for address normalization
    STREET_ABBREVS = {
        "AVE": "AVENUE", "ST": "STREET", "BLVD": "BOULEVARD",
        "RD": "ROAD", "PL": "PLACE", "DR": "DRIVE", "LN": "LANE",
        "CT": "COURT", "PKWY": "PARKWAY", "HWY": "HIGHWAY",
        "CIR": "CIRCLE", "TER": "TERRACE", "EXPY": "EXPRESSWAY",
    }
    STREET_FULL_TO_ABBREV = {v: k for k, v in STREET_ABBREVS.items()}

    def _normalize_address(self, address: str) -> tuple[str, str]:
        """Parse address into house number and street name."""
        address = re.sub(r'\s*(apt|unit|#|suite|fl|floor)\.?\s*\w*', '', address, flags=re.IGNORECASE)
        address = address.strip().upper()

        match = re.match(r'^(\d+[\-\d]*[A-Z]?)\s+(.+)$', address)
        if match:
            return match.group(1), match.group(2)

        return "", address

    def _street_variants(self, street: str) -> list[str]:
        """Generate street name variants (abbreviated and full)."""
        street = street.upper().strip()
        variants = [street]

        # Try expanding abbreviation: AVE -> AVENUE
        for abbrev, full in self.STREET_ABBREVS.items():
            pattern = r'\b' + abbrev + r'\b'
            if re.search(pattern, street):
                variants.append(re.sub(pattern, full, street))
                break

        # Try abbreviating: AVENUE -> AVE
        for full, abbrev in self.STREET_FULL_TO_ABBREV.items():
            pattern = r'\b' + full + r'\b'
            if re.search(pattern, street):
                variants.append(re.sub(pattern, abbrev, street))
                break

        # Also try just the core street name (first 15 chars) for LIKE matching
        core = re.sub(r'\b(STREET|AVENUE|BOULEVARD|ROAD|PLACE|DRIVE|LANE|COURT|AVE|ST|BLVD|RD|PL|DR|LN|CT)\b', '', street).strip()
        if core and core != street:
            variants.append(core)

        return variants

    def _get_borough_code(self, borough: str) -> str:
        """Convert borough name to code."""
        borough_map = {
            "MANHATTAN": "1", "MN": "1", "NEW YORK": "1",
            "BRONX": "2", "BX": "2", "THE BRONX": "2",
            "BROOKLYN": "3", "BK": "3", "KINGS": "3",
            "QUEENS": "4", "QN": "4",
            "STATEN ISLAND": "5", "SI": "5", "RICHMOND": "5",
        }
        return borough_map.get(borough.upper().strip(), "")

    # PLUTO borough values can be full name OR abbreviation depending on dataset version
    BOROUGH_VARIANTS = {
        "MANHATTAN": ["MANHATTAN", "MN", "1"],
        "BRONX": ["BRONX", "BX", "2"],
        "BROOKLYN": ["BROOKLYN", "BK", "3"],
        "QUEENS": ["QUEENS", "QN", "4"],
        "STATEN ISLAND": ["STATEN ISLAND", "SI", "5"],
    }

    def lookup_pluto(self, address: str, borough: str) -> Optional[dict]:
        """Look up property in PLUTO dataset."""
        house_num, street = self._normalize_address(address)
        borough_upper = borough.upper().strip()

        # Get all possible borough values for the query
        boro_variants = self.BOROUGH_VARIANTS.get(borough_upper, [borough_upper])

        # Try each street name variant x borough variant
        for variant in self._street_variants(street):
            for boro in boro_variants:
                where_clauses = [
                    f"upper(address) LIKE '{house_num} {variant[:20]}%' AND upper(borough) = '{boro}'",
                    f"upper(address) LIKE '%{house_num}%{variant[:15]}%' AND upper(borough) = '{boro}'",
                ]
                for where in where_clauses:
                    results = self._query(DATASETS["pluto"], where=where, limit=5)
                    if results:
                        logger.info(f"PLUTO match: variant={variant}, borough={boro}")
                        return results[0]

        logger.warning(f"No PLUTO match for {house_num} {street}, {borough}")
        return None

    def get_dob_violations(
        self,
        bin_number: Optional[str] = None,
        bbl: Optional[str] = None,
        address: Optional[str] = None,
        borough: Optional[str] = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Get DOB violations for a property.

        Args:
            bin_number: Building Identification Number
            bbl: Borough-Block-Lot
            address: Street address (if no BIN/BBL)
            borough: Borough name (required with address)
            active_only: Only return active/open violations

        Returns:
            List of violation records
        """
        conditions = []

        if bin_number:
            conditions.append(f"bin = '{bin_number}'")
        elif bbl:
            conditions.append(f"bbl = '{bbl}'")
        elif address and borough:
            house_num, street = self._normalize_address(address)
            conditions.append(f"upper(house_number) = '{house_num}'")
            conditions.append(f"upper(street) LIKE '%{street[:15]}%'")
            boro_code = self._get_borough_code(borough)
            if boro_code:
                conditions.append(f"boro = '{boro_code}'")
        else:
            return []

        if active_only:
            conditions.append("violation_status != 'DISMISSED'")
            conditions.append("disposition_date IS NULL")

        where = " AND ".join(conditions)

        return self._query(
            DATASETS["dob_violations"],
            where=where,
            order="issue_date DESC",
            limit=50,
        )

    def get_ecb_violations(
        self,
        bin_number: Optional[str] = None,
        bbl: Optional[str] = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Get ECB violations for a property."""
        conditions = []

        if bin_number:
            conditions.append(f"bin = '{bin_number}'")
        elif bbl:
            conditions.append(f"bbl = '{bbl}'")
        else:
            return []

        if active_only:
            conditions.append("ecb_violation_status != 'RESOLVE'")

        where = " AND ".join(conditions)

        return self._query(
            DATASETS["dob_ecb_violations"],
            where=where,
            order="issue_date DESC",
            limit=50,
        )

    def get_hpd_violations(
        self,
        bbl: Optional[str] = None,
        address: Optional[str] = None,
        borough: Optional[str] = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Get HPD violations for a property."""
        conditions = []

        if bbl:
            conditions.append(f"bbl = '{bbl}'")
        elif address and borough:
            house_num, street = self._normalize_address(address)
            conditions.append(f"upper(housenumber) LIKE '%{house_num}%'")
            conditions.append(f"upper(streetname) LIKE '%{street[:15]}%'")
            conditions.append(f"upper(boro) = '{borough.upper()}'")
        else:
            return []

        if active_only:
            conditions.append("violationstatus = 'Open'")

        where = " AND ".join(conditions)

        return self._query(
            DATASETS["hpd_violations"],
            where=where,
            order="inspectiondate DESC",
            limit=50,
        )

    def get_dob_permits(
        self,
        bin_number: Optional[str] = None,
        bbl: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get recent DOB permits for a property."""
        conditions = []

        if bin_number:
            conditions.append(f"bin__ = '{bin_number}'")
        elif bbl:
            conditions.append(f"bbl = '{bbl}'")
        else:
            return []

        where = " AND ".join(conditions)

        return self._query(
            DATASETS["dob_permits"],
            where=where,
            order="issuance_date DESC",
            limit=limit,
        )

    def get_dob_complaints(
        self,
        bin_number: Optional[str] = None,
        bbl: Optional[str] = None,
        open_only: bool = True,
    ) -> list[dict]:
        """Get DOB complaints for a property."""
        conditions = []

        if bin_number:
            conditions.append(f"bin = '{bin_number}'")
        elif bbl:
            # BBL isn't directly in complaints, would need join
            return []
        else:
            return []

        if open_only:
            conditions.append("status != 'CLOSED'")

        where = " AND ".join(conditions)

        return self._query(
            DATASETS["dob_complaints"],
            where=where,
            order="date_entered DESC",
            limit=20,
        )

    def get_property_info(self, address: str, borough: str) -> PropertyInfo:
        """Get comprehensive property information.

        Args:
            address: Street address
            borough: Borough name

        Returns:
            PropertyInfo with all available data
        """
        info = PropertyInfo(address=address, borough=borough)

        # Start with PLUTO lookup
        pluto = self.lookup_pluto(address, borough)
        if pluto:
            info.bbl = pluto.get("bbl")
            info.bin = pluto.get("bin")
            info.zoning_district = pluto.get("zonedist1")
            info.overlay = pluto.get("overlay1")
            info.land_use = pluto.get("landuse")
            info.building_class = pluto.get("bldgclass")
            info.num_floors = self._safe_int(pluto.get("numfloors"))
            info.year_built = self._safe_int(pluto.get("yearbuilt"))
            info.lot_area = self._safe_float(pluto.get("lotarea"))
            info.raw_data["pluto"] = pluto

            logger.info(f"Found PLUTO data for {address}: BBL={info.bbl}, BIN={info.bin}")
        else:
            logger.warning(f"No PLUTO data found for {address}, {borough}")

        # Get violations if we have identifiers
        if info.bin or info.bbl:
            # DOB violations
            dob_violations = self.get_dob_violations(
                bin_number=info.bin,
                bbl=info.bbl,
                active_only=True,
            )
            info.active_dob_violations = len(dob_violations)
            info.recent_violations.extend([
                {
                    "type": "DOB",
                    "description": v.get("description", ""),
                    "issue_date": v.get("issue_date", "")[:10] if v.get("issue_date") else "",
                    "violation_type": v.get("violation_type", ""),
                }
                for v in dob_violations[:10]
            ])
            info.raw_data["dob_violations"] = dob_violations

            # ECB violations
            ecb_violations = self.get_ecb_violations(
                bin_number=info.bin,
                bbl=info.bbl,
                active_only=True,
            )
            info.active_ecb_violations = len(ecb_violations)
            info.recent_violations.extend([
                {
                    "type": "ECB",
                    "description": v.get("violation_description", ""),
                    "issue_date": v.get("issue_date", "")[:10] if v.get("issue_date") else "",
                    "violation_type": v.get("violation_type", ""),
                }
                for v in ecb_violations[:10]
            ])
            info.raw_data["ecb_violations"] = ecb_violations

            # HPD violations (residential)
            if info.building_class and info.building_class[0] in ['A', 'B', 'C', 'D', 'S']:
                hpd_violations = self.get_hpd_violations(bbl=info.bbl, active_only=True)
                info.active_hpd_violations = len(hpd_violations)
                info.raw_data["hpd_violations"] = hpd_violations

            # Permits
            permits = self.get_dob_permits(bin_number=info.bin, bbl=info.bbl)
            info.recent_permits = [
                {
                    "job_type": p.get("job_type", ""),
                    "job_description": p.get("job_description", ""),
                    "issuance_date": p.get("issuance_date", "")[:10] if p.get("issuance_date") else "",
                }
                for p in permits[:10]
            ]
            info.raw_data["permits"] = permits

            # Complaints
            if info.bin:
                complaints = self.get_dob_complaints(bin_number=info.bin, open_only=True)
                info.open_complaints = [
                    {
                        "complaint_category": c.get("complaint_category", ""),
                        "status": c.get("status", ""),
                        "date_entered": c.get("date_entered", ""),
                    }
                    for c in complaints
                ]
                info.raw_data["complaints"] = complaints

        return info

    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert to int."""
        try:
            return int(float(value)) if value else None
        except (ValueError, TypeError):
            return None

    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert to float."""
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None


def extract_address_from_query(query: str) -> Optional[tuple[str, str]]:
    """Try to extract an address and borough from a user query.

    Args:
        query: User's question text

    Returns:
        Tuple of (address, borough) or None if not found
    """
    query_upper = query.upper()

    # Detect borough
    borough = None
    borough_patterns = [
        (r'\bMANHATTAN\b', 'Manhattan'),
        (r'\bBRONX\b', 'Bronx'),
        (r'\bBROOKLYN\b', 'Brooklyn'),
        (r'\bQUEENS\b', 'Queens'),
        (r'\bSTATEN\s*ISLAND\b', 'Staten Island'),
    ]

    for pattern, boro_name in borough_patterns:
        if re.search(pattern, query_upper):
            borough = boro_name
            break

    if not borough:
        return None

    # Try to find an address pattern
    # Common patterns: "123 Main Street", "456 W 42nd St"
    address_pattern = r'\b(\d+[\-\d]*[A-Z]?)\s+((?:EAST|WEST|NORTH|SOUTH|E\.?|W\.?|N\.?|S\.?)?\s*\d*(?:ST|ND|RD|TH)?\s*(?:STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|PLACE|PL|DRIVE|DR|LANE|LN|WAY|COURT|CT)[A-Z]*)'

    match = re.search(address_pattern, query_upper)
    if match:
        address = f"{match.group(1)} {match.group(2)}"
        return address, borough

    return None
