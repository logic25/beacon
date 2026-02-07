"""
Flood zone data source - FEMA flood zone status.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# NYC Open Data - Flood Hazard Areas
FLOOD_DATASET = "dq4w-emd3"
BASE_URL = "https://data.cityofnewyork.us/resource"


@dataclass
class FloodStatus:
    """Flood zone status for a property."""

    zone: str = "X"  # X = minimal risk, A/AE/V/VE = flood zones
    bfe: Optional[float] = None  # Base Flood Elevation
    coastal_zone: bool = False
    in_floodplain: bool = False
    notes: Optional[str] = None


class FloodZoneClient:
    """Client for FEMA flood zone data from NYC Open Data."""

    def __init__(self):
        self.session = requests.Session()

    def _query(self, where: str, limit: int = 5) -> list[dict]:
        """Execute flood zone query."""
        url = f"{BASE_URL}/{FLOOD_DATASET}.json"
        params = {"$where": where, "$limit": limit}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Flood zone query failed: {e}")
            return []

    def check(self, bbl: str) -> FloodStatus:
        """Check flood zone status for a BBL.

        Args:
            bbl: Borough-Block-Lot identifier

        Returns:
            FloodStatus with findings
        """
        status = FloodStatus()

        try:
            # Query by BBL
            results = self._query(f"bbl = '{bbl}'", limit=1)

            if results:
                data = results[0]
                status.zone = data.get("fld_zone", "X")
                status.bfe = self._safe_float(data.get("static_bfe"))
                status.in_floodplain = status.zone not in ["X", "AREA OF MINIMAL FLOOD HAZARD"]

                # Check for coastal zones
                if status.zone and status.zone.startswith("V"):
                    status.coastal_zone = True
                    status.notes = "Coastal high hazard area - stricter building requirements apply"

                if status.in_floodplain:
                    status.notes = f"Property in {status.zone} flood zone - flood insurance recommended"

                logger.info(f"Flood zone for {bbl}: {status.zone}")
            else:
                # No results usually means Zone X (minimal risk)
                status.zone = "X"
                status.notes = "Minimal flood hazard"

        except Exception as e:
            logger.warning(f"Flood zone check failed: {e}")
            status.zone = "Unknown"
            status.notes = "Could not determine flood zone"

        return status

    def _safe_float(self, value) -> Optional[float]:
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None
