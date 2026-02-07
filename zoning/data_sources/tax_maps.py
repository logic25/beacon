"""
Digital Tax Map data source - lot dimensions.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# NYC Open Data - DOF Digital Tax Map
TAX_MAP_DATASET = "smk3-tmxj"  # Tax lot polygons
BASE_URL = "https://data.cityofnewyork.us/resource"


@dataclass
class LotDimensions:
    """Lot dimensions from tax maps."""

    frontage: Optional[float] = None  # Street frontage in feet
    depth: Optional[float] = None  # Lot depth in feet
    shape: str = "regular"  # regular, irregular, through-lot
    corner_lot: bool = False
    through_lot: bool = False
    notes: Optional[str] = None


class TaxMapClient:
    """Client for DOF Digital Tax Map data."""

    def __init__(self):
        self.session = requests.Session()

    def _query(self, where: str, limit: int = 5) -> list[dict]:
        """Execute tax map query."""
        url = f"{BASE_URL}/{TAX_MAP_DATASET}.json"
        params = {"$where": where, "$limit": limit}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Tax map query failed: {e}")
            return []

    def get_dimensions(self, bbl: str) -> Optional[LotDimensions]:
        """Get lot dimensions for a BBL.

        Args:
            bbl: Borough-Block-Lot identifier

        Returns:
            LotDimensions or None
        """
        try:
            results = self._query(f"bbl = '{bbl}'", limit=1)

            if not results:
                # Try PLUTO as fallback (it has lot_front and lot_depth)
                return self._get_from_pluto(bbl)

            data = results[0]
            dims = LotDimensions(
                frontage=self._safe_float(data.get("lot_front")),
                depth=self._safe_float(data.get("lot_depth")),
            )

            # Determine lot shape
            if data.get("irregular") == "Y":
                dims.shape = "irregular"
            if data.get("corner") == "Y":
                dims.corner_lot = True
                dims.notes = "Corner lot - may have different setback requirements"

            return dims

        except Exception as e:
            logger.warning(f"Tax map lookup failed: {e}")
            return None

    def _get_from_pluto(self, bbl: str) -> Optional[LotDimensions]:
        """Fallback to PLUTO for lot dimensions."""
        from .pluto import PLUTOClient

        try:
            pluto = PLUTOClient()
            site = pluto.lookup_by_bbl(bbl)
            if site and (site.lot_frontage or site.lot_depth):
                return LotDimensions(
                    frontage=site.lot_frontage,
                    depth=site.lot_depth,
                )
        except Exception as e:
            logger.warning(f"PLUTO fallback failed: {e}")

        return None

    def _safe_float(self, value) -> Optional[float]:
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None
