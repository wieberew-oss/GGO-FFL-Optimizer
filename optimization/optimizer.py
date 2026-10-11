"""
optimizer.py
------------
Lineup optimizer for the weekly DFS salary-cap format.

Roster requirements:
    QB   = 1
    RB   = 2
    WR   = 3
    TE   = 1
    FLEX = 1  (RB, WR, or TE)
    DST  = 1
    Total = 9 players
    Salary cap = $50,000
    At least 2 different NFL games (Classic rule)

Uses PuLP (integer linear programming) to find optimal lineups.
Supports multiple strategies, stacking, and multi-lineup diversity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple

import pulp

from models.player import Player

SALARY_CAP = 50_000

SLOT_REQUIREMENTS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
    "DST": 1,
}

FLEX_ELIGIBLE = {"RB", "WR", "TE"}

VALID_STRATEGIES = {
    "best_projected",
    "best_value",
    "high_floor",
    "high_ceiling",
    "contrarian",
}


@dataclass
class OptimizationResult:
    lineup: List[Tuple[Player, str]]          # (Player, assigned_slot)
    total_salary: int
    total_projection: float
    strategy: str
    feasible: bool
    message: str = ""
    enriched_stats: dict = field(default_factory=dict)
    player_projections: dict = field(default_factory=dict)
    matchup_adjustments: dict = field(default_factory=dict)
    projection_mode: str = "adjusted"
    total_floor: float = 0.0
    total_ceiling: float = 0.0
    games_used: int = 0

    def to_display_rows(self) -> list:
        rows = []
        for player, slot in self.lineup:
            ps = self.enriched_stats.get(player.dk_id)
            if player.dk_id in self.player_projections:
                adj_proj = f"{self.player_projections[player.dk_id]:.1f}"
            elif ps and getattr(ps, "adjusted_projection", None) is not None:
                adj_proj = f"{ps.adjusted_projection:.1f}"
            else:
                adj_proj = f"{player.projection:.1f}"

            source = getattr(ps, "data_source", "dk_only") if ps else "dk_only"
            source_icon = {"enriched": "★", "vegas_only": "◆", "dk_only": "·"}.get(source, "·")

            vegas_adjustment = getattr(ps, "vegas_adjustment", None) if ps else None
            vegas_delta = (
                "Not applied" if self.projection_mode == "dk_only"
                else f"{vegas_adjustment:+.1f}" if vegas_adjustment is not None
                else "—"
            )

            floor_str = f"{player.floor:.1f}" if player.floor is not None else "—"
            ceil_str = f"{player.ceiling:.1f}" if player.ceiling is not None else "—"

            rows.append({
                "Slot":     slot,
                "Player":   player.name,
                "Pos":      player.position,
                "Team":     player.team,
                "Opp":      player.opponent,
                "Salary":   f"${player.salary:,}",
                "Proj":     adj_proj,
                "Floor":    floor_str,
                "Ceiling":  ceil_str,
                "Vegas Δ":  vegas_delta,
                "Defense Δ": "Not applied" if self.projection_mode == "dk_only"
                             else f"{self.matchup_adjustments.get(player.dk_id, 0.0):+.1f}",
                "DK Avg":   f"{player.projection:.1f}",
                "Value":    f"{player.value:.2f}" if player.value is not None else "—",
                "Status":   player.status if player.status else "OK",
                "Data":     source_icon,
                "Game":     player.game_key,
            })

        rows.append({
            "Slot":   "TOTAL",
            "Player": "",
            "Pos":    "",
            "Team":   "",
            "Opp":    "",
            "Salary": f"${self.total_salary:,}",
            "Proj":   f"{self.total_projection:.1f}",
            "Floor":  f"{self.total_floor:.1f}" if self.total_floor else "—",
            "Ceiling": f"{self.total_ceiling:.1f}" if self.total_ceiling else "—",
            "Vegas Δ": "Not applied" if self.projection_mode == "dk_only" else "—",
            "Defense Δ": "Not applied" if self.projection_mode == "dk_only"
                         else f"{sum(self.matchup_adjustments.get(p.dk_id, 0.0) for p, _ in self.lineup):+.1f}",
            "DK Avg": "",
            "Value":  "",
            "Status": "",
            "Data":   "",
            "Game":   f"{self.games_used} games",
        })
        return rows

    def to_dk_export_rows(self) -> list:
        """Return rows in a simple DraftKings-style upload format."""
        slot_map = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "FLEX": "FLEX", "DST": "DST"}
        rows = []
        for player, slot in self.lineup:
            rows.append({
                "Position": slot_map.get(slot, slot),
                "Name + ID": f"{player.name} ({player.dk_id})",
                "Name": player.name,
                "ID": player.dk_id,
                "Roster Position": "/".join(player.roster_slots),
                "Salary": player.salary,
                "Game Info": player.game_info,
                "TeamAbbrev": player.team,
                "AvgPointsPerGame": player.projection,
                "Status": player.status,
            })
        return rows


def effective_projection(
    player: Player,
    enriched_stats: Optional[dict] = None,
    matchup_multiplier: float = 1.0,
) -> float:
    """Return the player's point projection after enrichment and matchup scaling."""
    enriched_stats = enriched_stats or {}
    ps = enriched_stats.get(player.dk_id)
    base = (
        ps.adjusted_projection
        if ps is not None and getattr(ps, "adjusted_projection", None) is not None
        else player.projection
    )
    return base * matchup_multiplier


