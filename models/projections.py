# ===========================================================================
# File: models/projections.py
# ===========================================================================
"""
models/projections.py
---------------------
Enriches Player objects with nflverse stats and computes an adjusted projection.

The enrichment pipeline:
  1. Match each DK player to nflverse recent stats by name + team
  2. Attach snap %, recent form stats (targets, carries, etc.)
  3. Attach Vegas game context (total, spread, home/away, implied total)
  4. Compute an adjusted projection blending DK avg with recent form + Vegas

Projection formula (by position):

  QB:   base * 0.40 + recent_avg * 0.40 + vegas_boost * 0.20
  RB:   base * 0.35 + recent_avg * 0.40 + vegas_boost * 0.15 + snap_boost * 0.10
  WR:   base * 0.35 + recent_avg * 0.35 + target_boost * 0.20 + vegas_boost * 0.10
  TE:   base * 0.35 + recent_avg * 0.40 + target_boost * 0.15 + vegas_boost * 0.10
  DST:  base (no enrichment — opponent offense modeling is out of scope for MVP)

All boosts are additive adjustments, not multipliers, keeping the scale in
fantasy points. If nflverse data is unavailable for a player, the DK
AvgPointsPerGame is used unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from data.nflverse import (
    get_player_recent_stats,
    get_snap_pct_recent,
    get_game_context,
    normalize_team,
    is_available,
)
from models.player import Player


# ---------------------------------------------------------------------------
# Enriched stats attached to each Player
# ---------------------------------------------------------------------------
@dataclass
class PlayerStats:
    """nflverse-derived stats for a single player."""

    # Recent form (last N weeks average)
    recent_fantasy_pts: Optional[float] = None
    avg_targets:        Optional[float] = None
    avg_target_share:   Optional[float] = None
    avg_air_yards_share: Optional[float] = None
    avg_wopr:           Optional[float] = None
    avg_receptions:     Optional[float] = None
    avg_receiving_yards: Optional[float] = None
    avg_receiving_tds:  Optional[float] = None
    avg_carries:        Optional[float] = None
    avg_rushing_yards:  Optional[float] = None
    avg_rushing_tds:    Optional[float] = None
    avg_passing_yards:  Optional[float] = None
    avg_passing_tds:    Optional[float] = None
    avg_interceptions:  Optional[float] = None
    games_played:       Optional[int]   = None

    # Snap usage
    avg_snap_pct: Optional[float] = None

    # Vegas context
    total_line:    Optional[float] = None
    spread_line:   Optional[float] = None
    is_home:       Optional[bool]  = None
    implied_total: Optional[float] = None

    # Adjusted projection (output)
    adjusted_projection: Optional[float] = None
    data_source: str = "dk_only"   # 'dk_only' | 'enriched'

    def to_display_dict(self) -> dict:
        """Flat dict for showing in the player pool table."""
        return {
            "Rec Pts":     _fmt(self.recent_fantasy_pts),
            "Targets":     _fmt(self.avg_targets),
            "Tgt Share":   _fmt_pct(self.avg_target_share),
            "WOPR":        _fmt(self.avg_wopr, 3),
            "Snap%":       _fmt_pct(self.avg_snap_pct),
            "Carries":     _fmt(self.avg_carries),
            "Rush Yds":    _fmt(self.avg_rushing_yards),
            "Pass Yds":    _fmt(self.avg_passing_yards),
            "Game Total":  _fmt(self.total_line),
            "Implied":     _fmt(self.implied_total),
            "Home":        ("Yes" if self.is_home else "No") if self.is_home is not None else "-",
        }


def _fmt(val, decimals: int = 1) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    return f"{val:.{decimals}f}"


def _fmt_pct(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    return f"{val * 100:.1f}%"


# ---------------------------------------------------------------------------
# Vegas boost helpers
# ---------------------------------------------------------------------------
LEAGUE_AVG_TOTAL = 47.0   # approximate NFL average game total


def _vegas_boost(implied_total: Optional[float], position: str) -> float:
    """
    Return a small additive fantasy-point adjustment based on team implied total.
    Scale: +/- ~2 pts at extremes vs league average.
    """
    if implied_total is None:
        return 0.0
    delta = implied_total - (LEAGUE_AVG_TOTAL / 2)   # vs avg team total ~23.5
    multipliers = {"QB": 0.20, "RB": 0.12, "WR": 0.10, "TE": 0.08}
    return delta * multipliers.get(position, 0.0)


def _home_boost(is_home: Optional[bool], position: str) -> float:
    """Small home-field advantage boost."""
    if is_home is None:
        return 0.0
    boosts = {"QB": 0.4, "RB": 0.2, "WR": 0.25, "TE": 0.15}
    return boosts.get(position, 0.0) if is_home else 0.0


# ---------------------------------------------------------------------------
# Core enrichment logic per position
# ---------------------------------------------------------------------------
def _adjust_qb(base: float, stats: PlayerStats) -> float:
    recent = stats.recent_fantasy_pts
    if recent is None:
        return base
    vegas = _vegas_boost(stats.implied_total, "QB")
    home  = _home_boost(stats.is_home, "QB")
    return round(base * 0.40 + recent * 0.60 + vegas + home, 2)


def _adjust_rb(base: float, stats: PlayerStats) -> float:
    recent = stats.recent_fantasy_pts
    if recent is None:
        return base
    vegas  = _vegas_boost(stats.implied_total, "RB")
    home   = _home_boost(stats.is_home, "RB")
    # Snap% bonus: every 10% above 50% adds 0.3 pts
    snap_bonus = 0.0
    if stats.avg_snap_pct is not None:
        snap_bonus = max(0.0, (stats.avg_snap_pct - 0.50) * 3.0)
    return round(base * 0.35 + recent * 0.65 + vegas + home + snap_bonus, 2)


def _adjust_wr(base: float, stats: PlayerStats) -> float:
    recent = stats.recent_fantasy_pts
    if recent is None:
        return base
    vegas  = _vegas_boost(stats.implied_total, "WR")
    home   = _home_boost(stats.is_home, "WR")
    # Target share bonus: every 5% above 20% adds 0.5 pts
    tgt_bonus = 0.0
    if stats.avg_target_share is not None:
        tgt_bonus = max(0.0, (stats.avg_target_share - 0.20) * 10.0)
    # WOPR bonus
    wopr_bonus = 0.0
    if stats.avg_wopr is not None:
        wopr_bonus = max(0.0, (stats.avg_wopr - 0.50) * 2.0)
    return round(base * 0.30 + recent * 0.60 + vegas + home + tgt_bonus + wopr_bonus, 2)


def _adjust_te(base: float, stats: PlayerStats) -> float:
    recent = stats.recent_fantasy_pts
    if recent is None:
        return base
    vegas  = _vegas_boost(stats.implied_total, "TE")
    home   = _home_boost(stats.is_home, "TE")
    tgt_bonus = 0.0
    if stats.avg_target_share is not None:
        tgt_bonus = max(0.0, (stats.avg_target_share - 0.12) * 8.0)
    return round(base * 0.35 + recent * 0.65 + vegas + home + tgt_bonus, 2)


_ADJUSTERS = {
    "QB":  _adjust_qb,
    "RB":  _adjust_rb,
    "WR":  _adjust_wr,
    "TE":  _adjust_te,
}


# ---------------------------------------------------------------------------
# Name matching helpers
# ---------------------------------------------------------------------------
def _normalize_name(name: str) -> str:
    """Lowercase, strip punctuation for fuzzy matching."""
    import re
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def _find_player_row(
    name: str,
    team: str,
    stats_df: pd.DataFrame,
    name_col: str = "player_display_name",
    team_col: str = "recent_team",
) -> Optional[pd.Series]:
    """
    Match a DK player name to a nflverse row.
    Tries exact match first, then normalized match.
    """
    if stats_df.empty:
        return None

    team_nfl = normalize_team(team, "to_nfl")

    # Exact match on name + team
    exact = stats_df[
        (stats_df[name_col] == name) & (stats_df[team_col] == team_nfl)
    ]
    if not exact.empty:
        return exact.iloc[0]

    # Exact name, any team (handles team changes)
    name_only = stats_df[stats_df[name_col] == name]
    if not name_only.empty:
        return name_only.iloc[0]

    # Normalized name match
    norm = _normalize_name(name)
    stats_df = stats_df.copy()
    stats_df["_norm"] = stats_df[name_col].apply(_normalize_name)
    fuzzy = stats_df[stats_df["_norm"] == norm]
    if not fuzzy.empty:
        return fuzzy.iloc[0]

    return None


def _find_snap_row(
    name: str,
    team: str,
    snaps_df: pd.DataFrame,
) -> Optional[pd.Series]:
    """Match a player in the snap counts DataFrame."""
    if snaps_df.empty:
        return None

    team_nfl = normalize_team(team, "to_nfl")
    exact = snaps_df[
        (snaps_df["player"] == name) & (snaps_df["team"] == team_nfl)
    ]
    if not exact.empty:
        return exact.iloc[0]

    # Normalized
    norm = _normalize_name(name)
    snaps_df = snaps_df.copy()
    snaps_df["_norm"] = snaps_df["player"].apply(_normalize_name)
    fuzzy = snaps_df[snaps_df["_norm"] == norm]
    if not fuzzy.empty:
        return fuzzy.iloc[0]

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def enrich_players(
    players: list,
    seasons: list[int],
    recent_weeks: int = 4,
    min_snap_pct: Optional[float] = None,
) -> dict:
    """
    Enrich a list of Player objects with nflverse stats.

    Returns a dict mapping player.dk_id -> PlayerStats.
    The Player objects themselves are NOT mutated — callers read from this dict.

    If nfl_data_py is not installed or data fetch fails, returns an empty dict
    and the app falls back to DK projections.
    """
    if not is_available():
        return {}

    try:
        # Fetch all data upfront (cached after first call)
        recent_stats = get_player_recent_stats(seasons, recent_weeks=recent_weeks)
        snap_data    = get_snap_pct_recent(seasons, recent_weeks=recent_weeks)
    except Exception:
        return {}

    results: dict[int, PlayerStats] = {}

    for player in players:
        if player.position == "DST":
            # DST uses DK projection as-is
            ps = PlayerStats(
                adjusted_projection=player.projection,
                data_source="dk_only",
            )
            results[player.dk_id] = ps
            continue

        stats = PlayerStats()

        # --- Weekly stats match ---
        row = _find_player_row(player.name, player.team, recent_stats)
        if row is not None:
            stats.recent_fantasy_pts  = _safe_float(row, "avg_fantasy_pts")
            stats.avg_targets         = _safe_float(row, "avg_targets")
            stats.avg_target_share    = _safe_float(row, "avg_target_share")
            stats.avg_air_yards_share = _safe_float(row, "avg_air_yards_share")
            stats.avg_wopr            = _safe_float(row, "avg_wopr")
            stats.avg_receptions      = _safe_float(row, "avg_receptions")
            stats.avg_receiving_yards = _safe_float(row, "avg_receiving_yards")
            stats.avg_receiving_tds   = _safe_float(row, "avg_receiving_tds")
            stats.avg_carries         = _safe_float(row, "avg_carries")
            stats.avg_rushing_yards   = _safe_float(row, "avg_rushing_yards")
            stats.avg_rushing_tds     = _safe_float(row, "avg_rushing_tds")
            stats.avg_passing_yards   = _safe_float(row, "avg_passing_yards")
            stats.avg_passing_tds     = _safe_float(row, "avg_passing_tds")
            stats.avg_interceptions   = _safe_float(row, "avg_interceptions")
            stats.games_played        = int(row["games_played"]) if "games_played" in row else None

        # --- Snap % match ---
        snap_row = _find_snap_row(player.name, player.team, snap_data)
        if snap_row is not None:
            stats.avg_snap_pct = _safe_float(snap_row, "avg_snap_pct")

        # --- Minimum snap rate threshold filter ---
        if min_snap_pct is not None and stats.avg_snap_pct is not None:
            if stats.avg_snap_pct < min_snap_pct:
                continue

        # --- Vegas context ---
        try:
            ctx = get_game_context(seasons, player.team, player.opponent)
            if ctx:
                stats.total_line    = ctx.get("total_line")
                stats.spread_line   = ctx.get("spread_line")
                stats.is_home       = ctx.get("is_home")
                stats.implied_total = ctx.get("implied_total")
        except Exception:
            pass

        # --- Compute adjusted projection ---
        adjuster = _ADJUSTERS.get(player.position)
        if adjuster and stats.recent_fantasy_pts is not None:
            stats.adjusted_projection = adjuster(player.projection, stats)
            stats.data_source = "enriched"
        else:
            # No recent data found — fall back to DK projection
            # Still apply Vegas boost if we have it
            base = player.projection
            vegas = _vegas_boost(stats.implied_total, player.position)
            home  = _home_boost(stats.is_home, player.position)
            stats.adjusted_projection = round(base + vegas + home, 2)
            stats.data_source = "vegas_only" if (stats.implied_total is not None) else "dk_only"

        results[player.dk_id] = stats

    return results


def _safe_float(row, col: str) -> Optional[float]:
    """Safely extract a float from a Series row, returning None on missing/NaN."""
    if col not in row.index:
        return None
    val = row[col]
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None