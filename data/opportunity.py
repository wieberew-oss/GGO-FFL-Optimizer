"""
data/opportunity.py
----------------
Detect role-elevation opportunities: backups who should see a larger
workload because a higher-usage teammate at the same position is OUT/IR
(optionally Q).

Uses DK injury status plus usage proxies from nflverse enrichment when
available (carries / targets / snap %). Falls back to DK AvgPointsPerGame
as a starter proxy when stats are missing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from models.player import Player

# Positions where depth-chart hierarchy is meaningful for DFS
ELEVATION_POSITIONS = {"RB", "WR", "TE"}

DEFAULT_BOOST = 0.35  # +35% — middle of the 25–50% band
MIN_BOOST = 0.25
MAX_BOOST = 0.50


@dataclass
class RoleElevation:
    """One player elevated because a teammate ahead of them is unavailable."""

    dk_id: int
    player_name: str
    position: str
    team: str
    rank: int  # 1-based usage rank among teammates at this position
    ahead_name: str
    ahead_status: str
    usage_score: float
    reason: str

    def to_badge(self) -> str:
        return "🟢 OPP"

    def to_short(self) -> str:
        return f"{self.ahead_name} ({self.ahead_status})"


def _injured_statuses(include_questionable: bool) -> Set[str]:
    statuses = {"OUT", "IR"}
    if include_questionable:
        statuses.add("Q")
    return statuses


def _usage_score(
    player: Player,
    enriched_stats: Optional[dict],
) -> float:
    """
    Higher = more of a 'starter' role historically.
    Prefer volume metrics that predict who sits above whom on the depth chart.
    """
    ps = (enriched_stats or {}).get(player.dk_id)
    pos = player.position

    if ps is not None:
        if pos == "RB":
            carries = getattr(ps, "avg_carries", None)
            snap = getattr(ps, "avg_snap_pct", None)
            if carries is not None and carries > 0:
                return float(carries) * 10.0 + (float(snap or 0) * 5.0)
            if snap is not None:
                return float(snap) * 100.0
        elif pos in {"WR", "TE"}:
            targets = getattr(ps, "avg_targets", None)
            tgt_share = getattr(ps, "avg_target_share", None)
            snap = getattr(ps, "avg_snap_pct", None)
            if targets is not None and targets > 0:
                return float(targets) * 10.0 + (float(tgt_share or 0) * 50.0)
            if tgt_share is not None:
                return float(tgt_share) * 100.0
            if snap is not None:
                return float(snap) * 80.0

    # Fallback: DK season average as a coarse starter proxy
    return float(player.projection or 0.0)


def detect_role_elevations(
    players: List[Player],
    enriched_stats: Optional[dict] = None,
    include_questionable: bool = False,
    positions: Optional[Set[str]] = None,
) -> Dict[int, RoleElevation]:
    """
    Return map of dk_id -> RoleElevation for available players who sit
    behind at least one unavailable higher-usage teammate at the same position.
    """
    positions = positions or ELEVATION_POSITIONS
    injured = _injured_statuses(include_questionable)
    enriched_stats = enriched_stats or {}

    # Group by team + position
    groups: Dict[tuple, List[Player]] = defaultdict(list)
    for p in players:
        if p.position not in positions:
            continue
        if not p.team:
            continue
        groups[(p.team.upper(), p.position)].append(p)

    results: Dict[int, RoleElevation] = {}

    for (team, pos), group in groups.items():
        # Rank everyone by usage (descending)
        ranked = sorted(
            group,
            key=lambda pl: _usage_score(pl, enriched_stats),
            reverse=True,
        )

        for idx, candidate in enumerate(ranked):
            # Only elevate players who can actually play
            if candidate.status in {"OUT", "IR"}:
                continue

            rank = idx + 1  # 1 = highest usage
            if rank == 1:
                continue  # already the top usage player; no one "above"

            # Anyone ranked strictly above this candidate who is injured?
            ahead_injured = [
                pl for pl in ranked[:idx]
                if pl.status in injured
            ]
            if not ahead_injured:
                continue

            # Primary reason: highest-usage injured teammate above them
            primary = ahead_injured[0]
            reason = (
                f"{primary.name} ({primary.status or 'OUT'}) unavailable — "
                f"{candidate.name} elevated at {pos} ({team})"
            )
            results[candidate.dk_id] = RoleElevation(
                dk_id=candidate.dk_id,
                player_name=candidate.name,
                position=pos,
                team=team,
                rank=rank,
                ahead_name=primary.name,
                ahead_status=primary.status or "OUT",
                usage_score=_usage_score(candidate, enriched_stats),
                reason=reason,
            )

    return results


def role_elevation_multipliers(
    elevations: Dict[int, RoleElevation],
    enabled: bool,
    boost: float = DEFAULT_BOOST,
) -> Dict[int, float]:
    """
    Map dk_id -> multiplier (1.0 + boost) for elevated players when enabled.
    boost is fractional (0.35 = +35%). Clamped to [MIN_BOOST, MAX_BOOST] when enabled.
    """
    if not enabled or not elevations:
        return {}
    boost = max(MIN_BOOST, min(MAX_BOOST, float(boost)))
    mult = 1.0 + boost
    return {dk_id: mult for dk_id in elevations}


def combine_multipliers(
    defense_mults: Dict[int, float],
    role_mults: Dict[int, float],
) -> Dict[int, float]:
    """Element-wise product of defense and role-elevation multipliers."""
    keys = set(defense_mults) | set(role_mults)
    return {
        k: float(defense_mults.get(k, 1.0)) * float(role_mults.get(k, 1.0))
        for k in keys
    }
