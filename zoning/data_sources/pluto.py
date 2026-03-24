"""
PLUTO data source - property and zoning info from NYC Open Data.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PLUTO_DATASET = "64uk-42ks"
BASE_URL = "https://data.cityofnewyork.us/resource"


@dataclass
class SiteInfo:
    """Property information from PLUTO."""

    bbl: str
    bin: Optional[str] = None
    address: Optional[str] = None
    borough: Optional[str] = None

    # Zoning
    zoning_district: Optional[str] = None
    overlay: Optional[str] = None
    special_district: Optional[str] = None

    # Lot info
    lot_area: Optional[float] = None
    lot_frontage: Optional[float] = None
    lot_depth: Optional[float] = None

    # Building info
    building_class: Optional[str] = None
    year_built: Optional[int] = None
    num_floors: Optional[int] = None
    num_units: Optional[int] = None


class PLUTOClient:
    """Client for PLUTO data from NYC Open Data."""

    def __init__(self):
        self.session = requests.Session()

    def _query(self, where: str, limit: int = 5) -> list[dict]:
        """Execute PLUTO query."""
        url = f"{BASE_URL}/{PLUTO_DATASET}.json"
        params = {"$where": where, "$limit": limit}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"PLUTO query failed: {e}")
            return []

    def _normalize_address(self, address: str) -> tuple[str, str]:
        """Parse address into house number and street."""
        address = re.sub(r'\s*(apt|unit|#|suite|fl|floor)\.?\s*\w*', '', address, flags=re.IGNORECASE)
        address = address.strip().upper()

        match = re.match(r'^(\d+[\-\d]*[A-Z]?)\s+(.+)$', address)
        if match:
            return match.group(1), match.group(2)
        return "", address

    def lookup(self, address: str, borough: str) -> Optional[SiteInfo]:
        """Look up property by address.

        Args:
            address: Street address
            borough: Borough name

        Returns:
            SiteInfo or None if not found
        """
        house_num, street = self._normalize_address(address)
        borough_upper = borough.upper()

        # Try different query approaches
        queries = [
            f"upper(address) LIKE '%{house_num}%{street[:20]}%' AND upper(borough) = '{borough_upper}'",
            f"upper(address) LIKE '{house_num} {street[:15]}%' AND upper(borough) = '{borough_upper}'",
        ]

        for where in queries:
            results = self._query(where)
            if results:
                return self._parse_result(results[0])

        return None

    def lookup_by_bbl(self, bbl: str) -> Optional[SiteInfo]:
        """Look up property by BBL."""
        results = self._query(f"bbl = '{bbl}'", limit=1)
        if results:
            return self._parse_result(results[0])
        return None

    def _parse_result(self, data: dict) -> SiteInfo:
        """Parse PLUTO result into SiteInfo."""
        return SiteInfo(
            bbl=data.get("bbl", ""),
            bin=data.get("bin"),
            address=data.get("address"),
            borough=data.get("borough"),
            zoning_district=data.get("zonedist1"),
            overlay=data.get("overlay1"),
            special_district=data.get("spdist1"),
            lot_area=self._safe_float(data.get("lotarea")),
            lot_frontage=self._safe_float(data.get("lotfront")),
            lot_depth=self._safe_float(data.get("lotdepth")),
            building_class=data.get("bldgclass"),
            year_built=self._safe_int(data.get("yearbuilt")),
            num_floors=self._safe_int(data.get("numfloors")),
            num_units=self._safe_int(data.get("unitsres")),
        )

    def _safe_float(self, value) -> Optional[float]:
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value) -> Optional[int]:
        try:
            return int(float(value)) if value else None
        except (ValueError, TypeError):
            return None
