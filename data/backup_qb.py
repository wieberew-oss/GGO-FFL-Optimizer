"""
data/backup_qb.py
-----------------
Detect teams starting a backup QB (QB1 OUT/IR, optionally Q) and produce
discount multipliers for that team's pass-catchers.

Top-usage QB on the team who is unavailable → remaining QBs are "backup starts".
WR/TE (and optionally the backup QB himself) get a projection haircut.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from models.player import Player

DEFAULT_WR_TE_DISCOUNT = 0.15   # -15% on pass catchers
DEFAULT_QB_DISCOUNT = 0.10      # -10% on the backup QB projection itself
MIN_DISCOUNT = 0.05
MAX_DISCOUNT = 0.30


@dataclass
class BackupQBContext:
    team: str
    starter_out: str
    starter_status: str
    backup_qb_name: str
    backup_qb_id: int


def _injured(include_q: bool) -> Set[str]:
    s = {"OUT", "IR"}
    if include_q:
        s.add("Q")
    return s


def detect_backup_qb_starts(
    players: List[Player],
    include_questionable: bool = False,
) -> Dict[str, BackupQBContext]:
    """
    Returns map team -> BackupQBContext for teams whose highest-projection
    QB is unavailable and another QB on the roster is available.
    """
    injured = _injured(include_questionable)
    by_team: Dict[str, List[Player]] = defaultdict(list)
    for p in players:
        if p.position == "QB" and p.team:
            by_team[p.team.upper()].append(p)

    results: Dict[str, BackupQBContext] = {}
    for team, qbs in by_team.items():
        ranked = sorted(qbs, key=lambda q: float(q.projection or 0), reverse=True)
        if len(ranked) < 2:
            continue
        top = ranked[0]
        if top.status not in injured:
            continue
        # First available lower-ranked QB is the presumed starter
        backup = next((q for q in ranked[1:] if q.status not in {"OUT", "IR"}), None)
        if backup is None:
            continue
        results[team] = BackupQBContext(
            team=team,
            starter_out=top.name,
            starter_status=top.status or "OUT",
            backup_qb_name=backup.name,
            backup_qb_id=backup.dk_id,
        )
    return results


def backup_qb_multipliers(
    players: List[Player],
    contexts: Dict[str, BackupQBContext],
    enabled: bool,
    wr_te_discount: float = DEFAULT_WR_TE_DISCOUNT,
    qb_discount: float = DEFAULT_QB_DISCOUNT,
) -> Dict[int, float]:
    """
    Map dk_id -> multiplier (< 1.0) for players hurt by a backup QB start.
    """
    if not enabled or not contexts:
        return {}
    wr_te_discount = max(MIN_DISCOUNT, min(MAX_DISCOUNT, float(wr_te_discount)))
    qb_discount = max(MIN_DISCOUNT, min(MAX_DISCOUNT, float(qb_discount)))
    wr_te_mult = 1.0 - wr_te_discount
    qb_mult = 1.0 - qb_discount

    mults: Dict[int, float] = {}
    for p in players:
        team = (p.team or "").upper()
        ctx = contexts.get(team)
        if not ctx:
            continue
        if p.position in {"WR", "TE"}:
            mults[p.dk_id] = wr_te_mult
        elif p.position == "QB" and p.dk_id == ctx.backup_qb_id:
            mults[p.dk_id] = qb_mult
    return mults