def _get_floor(player: Player, enriched_stats: Optional[dict], proj: float) -> float:
    if player.floor is not None:
        return player.floor
    ps = (enriched_stats or {}).get(player.dk_id)
    if ps and getattr(ps, "floor", None) is not None:
        return ps.floor
    # Heuristic: ~70% of projection as a conservative floor
    return round(proj * 0.70, 2)


def _get_ceiling(player: Player, enriched_stats: Optional[dict], proj: float) -> float:
    if player.ceiling is not None:
        return player.ceiling
    ps = (enriched_stats or {}).get(player.dk_id)
    if ps and getattr(ps, "ceiling", None) is not None:
        return ps.ceiling
    # Heuristic: ~140% of projection as ceiling
    return round(proj * 1.40, 2)


def _build_objective_value(
    player: Player,
    strategy: str,
    projection: float,
    floor: float,
    ceiling: float,
) -> float:
    """Convert projections into the optimizer objective for a given strategy."""
    if strategy == "best_value":
        return (projection / (player.salary / 1000)) if player.salary > 0 else 0.0
    if strategy == "high_floor":
        return floor
    if strategy == "high_ceiling":
        return ceiling
    if strategy == "contrarian":
        # Prefer high ceiling relative to salary (upside per dollar)
        return (ceiling / (player.salary / 1000)) if player.salary > 0 else 0.0
    # best_projected (default)
    return projection


