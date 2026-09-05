"""
data/nflverse.py
----------------
Fetches and caches NFL player stats, snap counts, and schedules.

Data sources:
  - Seasons 1999–2024: nfl_data_py (nflverse-data player_stats release)
  - Season 2025+:      Direct CDN fetch from nflverse stats_player release
                       https://github.com/nflverse/nflverse-data/releases/download/stats_player/
  - Snap counts:       nflverse snap_counts release (has 2025 data)
  - Schedules:         nflverse schedules release

The two stat formats are normalized to a common schema before use.

All data is cached in memory per session. Call clear_cache() to reset.
"""

from __future__ import annotations

import warnings
from typing import Optional

import pandas as pd
import requests

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*Downcasting.*")

try:
    import nfl_data_py as nfl
    NFL_DATA_AVAILABLE = True
except ImportError:
    NFL_DATA_AVAILABLE = False

# ---------------------------------------------------------------------------
# CDN base URLs
# ---------------------------------------------------------------------------
_CDN_STATS   = "https://github.com/nflverse/nflverse-data/releases/download/stats_player"
_CDN_SNAPS   = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts"
_CDN_SCHED   = "https://github.com/nflverse/nflverse-data/releases/download/schedules"

# nfl-data-py wraps the old player_stats release which tops out at 2024
_LEGACY_MAX_SEASON = 2024   # last season available via nfl-data-py
_CDN_MIN_SEASON    = 2024   # new CDN format starts here (we overlap 2024 for consistency)

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_cache: dict = {}


def clear_cache() -> None:
    _cache.clear()


def is_available() -> bool:
    """Returns True if at least pandas is available (CDN fetch works without nfl-data-py)."""
    return True   # we can always use CDN direct


# ---------------------------------------------------------------------------
# Team abbreviation normalization
# ---------------------------------------------------------------------------
DK_TO_NFL: dict[str, str] = {
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "JAX": "JAC",
    "SL":  "LAR",
    "SD":  "LAC",
    "OAK": "LV",
}
NFL_TO_DK: dict[str, str] = {v: k for k, v in DK_TO_NFL.items()}


def normalize_team(team: str, direction: str = "to_nfl") -> str:
    if direction == "to_nfl":
        return DK_TO_NFL.get(team, team)
    return NFL_TO_DK.get(team, team)


# ---------------------------------------------------------------------------
# Internal: fetch one season of weekly stats via CDN (new format, 2024+)
# ---------------------------------------------------------------------------
def _fetch_cdn_weekly(season: int) -> pd.DataFrame:
    """
    Fetch weekly player stats from the nflverse stats_player CDN.
    Returns normalized DataFrame with same schema as legacy data.
    New format uses 'team' instead of 'recent_team'.
    """
    url = f"{_CDN_STATS}/stats_player_week_{season}.parquet"
    df = pd.read_parquet(url, engine="auto")

    # Normalize to legacy column names our code expects
    if "team" in df.columns and "recent_team" not in df.columns:
        df = df.rename(columns={"team": "recent_team"})
    if "passing_interceptions" in df.columns and "interceptions" not in df.columns:
        df = df.rename(columns={"passing_interceptions": "interceptions"})

    # Add season_type if missing (CDN format includes it)
    if "season_type" not in df.columns:
        df["season_type"] = "REG"

    return df


# ---------------------------------------------------------------------------
# Internal: fetch one season of weekly stats via nfl-data-py (legacy, ≤2024)
# ---------------------------------------------------------------------------
def _fetch_legacy_weekly(season: int) -> pd.DataFrame:
    """Fetch via nfl_data_py for seasons where it's still the best source."""
    return nfl.import_weekly_data([season])


