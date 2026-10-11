# ===========================================================================
# File: data/defenses.py
# ===========================================================================
"""
defenses.py
-----------
Opponent matchup multipliers for offensive players.

Primary source (preferred):
    Live season sample — fantasy points allowed by each defense to QB/RB/WR/TE
    over the first N weeks of the current season (via nflverse weekly stats).

Fallback:
    Preseason Defense_Predictions.json tiers (legacy).

Multiplier scale:
    Rank 1  (most pts allowed / softest)  → ~1.12
    Rank 16 (average)                     → 1.00
    Rank 32 (fewest pts allowed / toughest) → ~0.88
"""

from __future__ import annotations

import os
import json
from typing import Optional

ABBR_TO_FULL_NAME = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "JAC": "Jacksonville Jaguars", "KC": "Kansas City Chiefs", "LV": "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers", "SF": "San Francisco 49ers", "SEA": "Seattle Seahawks",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

_DEFENSE_JSON_CACHE: Optional[dict] = None
_SEASON_DVP_CACHE: dict = {}


def _rank_to_multiplier(rank: int, n_teams: int = 32) -> float:
    """Rank 1 (softest) ≈ 1.12, rank 32 (toughest) ≈ 0.88, midpoint ≈ 1.00."""
    if rank < 1:
        rank = 1
    if rank > n_teams:
        rank = n_teams
    span = 0.12
    t = 1.0 - 2.0 * (rank - 1) / max(n_teams - 1, 1)
    return round(1.0 + span * t, 3)


def _load_json_defenses() -> dict:
    global _DEFENSE_JSON_CACHE
    if _DEFENSE_JSON_CACHE is not None:
        return _DEFENSE_JSON_CACHE

    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, "Defense_Predictions.json")
    if not os.path.exists(json_path):
        _DEFENSE_JSON_CACHE = {}
        return _DEFENSE_JSON_CACHE

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cache = {}
        if isinstance(data, list):
            for item in data:
                team_name = item.get("team")
                if team_name:
                    cache[team_name.lower()] = item
        elif isinstance(data, dict):
            for k, v in data.items():
                cache[k.lower()] = v
        _DEFENSE_JSON_CACHE = cache
    except Exception:
        _DEFENSE_JSON_CACHE = {}
    return _DEFENSE_JSON_CACHE


def _tier_to_multiplier(text: str) -> float:
    if not text:
        return 1.0
    t = text.lower()
    if "elite" in t or "top 3" in t or "shutdown" in t:
        return 0.88
    if "above average" in t or "solid" in t:
        return 0.94
    if "vulnerable" in t or "poor" in t or "bottom" in t or "matador" in t:
        return 1.10
    if "weak" in t:
        return 1.08
    return 1.0


def _json_factor(position: str, opponent: str) -> float:
    defenses = _load_json_defenses()
    if not defenses or not opponent:
        return 1.0

    opp_upper = opponent.upper()
    full_name = ABBR_TO_FULL_NAME.get(opp_upper, "")
    def_data = defenses.get(full_name.lower()) if full_name else None
    if not def_data:
        for json_team_name, data_dict in defenses.items():
            if opp_upper in json_team_name.upper() or opponent.lower() in json_team_name.lower():
                def_data = data_dict
                break
    if not def_data:
        return 1.0

    if position == "RB":
        proj_text = def_data.get("vs_run_projection", "")
    else:
        proj_text = def_data.get("vs_pass_projection", "")

    multiplier = _tier_to_multiplier(proj_text)
    if multiplier == 1.0 and "rank" in def_data:
        rank = def_data.get("rank", 16)
        multiplier = _rank_to_multiplier(int(rank))
    return max(0.85, min(1.15, multiplier))


def _season_dvp_table(season: int, max_week: int | None, min_week: int = 1):
    key = (season, min_week, max_week)
    if key in _SEASON_DVP_CACHE:
        return _SEASON_DVP_CACHE[key]

    try:
        from data.nflverse import get_points_allowed_by_defense
        table = get_points_allowed_by_defense(
            season, max_week=max_week, min_week=min_week, scoring="ppr"
        )
    except Exception:
        table = None

    _SEASON_DVP_CACHE[key] = table
    return table


def resolve_sample_window(
    season: int | None = None,
    mode: str = "all",
    last_n: int = 4,
) -> tuple[int, int, int]:
    """
    Resolve (season, min_week, max_week) for the defensive sample.

    mode:
      - "all": weeks 1 .. latest completed
      - "last_n": the last `last_n` completed weeks
    """
    from datetime import date
    from data.nflverse import get_latest_completed_week

    if season is None:
        today = date.today()
        season = today.year if today.month >= 8 else today.year - 1

    latest = get_latest_completed_week(season)
    if latest < 1:
        # No live data yet — caller should fall back to preseason
        return season, 1, 0

    if mode == "last_n":
        n = max(1, int(last_n))
        min_week = max(1, latest - n + 1)
        max_week = latest
    else:
        min_week = 1
        max_week = latest

    return season, min_week, max_week


