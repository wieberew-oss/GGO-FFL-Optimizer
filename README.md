# 🏈 Gampy GO — Gampy's Gridiron Optimizer

A personal weekly fantasy football lineup optimizer built with Streamlit.
Combines your DraftKings player pool with real NFL stats from nflverse,
season-to-date defensive matchups, situational multipliers (injury role
elevation, backup QB, weather, game script), Monte Carlo pressure tests,
and optional market ranking checks under a **$50,000** Classic salary cap.

---

## Features

### Data & base projections
- **DraftKings CSV ingestion** — upload the weekly player pool or fetch via URL
- **nflverse enrichment** — recent fantasy points, targets/share, WOPR, snaps,
  carries, TD rates, Vegas totals/spreads/implied points, home/away
- **Adjusted projections** — blends DK averages with recent form, usage bonuses,
  Vegas, home field, and RZ/TD involvement
- **Live defense vs position (DvP)** — fantasy points allowed by each defense to
  QB/RB/WR/TE from this season’s completed games (auto-expands each week)
  - Sample window: **all weeks so far** or **last N weeks**
  - Fallback to preseason JSON tiers if live data is unavailable
  - Grid columns: **Def Rank** (1 = softest … 32 = toughest) and **Def Pts/G**

### Situational multipliers (sidebar toggles)
| Toggle | Effect |
|--------|--------|
| **Role elevation** | Backup RB/WR/TE gets **+25–50%** when the higher-usage teammate is OUT/IR (optional Q) |
| **Backup QB suppression** | When a team’s top QB is OUT/IR, discount that team’s WR/TE (and the backup QB) |
| **Avoid bad weather (outdoor)** | Wind/rain/cold via Open-Meteo: discount QB/WR/TE; slight **RB** and **DST** boost. Indoor/retractable ignored |
| **Wide-spread adjustments (>7)** | Favorite by 7+: boost RB, mild pass discount. Underdog by 7+: cut RB, mild pass boost (muted vs elite pass D) |

### Optimizer
- **Integer linear program (PuLP)** — valid Classic roster under the salary cap
- **Multi-game rule** — enforces ≥ 2 distinct NFL games
- **Strategies:** Best Projected · Best Value · High Floor · High Ceiling · Contrarian
- **Multiple lineups** — 1–10 with uniqueness penalty
- **Game stack modes**
  - No forced stack
  - QB + 1 same-team WR/TE
  - QB + 2 same-team WRs
  - QB + WR + TE (same team)
- **Max from one team** · **Lock / exclude** · exclude OUT/IR and/or Q

### Pressure tests
- **Monte Carlo** — 3,000 sims → mean, std, 10th/50th/90th percentiles
- **Stats Guy check** — free redraft market ranks/values (not weekly DFS points)

### UX
- Lineup vault with salary remaining, floor/ceiling, games used, CSV export
- Player pool: Adj Proj, Projection Math, Vegas Δ, Defense Δ, Role Δ, Role OPP,
  Def Rank, Def Pts/G, usage metrics
- Decoder Ring explaining the projection pipeline

---

## Roster Format (DraftKings Classic)

| Slot | Count | Notes |
|------|-------|--------|
| QB | 1 | |
| RB | 2 | |
| WR | 3 | |
| TE | 1 | |
| FLEX | 1 | RB, WR, or TE |
| DST | 1 | |
| **Total** | **9** | Cap: **$50,000** · ≥ 2 games |

---

## Complete Projection Model

Projections are built in layers. The optimizer maximizes the **final** value
after all enabled layers. Toggle **DK averages only** in the sidebar to ignore
every adjustment.

```text
┌──────────────────────────────────────────────────────────────┐
│ 1. SEED                                                     │
│    DraftKings AvgPointsPerGame                              │
└──────────────────────────┤───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. ENRICHED MEAN  (requires Load Stats)                     │
│    Blend DK + recent form + Vegas + home + usage + RZ/TD    │
└──────────────────────────┤───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. MULTIPLIERS  (combined: product of enabled factors)      │
│    Defense × Role elevation × Backup QB × Weather × Script  │
└──────────────────────────┤───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. FINAL PROJECTION  →  used by ILP optimizer               │
│    final ≈ enriched_mean × combined_multiplier              │
└──────────────────────────────────────────────────────────────┘
```

See the full README in the repo for position formulas, multiplier tables, project structure, setup, and roadmap.
