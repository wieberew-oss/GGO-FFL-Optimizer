"""
data/nflverse.py
----------------
Fetches and caches NFL player stats, snap counts, and schedules.

All data is fetched directly from the nflverse CDN (GitHub releases).
No nfl-data-py dependency required — works with standard pandas + pyarrow.

  - Weekly stats:  stats_player release  (stats_player_week_{year}.parquet)
  - Snap counts:   snap_counts release   (snap_counts_{year}.parquet)
  - Schedules:     schedules release     (games.parquet — all seasons)

All data is cached in memory per session. Call clear_cache() to reset.
"""

from __future__ import annotations

import warnings
from typing import Optional

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*Downcasting.*")

# ---------------------------------------------------------------------------
# CDN base URLs
# ---------------------------------------------------------------------------
_CDN_STATS = "https://github.com/nflverse/nflverse-data/releases/download/stats_player"
_CDN_SNAPS = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts"
_CDN_SCHED = "https://github.com/nflverse/nflverse-data/releases/download/schedules"

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_cache: dict = {}


def clear_cache() -> None:
    """Clear all cached nflverse data."""
    _cache.clear()


def is_available() -> bool:
    """Always True — we use direct CDN fetches, no extra dependency needed."""
    return True


# ---------------------------------------------------------------------------
# Team abbreviation normalization
# DraftKings uses slightly different abbreviations in some cases.
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
# Weekly stats
# ---------------------------------------------------------------------------
def _fetch_cdn_weekly(season: int) -> pd.DataFrame:
    """
    Fetch one season of weekly player stats from the nflverse CDN.
    Normalizes column names to a consistent schema.
    """
    url = f"{_CDN_STATS}/stats_player_week_{season}.parquet"
    df = pd.read_parquet(url, engine="auto")

    # Normalize column names
    if "team" in df.columns and "recent_team" not in df.columns:
        df = df.rename(columns={"team": "recent_team"})
    if "passing_interceptions" in df.columns and "interceptions" not in df.columns:
        df = df.rename(columns={"passing_interceptions": "interceptions"})
    if "season_type" not in df.columns:
        df["season_type"] = "REG"

    return df


def fetch_weekly_stats(seasons: list[int]) -> pd.DataFrame:
    """
    Return weekly player stats for the given seasons.
    Each season is cached individually after first fetch.
    Seasons that return 404 are skipped silently.
    """
    frames = []
    for season in seasons:
        cache_key = ("weekly", season)
        if cache_key in _cache:
            frames.append(_cache[cache_key])
            continue

        try:
            df = _fetch_cdn_weekly(season)
        except Exception:
            continue  # season not available — skip silently

        # Keep regular season + playoffs only
        if "season_type" in df.columns:
            df = df[df["season_type"].isin(["REG", "POST"])].copy()

        # Guard against alternative leagues if schema supports it
        if "league" in df.columns:
            df = df[df["league"].str.upper() == "NFL"].copy()

        if "recent_team" in df.columns:
            df["recent_team"] = df["recent_team"].apply(
                lambda t: normalize_team(str(t), "to_nfl")
            )
        if "opponent_team" in df.columns:
            df["opponent_team"] = df["opponent_team"].apply(
                lambda t: normalize_team(str(t), "to_nfl")
            )

        _cache[cache_key] = df
        frames.append(df)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Snap counts
# ---------------------------------------------------------------------------
def fetch_snap_counts(seasons: list[int]) -> pd.DataFrame:
    """
    Return snap count data for the given seasons.
    """
    frames = []
    for season in seasons:
        cache_key = ("snaps", season)
        if cache_key in _cache:
            frames.append(_cache[cache_key])
            continue

        try:
            url = f"{_CDN_SNAPS}/snap_counts_{season}.parquet"
            df = pd.read_parquet(url, engine="auto")
        except Exception:
            continue

        if "team" in df.columns:
            df["team"] = df["team"].apply(lambda t: normalize_team(str(t), "to_nfl"))

        _cache[cache_key] = df
        frames.append(df)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