def get_opponent_defensive_factor(
    position: str,
    opponent: str,
    use_preseason: bool = False,
    season: Optional[int] = None,
    max_week: Optional[int] = None,
    min_week: int = 1,
    sample_mode: str = "all",
    last_n: int = 4,
) -> float:
    """
    Matchup multiplier for an offensive player facing `opponent`.

    Live season sample is preferred unless use_preseason=True.
    sample_mode "all" uses weeks 1..latest; "last_n" uses the trailing window.
    Falls back to preseason JSON if the live table is unavailable.
    """
    if not opponent or position in ("DST", "K", "DEF"):
        return 1.0

    if not use_preseason:
        # Resolve window if caller did not pin min/max explicitly
        if max_week is None or (sample_mode and min_week == 1 and max_week is None):
            season, min_week, max_week = resolve_sample_window(
                season, mode=sample_mode, last_n=last_n
            )
        elif season is None:
            from datetime import date
            today = date.today()
            season = today.year if today.month >= 8 else today.year - 1

        if max_week and max_week >= 1:
            table = _season_dvp_table(season, max_week, min_week=min_week)
            if table is not None and not getattr(table, "empty", True):
                from data.nflverse import normalize_team
                opp = normalize_team(opponent, "to_nfl")
                if opp == "JAC":
                    candidates = ["JAC", "JAX"]
                elif opp == "JAX":
                    candidates = ["JAX", "JAC"]
                else:
                    candidates = [opp]

                pos = "RB" if position == "FB" else position
                row = table[
                    (table["defense"].isin(candidates)) & (table["position"] == pos)
                ]
                if not row.empty:
                    rank = int(row.iloc[0]["rank"])
                    return max(0.85, min(1.15, _rank_to_multiplier(rank)))

    return _json_factor(position, opponent)


def get_matchup_detail(
    position: str,
    opponent: str,
    use_preseason: bool = False,
    season: Optional[int] = None,
    max_week: Optional[int] = None,
    min_week: int = 1,
    sample_mode: str = "all",
    last_n: int = 4,
) -> dict:
    """Richer matchup info for UI: multiplier, rank, pts_allowed, games, source, badge."""
    if not use_preseason and max_week is None:
        season, min_week, max_week = resolve_sample_window(
            season, mode=sample_mode, last_n=last_n
        )

    mult = get_opponent_defensive_factor(
        position, opponent,
        use_preseason=use_preseason,
        season=season,
        max_week=max_week,
        min_week=min_week,
        sample_mode=sample_mode,
        last_n=last_n,
    )

    detail = {
        "multiplier": mult,
        "rank": None,
        "pts_allowed": None,
        "games": None,
        "source": "preseason" if use_preseason else "neutral",
        "badge": "⚪ Neutral",
        "min_week": min_week,
        "max_week": max_week,
    }

    if not use_preseason and max_week and max_week >= 1:
        if season is None:
            from datetime import date
            today = date.today()
            season = today.year if today.month >= 8 else today.year - 1
        table = _season_dvp_table(season, max_week, min_week=min_week)
        if table is not None and not getattr(table, "empty", True):
            from data.nflverse import normalize_team
            opp = normalize_team(opponent, "to_nfl")
            candidates = ["JAC", "JAX"] if opp in ("JAC", "JAX") else [opp]
            pos = "RB" if position == "FB" else position
            row = table[
                (table["defense"].isin(candidates)) & (table["position"] == pos)
            ]
            if not row.empty:
                r = row.iloc[0]
                detail["rank"] = int(r["rank"])
                detail["pts_allowed"] = round(float(r["pts_allowed"]), 1)
                detail["games"] = int(r["games"])
                if min_week <= 1:
                    detail["source"] = f"weeks_1_{max_week}"
                else:
                    detail["source"] = f"weeks_{min_week}_{max_week}"

    if mult < 0.95:
        detail["badge"] = "🔴 Tough"
    elif mult > 1.05:
        detail["badge"] = "🟢 Soft"
    else:
        detail["badge"] = "🟡 Neutral"

    return detail


def clear_defense_cache() -> None:
    """Clear in-memory season DvP cache."""
    global _SEASON_DVP_CACHE, _DEFENSE_JSON_CACHE
    _SEASON_DVP_CACHE = {}
    _DEFENSE_JSON_CACHE = None