# ---------------------------------------------------------------------------
# Public: weekly stats
# ---------------------------------------------------------------------------
def fetch_weekly_stats(seasons: list[int]) -> pd.DataFrame:
    """
    Return weekly player stats for the given seasons.
    Uses CDN direct fetch for 2024+ (more current), nfl-data-py for older seasons.
    All seasons cached individually after first fetch.
    """
    frames = []
    for season in seasons:
        cache_key = ("weekly", season)
        if cache_key in _cache:
            frames.append(_cache[cache_key])
            continue

        df = None
        # Try CDN first for all seasons (it has 2024 and 2025)
        try:
            df = _fetch_cdn_weekly(season)
        except Exception:
            pass

        # Fall back to nfl-data-py for seasons it covers
        if df is None and NFL_DATA_AVAILABLE and season <= _LEGACY_MAX_SEASON:
            try:
                df = _fetch_legacy_weekly(season)
            except Exception:
                pass

        if df is None:
            continue   # season not available — skip silently

        # Keep REG + POST only
        if "season_type" in df.columns:
            df = df[df["season_type"].isin(["REG", "POST"])].copy()

        # Normalize team columns
        if "recent_team" in df.columns:
            df["recent_team"] = df["recent_team"].apply(lambda t: normalize_team(str(t), "to_nfl"))
        if "opponent_team" in df.columns:
            df["opponent_team"] = df["opponent_team"].apply(lambda t: normalize_team(str(t), "to_nfl"))

        _cache[cache_key] = df
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Public: snap counts
# ---------------------------------------------------------------------------
def fetch_snap_counts(seasons: list[int]) -> pd.DataFrame:
    """
    Return snap count data. Uses nflverse CDN directly (has 2025 data).
    """
    frames = []
    for season in seasons:
        cache_key = ("snaps", season)
        if cache_key in _cache:
            frames.append(_cache[cache_key])
            continue

        df = None
        # Try CDN snap counts
        try:
            url = f"{_CDN_SNAPS}/snap_counts_{season}.parquet"
            df = pd.read_parquet(url, engine="auto")
        except Exception:
            pass

        # Fall back to nfl-data-py
        if df is None and NFL_DATA_AVAILABLE and season <= _LEGACY_MAX_SEASON:
            try:
                df = nfl.import_snap_counts([season])
            except Exception:
                pass

        if df is None:
            continue

        if "team" in df.columns:
            df["team"] = df["team"].apply(lambda t: normalize_team(str(t), "to_nfl"))

        _cache[cache_key] = df
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Public: schedules
# ---------------------------------------------------------------------------
def fetch_schedules(seasons: list[int]) -> pd.DataFrame:
    """
    Return schedule/Vegas line data.
    The nflverse schedules release uses a single combined file: games.parquet
    covering all seasons. We filter to requested seasons after fetching.
    """
    cache_key = ("schedules_all",)
    if cache_key not in _cache:
        df = None
        # Try CDN combined file first
        try:
            url = f"{_CDN_SCHED}/games.parquet"
            df = pd.read_parquet(url, engine="auto")
        except Exception:
            pass

        # Fall back to nfl-data-py for older data
        if df is None and NFL_DATA_AVAILABLE:
            try:
                all_seasons = list(range(2019, 2026))
                df = nfl.import_schedules(all_seasons)
            except Exception:
                pass

        if df is None:
            return pd.DataFrame()

        if "home_team" in df.columns:
            df["home_team"] = df["home_team"].apply(lambda t: normalize_team(str(t), "to_nfl"))
        if "away_team" in df.columns:
            df["away_team"] = df["away_team"].apply(lambda t: normalize_team(str(t), "to_nfl"))

        _cache[cache_key] = df

    all_games = _cache[cache_key]

    if seasons and "season" in all_games.columns:
        return all_games[all_games["season"].isin(seasons)].copy()
    return all_games


