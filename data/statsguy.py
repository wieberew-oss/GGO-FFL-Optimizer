"""
data/statsguy.py
----------------
Fetch Stats Guy Fantasy redraft rankings for pressure-testing lineups.

Note: Stats Guy values are trade/market valuations (redraft/dynasty), NOT
weekly DFS point projections. We use relative rank / value as an independent
signal to flag disagreements with our model — a pressure test, not a replacement.
"""

from __future__ import annotations

from typing import Optional, Dict, List
import re
import requests

_BASE = "https://api.statsguyfantasy.com/api/v1"
_CACHE: Dict[str, list] = {}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z ]", "", (name or "").lower()).strip()


def fetch_rankings(
    format: str = "non_sf_redraft",
    position: Optional[str] = None,
    limit: int = 300,
) -> list:
    """Return list of ranking dicts from Stats Guy (cached per format/position)."""
    cache_key = f"{format}|{position or 'ALL'}|{limit}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    params = {"format": format, "limit": limit}
    if position:
        params["position"] = position

    try:
        resp = requests.get(f"{_BASE}/rankings", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        rankings = data.get("rankings") or data.get("data") or []
        if isinstance(data, list):
            rankings = data
        _CACHE[cache_key] = rankings
        return rankings
    except Exception:
        return []


def build_lookup(
    format: str = "non_sf_redraft",
    limit: int = 400,
) -> Dict[str, dict]:
    """
    name_normalized -> {rank, positionRank, value, position, team, name}
    Fetches all skill positions.
    """
    lookup: Dict[str, dict] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_rankings(format=format, position=pos, limit=limit)
        for r in rows:
            name = r.get("name") or ""
            key = _normalize(name)
            if not key:
                continue
            lookup[key] = {
                "name": name,
                "rank": r.get("rank"),
                "positionRank": r.get("positionRank"),
                "value": r.get("value"),
                "position": r.get("position") or pos,
                "team": r.get("team"),
            }
    return lookup


def match_player(name: str, lookup: Dict[str, dict]) -> Optional[dict]:
    key = _normalize(name)
    if key in lookup:
        return lookup[key]
    # light fuzzy: last token match among same first letter
    parts = key.split()
    if not parts:
        return None
    for k, v in lookup.items():
        if k.endswith(parts[-1]) and k[:1] == key[:1]:
            return v
    return None


def pressure_test_lineup(
    lineup_players: list,
    format: str = "non_sf_redraft",
) -> List[dict]:
    """
    For each player in the lineup, attach Stats Guy rank/value if found.

    lineup_players: iterable of objects with .name, .position, .projection
                    (Player instances work)
    """
    lookup = build_lookup(format=format)
    rows = []
    for p in lineup_players:
        name = getattr(p, "name", str(p))
        pos = getattr(p, "position", "")
        proj = getattr(p, "projection", None)
        hit = match_player(name, lookup)
        rows.append({
            "Player": name,
            "Pos": pos,
            "Our Proj": round(proj, 1) if proj is not None else None,
            "SG Rank": hit.get("rank") if hit else None,
            "SG Pos Rank": hit.get("positionRank") if hit else None,
            "SG Value": hit.get("value") if hit else None,
            "SG Team": hit.get("team") if hit else None,
            "Matched": "Yes" if hit else "No",
        })
    return rows


def clear_statsguy_cache() -> None:
    _CACHE.clear()
