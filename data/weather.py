"""
data/weather.py
---------------
Outdoor-game weather context via Open-Meteo (free, no API key).

Returns a small additive fantasy adjustment:
  - Strong wind and/or heavy precip → discount pass-heavy positions
  - Same bad weather → slight boost to DST (lower scoring, more stalled drives)
  - Mild conditions → neutral
Indoor / retractable venues always return neutral.
"""

from __future__ import annotations

from typing import Optional
from urllib.request import urlopen
import json

from data.stadiums import is_indoor, stadium_coords

_cache: dict = {}


def clear_weather_cache() -> None:
    _cache.clear()


def _fetch_forecast(lat: float, lon: float) -> Optional[dict]:
    key = (round(lat, 3), round(lon, 3))
    if key in _cache:
        return _cache[key]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=precipitation_sum,windspeed_10m_max,temperature_2m_max"
        "&timezone=America%2FNew_York&forecast_days=3"
    )
    try:
        with urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        _cache[key] = data
        return data
    except Exception:
        return None


def weather_for_team(home_team: str) -> dict:
    """
    Weather summary for a team's home stadium.
    Returns dict with keys: indoor, wind_mph, precip_mm, temp_f, badge, pass_delta
    pass_delta is an additive fantasy-point nudge for QB/WR/TE (negative = tougher).
    """
    neutral = {
        "indoor": True,
        "wind_mph": None,
        "precip_mm": None,
        "temp_f": None,
        "badge": "🏟️ Indoor",
        "pass_delta": 0.0,
        "note": "Indoor / retractable — weather ignored",
    }
    if not home_team or is_indoor(home_team):
        return neutral

    coords = stadium_coords(home_team)
    if coords is None:
        return {
            "indoor": False,
            "wind_mph": None,
            "precip_mm": None,
            "temp_f": None,
            "badge": "🌤️ Outdoor (no forecast)",
            "pass_delta": 0.0,
            "note": "Outdoor but forecast unavailable",
        }

    data = _fetch_forecast(*coords)
    if not data or "daily" not in data:
        return {
            "indoor": False,
            "wind_mph": None,
            "precip_mm": None,
            "temp_f": None,
            "badge": "🌤️ Outdoor (no forecast)",
            "pass_delta": 0.0,
            "note": "Outdoor but forecast unavailable",
        }

    daily = data["daily"]
    # Use day-0 (today/next) max values as a simple weekly proxy
    wind_kmh = (daily.get("windspeed_10m_max") or [None])[0]
    precip = (daily.get("precipitation_sum") or [None])[0]
    temp_c = (daily.get("temperature_2m_max") or [None])[0]

    wind_mph = round(wind_kmh * 0.621371, 1) if wind_kmh is not None else None
    temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None
    precip_mm = round(float(precip), 1) if precip is not None else None

    pass_delta = 0.0
    notes = []
    if wind_mph is not None and wind_mph >= 20:
        pass_delta -= 1.5
        notes.append(f"wind {wind_mph} mph")
    elif wind_mph is not None and wind_mph >= 15:
        pass_delta -= 0.8
        notes.append(f"wind {wind_mph} mph")
    if precip_mm is not None and precip_mm >= 8:
        pass_delta -= 1.0
        notes.append(f"rain {precip_mm} mm")
    elif precip_mm is not None and precip_mm >= 3:
        pass_delta -= 0.4
        notes.append(f"rain {precip_mm} mm")
    if temp_f is not None and temp_f <= 25:
        pass_delta -= 0.5
        notes.append(f"cold {temp_f}°F")

    if pass_delta <= -1.5:
        badge = "💨 Tough wx"
    elif pass_delta < 0:
        badge = "🌧️ Soft wx hit"
    else:
        badge = "☀️ Clear outdoor"

    return {
        "indoor": False,
        "wind_mph": wind_mph,
        "precip_mm": precip_mm,
        "temp_f": temp_f,
        "badge": badge,
        "pass_delta": round(pass_delta, 2),
        "note": ", ".join(notes) if notes else "Mild outdoor conditions",
    }


def weather_pass_delta_for_game(home_team: str, position: str) -> float:
    """
    Additive projection delta for a player based on home-stadium weather.

    - QB / WR / TE: negative in wind/rain/cold (pass suppression)
    - RB: small positive when pass is suppressed (run-script tilt)
    - DST: modest positive when pass is suppressed (lower scoring, more
      negative plays / field-position advantages)
    """
    wx = weather_for_team(home_team)
    delta = float(wx.get("pass_delta") or 0.0)
    if position in {"QB", "WR", "TE"}:
        return delta
    if delta >= 0:
        return 0.0
    # Bad weather branch
    if position == "RB":
        return round(abs(delta) * 0.25, 2)
    if position == "DST":
        # ~half the magnitude of the pass hit, as a DST boost (capped softly upstream)
        return round(abs(delta) * 0.50, 2)
    return 0.0