def fetch_schedules(seasons: list[int]) -> pd.DataFrame:
    """
    Return schedule/Vegas line data.
    Uses a single combined games.parquet that covers all seasons.
    """
    cache_key = ("schedules_all",)
    if cache_key not in _cache:
        try:
            url = f"{_CDN_SCHED}/games.parquet"
            df = pd.read_parquet(url, engine="auto")
        except Exception:
            return pd.DataFrame()

        if "home_team" in df.columns:
            df["home_team"] = df["home_team"].apply(
                lambda t: normalize_team(str(t), "to_nfl")
            )
        if "away_team" in df.columns:
            df["away_team"] = df["away_team"].apply(
                lambda t: normalize_team(str(t), "to_nfl")
            )

        _cache[cache_key] = df

    all_games = _cache[cache_key]
    if seasons and "season" in all_games.columns:
        return all_games[all_games["season"].isin(seasons)].copy()
    return all_games


# ---------------------------------------------------------------------------
# Aggregated stats helpers
# ---------------------------------------------------------------------------
def get_player_recent_stats(
    seasons: list[int],
    recent_weeks: int = 4,
    position_filter: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Return per-player averaged stats for the most recent N weeks across seasons.
    Uses gsis_id as the primary tracking key to prevent cross-league/name collisions.
    """
    weekly = fetch_weekly_stats(seasons)
    if weekly.empty:
        return pd.DataFrame()

    weekly_sorted = weekly.sort_values(["season", "week"], ascending=False)
    
    # Identify unique player key
    id_col = "gsis_id" if "gsis_id" in weekly_sorted.columns else "player_display_name"
    
    recent = weekly_sorted.groupby(id_col).head(recent_weeks)

    if position_filter:
        recent = recent[recent["position"].isin(position_filter)]

    # Map source columns to output names — handles both schema variants
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
        "interceptions":               "avg_interceptions",
        "passing_interceptions":       "avg_interceptions",
    }

    avg_cols = {}
    seen = set()
    for src, dst in col_candidates.items():
        if src in recent.columns and dst not in seen:
            avg_cols[src] = dst
            seen.add(dst)

    agg_dict = {k: "mean" for k in avg_cols}
    agg_dict["week"] = "count"
    agg_dict["player_display_name"] = "first"
    agg_dict["position"] = "first"

    team_col = "recent_team" if "recent_team" in recent.columns else "team"

    grouped = (
        recent
        .groupby([id_col, team_col], as_index=False)
        .agg(agg_dict)
        .rename(columns={**avg_cols, "week": "games_played", team_col: "recent_team"})
    )
    return grouped


def get_snap_pct_recent(
    seasons: list[int],
    recent_weeks: int = 4,
) -> pd.DataFrame:
    """Return average snap % per player over recent weeks."""
    snaps = fetch_snap_counts(seasons)
    if snaps.empty:
        return pd.DataFrame()

    pct_col = "offense_pct" if "offense_pct" in snaps.columns else None
    if pct_col is None:
        return pd.DataFrame()

    snaps_sorted = snaps.sort_values(["season", "week"], ascending=False)
    recent = snaps_sorted.groupby("player").head(recent_weeks)

    return (
        recent
        .groupby(["player", "team", "position"], as_index=False)
        .agg(avg_snap_pct=(pct_col, "mean"))
    )


def get_game_context(
    seasons: list[int],
    team: str,
    opponent: str,
) -> dict:
    """Return Vegas context for the most recent game between team and opponent."""
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
    total   = float(game["total_line"])  if pd.notna(game.get("total_line"))  else None
    spread  = float(game["spread_line"]) if pd.notna(game.get("spread_line")) else None

    implied = None
    if total is not None and spread is not None:
        implied = round((total - spread) / 2, 1) if is_home else round((total + spread) / 2, 1)

    return {
        "total_line":    total,
        "spread_line":   spread,
        "is_home":       is_home,
        "implied_total": implied,
    }