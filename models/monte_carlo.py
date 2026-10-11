"""
models/monte_carlo.py
---------------------
Monte Carlo pressure test for generated lineups.

Each player is sampled from a normal distribution centered on their
optimizer projection, with position-specific residual noise estimated
from typical DFS score variance. Lineup totals are summed over N draws.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
import math
import random

from models.player import Player

# Typical coefficient of variation (sd / mean) by position for weekly fantasy.
# Tuned for PPR-ish scoring; intentionally conservative.
_POSITION_CV = {
    "QB": 0.28,
    "RB": 0.40,
    "WR": 0.42,
    "TE": 0.45,
    "DST": 0.50,
    "K": 0.45,
}

_MIN_SD = 2.0  # points


@dataclass
class SimResult:
    n_sims: int
    mean: float
    std: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    min_score: float
    max_score: float
    player_means: Dict[int, float] = field(default_factory=dict)
    player_sds: Dict[int, float] = field(default_factory=dict)

    def to_display_dict(self) -> dict:
        return {
            "Sims": self.n_sims,
            "Mean": round(self.mean, 1),
            "Std": round(self.std, 1),
            "Floor (10th)": round(self.p10, 1),
            "25th": round(self.p25, 1),
            "Median": round(self.p50, 1),
            "75th": round(self.p75, 1),
            "Ceiling (90th)": round(self.p90, 1),
            "Min": round(self.min_score, 1),
            "Max": round(self.max_score, 1),
        }


def _player_sd(position: str, mean: float) -> float:
    cv = _POSITION_CV.get(position, 0.40)
    return max(_MIN_SD, abs(mean) * cv)


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def simulate_lineup(
    lineup: List[Tuple[Player, str]],
    player_projections: Optional[Dict[int, float]] = None,
    n_sims: int = 3000,
    seed: Optional[int] = None,
) -> SimResult:
    """
    Simulate lineup scores.

    Parameters
    ----------
    lineup              : list of (Player, slot) from OptimizationResult
    player_projections  : optional dk_id -> mean projection override
    n_sims              : number of Monte Carlo draws
    seed                : optional RNG seed for reproducibility
    """
    rng = random.Random(seed)
    players = [p for p, _ in lineup]
    means = []
    sds = []
    for p in players:
        mu = (player_projections or {}).get(p.dk_id, p.projection)
        if mu is None:
            mu = p.projection or 0.0
        sd = _player_sd(p.position, float(mu))
        means.append(float(mu))
        sds.append(sd)

    totals = []
    for _ in range(max(100, int(n_sims))):
        total = 0.0
        for mu, sd in zip(means, sds):
            # Truncate at 0 — fantasy scores can't go deeply negative in aggregate
            draw = rng.gauss(mu, sd)
            total += max(0.0, draw)
        totals.append(total)

    totals.sort()
    n = len(totals)
    mean = sum(totals) / n
    var = sum((x - mean) ** 2 for x in totals) / max(n - 1, 1)
    std = math.sqrt(var)

    return SimResult(
        n_sims=n,
        mean=mean,
        std=std,
        p10=_percentile(totals, 0.10),
        p25=_percentile(totals, 0.25),
        p50=_percentile(totals, 0.50),
        p75=_percentile(totals, 0.75),
        p90=_percentile(totals, 0.90),
        min_score=totals[0],
        max_score=totals[-1],
        player_means={p.dk_id: m for p, m in zip(players, means)},
        player_sds={p.dk_id: s for p, s in zip(players, sds)},
    )
