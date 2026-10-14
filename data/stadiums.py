"""
data/stadiums.py
----------------
Indoor vs outdoor stadium classification for weather adjustments.

Retractable-roof venues are treated as indoor (weather largely neutralized).
"""

from __future__ import annotations

# NFL team abbrev (DK-style + common variants) → indoor?
# True = dome / retractable (weather ignored)
INDOOR_TEAMS = {
    "ATL", "DET", "NO", "MIN",  # fixed domes
    "DAL", "HOU", "ARI", "IND", "LV", "LAR", "LAC",  # retractable
}

# City/lat-lon for outdoor home venues (approx stadium coords)
# Used only for outdoor teams when fetching weather.
OUTDOOR_STADIUM_COORDS = {
    "BAL": (39.2780, -76.6227),
    "BUF": (42.7738, -78.7870),
    "CAR": (35.2258, -80.8528),
    "CHI": (41.8623, -87.6167),
    "CIN": (39.0950, -84.5160),
    "CLE": (41.5061, -81.6995),
    "DEN": (39.7439, -105.0201),
    "GB":  (44.5013, -88.0622),
    "JAC": (30.3239, -81.6333),
    "JAX": (30.3239, -81.6333),
    "KC":  (39.0489, -94.4839),
    "MIA": (25.9580, -80.2389),
    "NE":  (42.0909, -71.2643),
    "NYG": (40.8128, -74.0742),
    "NYJ": (40.8128, -74.0742),
    "PHI": (39.9008, -75.1675),
    "PIT": (40.4468, -80.0158),
    "SF":  (37.4032, -121.9698),
    "SEA": (47.5952, -122.3316),
    "TB":  (27.9759, -82.5033),
    "TEN": (36.1665, -86.7713),
    "WAS": (38.9077, -76.8645),
    "WSH": (38.9077, -76.8645),
}


def is_indoor(team: str) -> bool:
    if not team:
        return False
    return team.upper() in INDOOR_TEAMS


def stadium_coords(team: str) -> tuple[float, float] | None:
    """Return (lat, lon) for outdoor home stadium, else None."""
    if not team:
        return None
    t = team.upper()
    if t in INDOOR_TEAMS:
        return None
    return OUTDOOR_STADIUM_COORDS.get(t)
