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

Uses PuLP (integer linear programming) to find optimal lineups.
Accepts an optional enriched_stats dict (dk_id -> PlayerStats) produced
by models/projections.py. When provided, adjusted_projection replaces
the raw DK AvgPointsPerGame for the optimizer objective.
"""

from dataclasses import dataclass
from typing import Optional

import pulp

from models.player import Player

SALARY_CAP = 50_000

# Required starters by slot (excluding FLEX)
SLOT_REQUIREMENTS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
    "DST": 1,
}

FLEX_ELIGIBLE = {"RB", "WR", "TE"}


@dataclass
class OptimizationResult:
    lineup: list          # List of (Player, assigned_slot) tuples
    total_salary: int
    total_projection: float
    strategy: str
    feasible: bool
    message: str = ""
    enriched_stats: dict = None   # dk_id -> PlayerStats, passed through for display
    player_projections: dict = None
    matchup_adjustments: dict = None
    projection_mode: str = "adjusted"

    def __post_init__(self):
        if self.enriched_stats is None:
            self.enriched_stats = {}
        if self.player_projections is None:
            self.player_projections = {}
        if self.matchup_adjustments is None:
            self.matchup_adjustments = {}

    def to_display_rows(self) -> list:
        rows = []
        for player, slot in self.lineup:
            ps = self.enriched_stats.get(player.dk_id)
            if player.dk_id in self.player_projections:
                adj_proj = f"{self.player_projections[player.dk_id]:.1f}"
            elif ps and ps.adjusted_projection is not None:
                adj_proj = f"{ps.adjusted_projection:.1f}"
            else:
                adj_proj = f"{player.projection:.1f}"
            source = ps.data_source if ps else "dk_only"
            source_icon = {"enriched": "★", "vegas_only": "◆", "dk_only": "·"}.get(source, "·")
            vegas_adjustment = getattr(ps, "vegas_adjustment", None) if ps else None
            vegas_delta = (
                "Not applied" if self.projection_mode == "dk_only"
                else f"{vegas_adjustment:+.1f}" if vegas_adjustment is not None
                else "—"
            )
            rows.append({
                "Slot":     slot,
                "Player":   player.name,
                "Pos":      player.position,
                "Team":     player.team,
                "Opp":      player.opponent,
                "Salary":   f"${player.salary:,}",
                "Proj":     adj_proj,
                "Vegas Δ": vegas_delta,
                "Defense Δ": "Not applied" if self.projection_mode == "dk_only"
                else f"{self.matchup_adjustments.get(player.dk_id, 0.0):+.1f}",
                "DK Avg":   f"{player.projection:.1f}",
                "Value":    f"{player.value:.2f}",
                "Status":   player.status if player.status else "OK",
                "Data":     source_icon,
            })
        rows.append({
            "Slot":   "TOTAL",
            "Player": "",
            "Pos":    "",
            "Team":   "",
            "Opp":    "",
            "Salary": f"${self.total_salary:,}",
            "Proj":   f"{self.total_projection:.1f}",
            "Vegas Δ": "Not applied" if self.projection_mode == "dk_only" else "—",
            "Defense Δ": "Not applied" if self.projection_mode == "dk_only"
            else f"{sum(self.matchup_adjustments.get(p.dk_id, 0.0) for p, _ in self.lineup):+.1f}",
            "DK Avg": "",
            "Value":  "",
            "Status": "",
            "Data":   "",
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
        if ps is not None and ps.adjusted_projection is not None
        else player.projection
    )
    return base * matchup_multiplier


def _build_projection(player: Player, strategy: str, projection: float) -> float:
    """
    Convert point projections to the optimizer objective for a strategy.
    """
    if strategy == "best_value":
        # Value = adjusted pts per $1k of salary
        return (projection / (player.salary / 1000)) if player.salary > 0 else 0.0

    # best_projected and all others: use adjusted projection directly
    return projection


def optimize(
    players: list,
    strategy: str = "best_projected",
    exclude_names: Optional[set] = None,
    lock_names: Optional[set] = None,
    exclude_injured: bool = True,
    exclude_questionable: bool = False,
    min_salary: int = 0,
    enriched_stats: Optional[dict] = None,
    matchup_multipliers: Optional[dict] = None,
    projection_mode: str = "adjusted",
) -> OptimizationResult:
    """
    Find the optimal lineup given the player pool and constraints.

    Parameters
    ----------
    players              : list of Player objects
    strategy             : one of 'best_projected', 'best_value'
    exclude_names        : set of player names to exclude
    lock_names           : set of player names to force into the lineup
    exclude_injured      : if True, exclude OUT and IR players
    exclude_questionable : if True, exclude players with Q status
    min_salary           : minimum total salary to enforce (default 0)
    enriched_stats       : dict of dk_id -> PlayerStats from projections.py
    projection_mode      : 'dk_only' or 'adjusted'
    """
    exclude_names = exclude_names or set()
    lock_names = lock_names or set()
    enriched_stats = enriched_stats or {}
    matchup_multipliers = matchup_multipliers or {}

    # Filter player pool
    pool = []
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
    # Build the ILP problem
    # -----------------------------------------------------------------------
    prob = pulp.LpProblem("FFL_Optimizer", pulp.LpMaximize)

    n = len(pool)
    indices = range(n)

    # Decision variables: x[i] = 1 if player i is selected
    x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in indices]

    # Slot assignment variables for FLEX
    # flex[i] = 1 if player i fills the FLEX slot
    flex = [pulp.LpVariable(f"flex_{i}", cat="Binary") for i in indices]

    # -----------------------------------------------------------------------
    # Objective: maximize weighted projection
    # -----------------------------------------------------------------------
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
    projections = [_build_projection(p, strategy, player_projections[p.dk_id]) for p in pool]
    prob += pulp.lpSum(projections[i] * x[i] for i in indices), "Total_Projection"

    # -----------------------------------------------------------------------
    # Constraints
    # -----------------------------------------------------------------------

    # Total roster size = 9
    prob += pulp.lpSum(x[i] for i in indices) == 9, "Roster_Size"

    # Salary cap
    prob += pulp.lpSum(pool[i].salary * x[i] for i in indices) <= SALARY_CAP, "Salary_Cap"

    # Minimum salary (optional, helps avoid degenerate low-salary lineups)
    if min_salary > 0:
        prob += pulp.lpSum(pool[i].salary * x[i] for i in indices) >= min_salary, "Min_Salary"

    # Slot requirements: exactly N players per primary position (non-FLEX starters)
    for slot, count in SLOT_REQUIREMENTS.items():
        eligible = [i for i in indices if slot in pool[i].roster_slots and slot != "FLEX"]
        # Players eligible for this slot who are NOT in the flex slot
        prob += (
            pulp.lpSum(x[i] - flex[i] for i in eligible) == count,
            f"Slot_{slot}",
        )

    # Exactly 1 FLEX
    prob += pulp.lpSum(flex[i] for i in indices) == 1, "Exactly_One_FLEX"

    # FLEX must be selected and must be FLEX-eligible
    for i in indices:
        # Can only be in FLEX if selected
        prob += flex[i] <= x[i], f"FLEX_selected_{i}"
        # Can only be in FLEX if eligible
        if pool[i].position not in FLEX_ELIGIBLE:
            prob += flex[i] == 0, f"FLEX_ineligible_{i}"

    # Lock constraints
    for name in lock_names:
        for i, p in enumerate(pool):
            if p.name == name:
                prob += x[i] == 1, f"Lock_{name.replace(' ', '_')}_{i}"

    # -----------------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------------
    solver = pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return OptimizationResult(
            lineup=[],
            total_salary=0,
            total_projection=0.0,
            strategy=strategy,
            feasible=False,
            message=f"Optimizer could not find a valid lineup (status: {status}). "
                    "Try relaxing constraints or check your player pool.",
        )

    # -----------------------------------------------------------------------
    # Build result
    # -----------------------------------------------------------------------
    selected = [(pool[i], round(flex[i].varValue or 0)) for i in indices if round(x[i].varValue or 0) == 1]

    # Assign display slots
    lineup = []
    slot_counts = {s: 0 for s in SLOT_REQUIREMENTS}

    # First pass: assign primary slots to non-FLEX players
    for player, is_flex in selected:
        if is_flex:
            continue
        # Find which primary slot this player fills
        for slot in ["QB", "RB", "WR", "TE", "DST"]:
            if slot in player.roster_slots and slot_counts[slot] < SLOT_REQUIREMENTS[slot]:
                lineup.append((player, slot))
                slot_counts[slot] += 1
                break

    # Second pass: assign FLEX
    for player, is_flex in selected:
        if is_flex:
            lineup.append((player, "FLEX"))

    # Sort by slot order for display
    slot_order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "FLEX": 4, "DST": 5}
    lineup.sort(key=lambda t: (slot_order.get(t[1], 99), t[0].name))

    total_salary = sum(p.salary for p, _ in lineup)
    total_projection = sum(player_projections[p.dk_id] for p, _ in lineup)

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
    )


def optimize_multiple(
    players: list,
    strategies: Optional[list] = None,
    exclude_injured: bool = True,
    exclude_questionable: bool = False,
    enriched_stats: Optional[dict] = None,
) -> dict:
    """
    Run multiple optimization strategies and return all results keyed by strategy name.
    """
    if strategies is None:
        strategies = ["best_projected", "best_value"]

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
