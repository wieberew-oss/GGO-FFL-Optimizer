"""
data/game_script.py
-------------------
Wide-spread game-script adjustments (|spread| > threshold).

Heavy favorite (team spread <= -threshold):
  RB elevated; QB/WR/TE mildly discounted (clock-killing script).

Heavy underdog (team spread >= +threshold):
  RB discounted (run abandoned); QB/WR/TE mildly elevated (pass to catch up).
  Pass boost is muted when opponent is a top-tier pass defense
  (DvP rank 25-32 = toughest).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from models.player import Player

DEFAULT_THRESHOLD = 7.0

# Multipliers relative to 1.0
FAV_RB = 1.08
FAV_PASS = 0.96
DOG_RB = 0.90
DOG_PASS = 1.06
DOG_PASS_VS_ELITE = 1.03  # muted boost vs top pass D


def team_spread_from_stats(spread_line: Optional[float], is_home: Optional[bool]) -> Optional[float]:
    """
    Convert nflverse home-centric spread_line into this team's spread.
    Negative = team is favored; positive = team is underdog.
    """
    if spread_line is None or is_home is None:
        return None
    try:
        s = float(spread_line)
    except (TypeError, ValueError):
        return None
    return s if is_home else -s


def game_script_multipliers(
    players: List[Player],
    enriched_stats: Optional[dict],
    enabled: bool,
    threshold: float = DEFAULT_THRESHOLD,
    def_rank_by_player: Optional[Dict[int, Optional[int]]] = None,
) -> Dict[int, float]:
    """
    Return dk_id -> multiplier for wide-spread script effects.

    def_rank_by_player: optional map of player dk_id -> opponent DvP rank
      (1 = softest / most pts allowed, 32 = toughest). Underdog pass boost is
      muted when rank >= 25 (top-tier shutdown pass defense).
    """
    if not enabled:
        return {}

    enriched_stats = enriched_stats or {}
    def_rank_by_player = def_rank_by_player or {}
    threshold = abs(float(threshold))
    mults: Dict[int, float] = {}

    for p in players:
        if p.position == "DST":
            continue
        ps = enriched_stats.get(p.dk_id)
        if ps is None:
            continue
        team_spread = team_spread_from_stats(
            getattr(ps, "spread_line", None),
            getattr(ps, "is_home", None),
        )
        if team_spread is None:
            continue

        # Heavy favorite
        if team_spread <= -threshold:
            if p.position == "RB":
                mults[p.dk_id] = FAV_RB
            elif p.position in {"QB", "WR", "TE"}:
                mults[p.dk_id] = FAV_PASS
            continue

        # Heavy underdog
        if team_spread >= threshold:
            if p.position == "RB":
                mults[p.dk_id] = DOG_RB
            elif p.position in {"QB", "WR", "TE"}:
                rank = def_rank_by_player.get(p.dk_id)
                # rank 25–32 = toughest pass defenses in our scale
                if rank is not None and rank >= 25:
                    mults[p.dk_id] = DOG_PASS_VS_ELITE
                else:
                    mults[p.dk_id] = DOG_PASS

    return mults


def script_label(team_spread: Optional[float], threshold: float = DEFAULT_THRESHOLD) -> str:
    if team_spread is None:
        return "—"
    if team_spread <= -threshold:
        return f"Fav {team_spread:+.1f}"
    if team_spread >= threshold:
        return f"Dog {team_spread:+.1f}"
    return f"Neutral {team_spread:+.1f}"