# ---------------------------------------------------------------------------
# Aggregated player stats
# ---------------------------------------------------------------------------
def get_player_recent_stats(
    seasons: list[int],
    recent_weeks: int = 4,
    position_filter: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Return per-player aggregated stats for the most recent N weeks.
    """
    weekly = fetch_weekly_stats(seasons)
    if weekly.empty:
        return pd.DataFrame()

    weekly_sorted = weekly.sort_values(["season", "week"], ascending=False)
    recent = weekly_sorted.groupby("player_display_name").head(recent_weeks)

    if position_filter:
        recent = recent[recent["position"].isin(position_filter)]

    # Flexible column mapping — handles both old and new schema
    avg_cols = {}
    col_candidates = {
        "fantasy_points":              "avg_fantasy_pts",
        "targets":                     "avg_targets",
        "target_share":                "avg_target_share",
        "receptions":                  "avg_receptions",
        "receiving_yards":             "avg_receiving_yards",
        "receiving_tds":               "avg_receiving_tds",
        "receiving_air_yards":         "avg_air_yards",
        "receiving_yards_after_catch": "avg_yac",
        "air_yards_share":             "avg_air_yards_share",
        "wopr":                        "avg_wopr",
        "carries":                     "avg_carries",
        "rushing_yards":               "avg_rushing_yards",
        "rushing_tds":                 "avg_rushing_tds",
        "passing_yards":               "avg_passing_yards",
        "passing_tds":                 "avg_passing_tds",
        # interceptions column name changed between formats
        "interceptions":               "avg_interceptions",
        "passing_interceptions":       "avg_interceptions",
    }
    seen_targets = set()
    for src_col, dst_col in col_candidates.items():
        if src_col in recent.columns and dst_col not in seen_targets:
            avg_cols[src_col] = dst_col
            seen_targets.add(dst_col)

    agg_dict = {k: "mean" for k in avg_cols.keys()}
    agg_dict["week"] = "count"

    team_col = "recent_team" if "recent_team" in recent.columns else "team"

    grouped = (
        recent
        .groupby(["player_display_name", "position", team_col], as_index=False)
        .agg(agg_dict)
        .rename(columns={**avg_cols, "week": "games_played", team_col: "recent_team"})
    )

    return grouped


def get_snap_pct_recent(
    seasons: list[int],
    recent_weeks: int = 4,
) -> pd.DataFrame:
    """
    Return average snap % per player over recent weeks.
    """
    snaps = fetch_snap_counts(seasons)
    if snaps.empty:
        return pd.DataFrame()

    # Column name may be 'offense_pct' or 'offense_snap_pct' depending on source
    pct_col = "offense_pct" if "offense_pct" in snaps.columns else None
    if pct_col is None:
        return pd.DataFrame()

    snaps_sorted = snaps.sort_values(["season", "week"], ascending=False)
    recent = snaps_sorted.groupby("player").head(recent_weeks)

    grouped = (
        recent
        .groupby(["player", "team", "position"], as_index=False)
        .agg(avg_snap_pct=(pct_col, "mean"))
    )
    return grouped


def get_game_context(
    seasons: list[int],
    team: str,
    opponent: str,
) -> dict:
    """
    Return Vegas context for the most recent game involving team vs opponent.
    """
    schedules = fetch_schedules(seasons)
    if schedules.empty:
        return {}

    team_nfl = normalize_team(team, "to_nfl")
    opp_nfl  = normalize_team(opponent, "to_nfl")

    mask = (
        ((schedules["home_team"] == team_nfl) & (schedules["away_team"] == opp_nfl)) |
        ((schedules["away_team"] == team_nfl) & (schedules["home_team"] == opp_nfl))
    )
    games = schedules[mask].sort_values(["season", "week"], ascending=False)

    if games.empty:
        return {}

    game    = games.iloc[0]
    is_home = game["home_team"] == team_nfl

    total  = float(game["total_line"])  if pd.notna(game.get("total_line"))  else None
    spread = float(game["spread_line"]) if pd.notna(game.get("spread_line")) else None

    implied = None
    if total is not None and spread is not None:
        implied = round((total - spread) / 2, 1) if is_home else round((total + spread) / 2, 1)

    return {
        "total_line":    total,
        "spread_line":   spread,
        "is_home":       is_home,
        "implied_total": implied,
    }