def optimize(
    players: List[Player],
    strategy: str = "best_projected",
    exclude_names: Optional[Set[str]] = None,
    lock_names: Optional[Set[str]] = None,
    exclude_injured: bool = True,
    exclude_questionable: bool = False,
    min_salary: int = 0,
    enriched_stats: Optional[dict] = None,
    matchup_multipliers: Optional[dict] = None,
    projection_mode: str = "adjusted",
    require_min_games: int = 2,
    stack_qb_with_receiver: bool = False,
    max_from_same_team: Optional[int] = None,
    previously_used_ids: Optional[Set[int]] = None,
    uniqueness_penalty: float = 0.0,
) -> OptimizationResult:
    """
    Find the optimal lineup given the player pool and constraints.

    New parameters
    --------------
    require_min_games       : Minimum number of distinct games (Classic rule = 2)
    stack_qb_with_receiver  : If True, force at least one WR/TE from the same team as the QB
    max_from_same_team      : Optional hard cap on players from one NFL team
    previously_used_ids     : Player IDs already used in prior lineups (for diversity)
    uniqueness_penalty      : Soft penalty subtracted from objective for previously used players
    """
    exclude_names = exclude_names or set()
    lock_names = lock_names or set()
    enriched_stats = enriched_stats or {}
    matchup_multipliers = matchup_multipliers or {}
    previously_used_ids = previously_used_ids or set()

    if strategy not in VALID_STRATEGIES:
        strategy = "best_projected"

    # Filter player pool
    pool: List[Player] = []
    for p in players:
        if p.name in exclude_names:
            continue
        if exclude_injured and not p.is_available:
            continue
        if exclude_questionable and p.status == "Q":
            continue
        pool.append(p)

    if len(pool) < 9:
        return OptimizationResult(
            lineup=[],
            total_salary=0,
            total_projection=0.0,
            strategy=strategy,
            feasible=False,
            message="Not enough eligible players in pool to fill a lineup.",
        )

    # -----------------------------------------------------------------------
    # Build the ILP
    # -----------------------------------------------------------------------
    prob = pulp.LpProblem("FFL_Optimizer", pulp.LpMaximize)

    n = len(pool)
    indices = range(n)

    x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in indices]
    flex = [pulp.LpVariable(f"flex_{i}", cat="Binary") for i in indices]

    # Projections
    if projection_mode not in {"dk_only", "adjusted"}:
        raise ValueError("projection_mode must be 'dk_only' or 'adjusted'")

    effective_stats = {} if projection_mode == "dk_only" else enriched_stats
    base_projections = {
        p.dk_id: effective_projection(p, effective_stats)
        for p in pool
    }
    player_projections = {
        p.dk_id: base_projections[p.dk_id] * (
            1.0 if projection_mode == "dk_only" else matchup_multipliers.get(p.dk_id, 1.0)
        )
        for p in pool
    }
    matchup_adjustments = {
        p.dk_id: player_projections[p.dk_id] - base_projections[p.dk_id]
        for p in pool
    }

    floors = {
        p.dk_id: _get_floor(p, effective_stats, player_projections[p.dk_id])
        for p in pool
    }
    ceilings = {
        p.dk_id: _get_ceiling(p, effective_stats, player_projections[p.dk_id])
        for p in pool
    }

    # Objective
    obj_terms = []
    for i, p in enumerate(pool):
        val = _build_objective_value(
            p, strategy,
            player_projections[p.dk_id],
            floors[p.dk_id],
            ceilings[p.dk_id],
        )
        if p.dk_id in previously_used_ids and uniqueness_penalty > 0:
            val -= uniqueness_penalty
        obj_terms.append(val * x[i])
    prob += pulp.lpSum(obj_terms), "Objective"

    # -----------------------------------------------------------------------
    # Constraints
    # -----------------------------------------------------------------------

    # Roster size
    prob += pulp.lpSum(x[i] for i in indices) == 9, "Roster_Size"

    # Salary cap
    prob += pulp.lpSum(pool[i].salary * x[i] for i in indices) <= SALARY_CAP, "Salary_Cap"

    if min_salary > 0:
        prob += pulp.lpSum(pool[i].salary * x[i] for i in indices) >= min_salary, "Min_Salary"

    # Primary slot requirements (non-FLEX)
    for slot, count in SLOT_REQUIREMENTS.items():
        eligible = [i for i in indices if slot in pool[i].roster_slots]
        prob += (
            pulp.lpSum(x[i] - flex[i] for i in eligible) == count,
            f"Slot_{slot}",
        )

    # Exactly 1 FLEX
    prob += pulp.lpSum(flex[i] for i in indices) == 1, "Exactly_One_FLEX"

    for i in indices:
        prob += flex[i] <= x[i], f"FLEX_selected_{i}"
        if pool[i].position not in FLEX_ELIGIBLE:
            prob += flex[i] == 0, f"FLEX_ineligible_{i}"

    # Lock constraints
    for name in lock_names:
        locked = False
        for i, p in enumerate(pool):
            if p.name == name:
                prob += x[i] == 1, f"Lock_{name.replace(' ', '_')}_{i}"
                locked = True
                break
        if not locked:
            # Locked player not in eligible pool — will make problem infeasible
            pass

    # ----- Multi-game constraint (Classic rule: ≥ 2 games) -----
    if require_min_games and require_min_games > 1:
        game_to_indices: Dict[str, List[int]] = defaultdict(list)
        for i, p in enumerate(pool):
            game_to_indices[p.game_key].append(i)

        game_vars = []
        for g_idx, (g, idxs) in enumerate(game_to_indices.items()):
            gv = pulp.LpVariable(f"game_{g_idx}", cat="Binary")
            game_vars.append(gv)
            # If any player from this game is selected → game is used
            for i in idxs:
                prob += x[i] <= gv, f"game_link_{g_idx}_{i}"
            # Optional: prevent a single game from being forced without players
            # (already handled by the links above)

        prob += pulp.lpSum(game_vars) >= require_min_games, "Min_Games"

    # ----- Optional stacking: QB + at least one pass-catcher -----
    if stack_qb_with_receiver:
        qb_indices = [i for i, p in enumerate(pool) if p.position == "QB"]
        for qi in qb_indices:
            qb = pool[qi]
            same_team_receivers = [
                i for i, p in enumerate(pool)
                if p.team == qb.team and p.position in {"WR", "TE"}
            ]
            if same_team_receivers:
                # If this QB is selected, at least one same-team WR/TE must be selected
                prob += (
                    pulp.lpSum(x[i] for i in same_team_receivers) >= x[qi],
                    f"Stack_QB_{qi}",
                )

    # ----- Optional max players from same team -----
    if max_from_same_team is not None and max_from_same_team > 0:
        team_to_indices: Dict[str, List[int]] = defaultdict(list)
        for i, p in enumerate(pool):
            team_to_indices[p.team].append(i)
        for team, idxs in team_to_indices.items():
            if len(idxs) > max_from_same_team:
                prob += (
                    pulp.lpSum(x[i] for i in idxs) <= max_from_same_team,
                    f"MaxTeam_{team}",
                )

    # -----------------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------------
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=30)
    status_code = prob.solve(solver)
    status = pulp.LpStatus.get(status_code, "Unknown")

    if status != "Optimal":
        return OptimizationResult(
            lineup=[],
            total_salary=0,
            total_projection=0.0,
            strategy=strategy,
            feasible=False,
            message=(
                f"Optimizer could not find a valid lineup (status: {status}). "
                "Try relaxing locks, exclusions, stacking, or min-games constraints."
            ),
        )

    # -----------------------------------------------------------------------
    # Build result
    # -----------------------------------------------------------------------
    selected = [
        (pool[i], round(flex[i].varValue or 0))
        for i in indices
        if round(x[i].varValue or 0) == 1
    ]

    lineup: List[Tuple[Player, str]] = []
    slot_counts = {s: 0 for s in SLOT_REQUIREMENTS}

    # Assign primary slots first
    for player, is_flex in selected:
        if is_flex:
            continue
        for slot in ["QB", "RB", "WR", "TE", "DST"]:
            if slot in player.roster_slots and slot_counts[slot] < SLOT_REQUIREMENTS[slot]:
                lineup.append((player, slot))
                slot_counts[slot] += 1
                break

    # Assign FLEX
    for player, is_flex in selected:
        if is_flex:
            lineup.append((player, "FLEX"))

    slot_order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "FLEX": 4, "DST": 5}
    lineup.sort(key=lambda t: (slot_order.get(t[1], 99), t[0].name))

    total_salary = sum(p.salary for p, _ in lineup)
    total_projection = sum(player_projections[p.dk_id] for p, _ in lineup)
    total_floor = sum(floors[p.dk_id] for p, _ in lineup)
    total_ceiling = sum(ceilings[p.dk_id] for p, _ in lineup)
    games_used = len({p.game_key for p, _ in lineup})

    return OptimizationResult(
        lineup=lineup,
        total_salary=total_salary,
        total_projection=round(total_projection, 2),
        strategy=strategy,
        feasible=True,
        enriched_stats=effective_stats,
        player_projections=player_projections,
        matchup_adjustments=matchup_adjustments,
        projection_mode=projection_mode,
        total_floor=round(total_floor, 2),
        total_ceiling=round(total_ceiling, 2),
        games_used=games_used,
    )


