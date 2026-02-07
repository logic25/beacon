"""
NYC Zoning Analysis Module

Provides comprehensive zoning analysis for any NYC address including:
- Permitted uses (Use Groups)
- Bulk regulations (FAR, height, setbacks)
- Parking requirements
- Landmark status
- Flood zones
- Special district rules
"""

from .analyzer import ZoningAnalyzer, ZoningAnalysis

__all__ = ["ZoningAnalyzer", "ZoningAnalysis"]
