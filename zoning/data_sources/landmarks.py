"""
LPC Landmarks data source - landmark and historic district status.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# NYC Open Data datasets
LANDMARKS_DATASET = "buis-pvji"  # Individual Landmarks
HISTORIC_DISTRICTS_DATASET = "vk56-w6f9"  # Historic Districts
BASE_URL = "https://data.cityofnewyork.us/resource"


@dataclass
class LandmarkStatus:
    """Landmark and historic district status for a property."""

    is_landmark: bool = False
    landmark_name: Optional[str] = None
    designation_date: Optional[str] = None

    historic_district: Optional[str] = None
    district_designation_date: Optional[str] = None

    lpc_notes: Optional[str] = None


class LandmarksClient:
    """Client for LPC landmark data from NYC Open Data."""

    def __init__(self):
        self.session = requests.Session()

    def _query(self, dataset: str, where: str, limit: int = 5) -> list[dict]:
        """Execute query against a dataset."""
        url = f"{BASE_URL}/{dataset}.json"
        params = {"$where": where, "$limit": limit}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Landmarks query failed: {e}")
            return []

    def check(self, bbl: str) -> LandmarkStatus:
        """Check landmark and historic district status for a BBL.

        Args:
            bbl: Borough-Block-Lot identifier

        Returns:
            LandmarkStatus with findings
        """
        status = LandmarkStatus()

        # Check individual landmarks
        try:
            # Try querying by BBL or BIN
            results = self._query(
                LANDMARKS_DATASET,
                f"bbl = '{bbl}' OR bin_number = '{bbl}'",
                limit=1,
            )
            if results:
                status.is_landmark = True
                status.landmark_name = results[0].get("landmark_name", "")
                status.designation_date = results[0].get("date_designated", "")
                logger.info(f"Found landmark: {status.landmark_name}")
        except Exception as e:
            logger.warning(f"Individual landmark check failed: {e}")

        # Check historic districts
        try:
            results = self._query(
                HISTORIC_DISTRICTS_DATASET,
                f"bbl = '{bbl}'",
                limit=1,
            )
            if results:
                status.historic_district = results[0].get("hist_dist", "")
                status.district_designation_date = results[0].get("date_designated", "")
                logger.info(f"Found historic district: {status.historic_district}")
        except Exception as e:
            logger.warning(f"Historic district check failed: {e}")

        return status

    def check_by_address(self, address: str, borough: str) -> LandmarkStatus:
        """Check by address (less reliable than BBL)."""
        status = LandmarkStatus()

        # Try to find by address in landmark dataset
        try:
            address_upper = address.upper()
            borough_upper = borough.upper()

            results = self._query(
                LANDMARKS_DATASET,
                f"upper(address) LIKE '%{address_upper[:20]}%' AND upper(borough) = '{borough_upper}'",
                limit=1,
            )
            if results:
                status.is_landmark = True
                status.landmark_name = results[0].get("landmark_name", "")
        except Exception as e:
            logger.warning(f"Address-based landmark check failed: {e}")

        return status