def optimize_multiple_lineups(
    players: List[Player],
    n_lineups: int = 3,
    strategy: str = "best_projected",
    exclude_names: Optional[Set[str]] = None,
    lock_names: Optional[Set[str]] = None,
    exclude_injured: bool = True,
    exclude_questionable: bool = False,
    enriched_stats: Optional[dict] = None,
    matchup_multipliers: Optional[dict] = None,
    projection_mode: str = "adjusted",
    require_min_games: int = 2,
    stack_qb_with_receiver: bool = False,
    max_from_same_team: Optional[int] = None,
    uniqueness_penalty: float = 5.0,
) -> List[OptimizationResult]:
    """
    Generate multiple diverse lineups by iteratively penalizing previously used players.
    """
    results: List[OptimizationResult] = []
    used_ids: Set[int] = set()

    for _ in range(max(1, n_lineups)):
        res = optimize(
            players,
            strategy=strategy,
            exclude_names=exclude_names,
            lock_names=lock_names,
            exclude_injured=exclude_injured,
            exclude_questionable=exclude_questionable,
            enriched_stats=enriched_stats,
            matchup_multipliers=matchup_multipliers,
            projection_mode=projection_mode,
            require_min_games=require_min_games,
            stack_qb_with_receiver=stack_qb_with_receiver,
            max_from_same_team=max_from_same_team,
            previously_used_ids=used_ids,
            uniqueness_penalty=uniqueness_penalty,
        )
        if not res.feasible:
            break
        results.append(res)
        for p, _ in res.lineup:
            used_ids.add(p.dk_id)

    return results


def optimize_multiple(
    players: list,
    strategies: Optional[list] = None,
    exclude_injured: bool = True,
    exclude_questionable: bool = False,
    enriched_stats: Optional[dict] = None,
) -> dict:
    """Run several strategies and return results keyed by strategy name."""
    if strategies is None:
        strategies = ["best_projected", "best_value", "high_floor", "high_ceiling"]

    results = {}
    for strategy in strategies:
        results[strategy] = optimize(
            players,
            strategy=strategy,
            exclude_injured=exclude_injured,
            exclude_questionable=exclude_questionable,
            enriched_stats=enriched_stats,
        )
    return results
