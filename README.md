# 🏈 Gampy GO — Gampy's Gridiron Optimizer

A personal weekly fantasy football lineup optimizer built with Streamlit.
Combines your DraftKings player pool with real NFL stats from nflverse,
season-to-date defensive matchups, Monte Carlo pressure tests, and optional
market ranking checks under a **$50,000** Classic salary cap.

---

## Features

### Data & projections
- **DraftKings CSV ingestion** — upload the weekly player pool or fetch via URL
- **nflverse enrichment** — recent fantasy points, targets/share, WOPR, snaps,
  carries, Vegas totals/spreads/implied points, home/away
- **Adjusted projections** — blends DK averages with recent form, Vegas, and
  defensive matchup multipliers by position
- **Live defense vs position** — fantasy points allowed by each defense to
  QB/RB/WR/TE from this season’s completed games (auto-expands each week)
  - Sample window: **all weeks so far** or **last N weeks**
  - Fallback to preseason JSON tiers if live data is unavailable
  - Grid columns: **Def Rank** (1 = softest … 32 = toughest) and **Def Pts/G**

### Optimizer
- **Integer linear program (PuLP)** — valid Classic roster under the salary cap
- **Multi-game rule** — enforces ≥ 2 distinct NFL games
- **Strategies**
  - Best Projected Score
  - Best Value (pts per $1k)
  - High Floor
  - High Ceiling
  - Contrarian (ceiling / $)
- **Multiple lineups** — generate 1–10 diverse lineups with a uniqueness penalty
- **Optional stacking** — force QB + same-team WR/TE
- **Max from one team** — optional hard cap
- **Lock / exclude** players; exclude OUT/IR and/or Questionable

### Pressure tests
- **Monte Carlo** — 3,000 sims around each player’s projection with
  position-specific variance → mean, std, 10th/50th/90th percentiles
- **Stats Guy check** — free redraft market ranks/values as an independent
  signal (trade values, **not** weekly DFS points)

### UX
- Lineup vault with salary remaining, floor/ceiling, games used
- CSV export per lineup
- Player pool filters (position, status, team, salary)
- Decoder Ring explaining the projection math
- Dark theme

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

## Project Structure

```
GGO-FFL-Optimizer/
├── app.py                      # Streamlit UI
├── requirements.txt
├── refactor.md                 # Implementation notes / changelog guide
│
├── data/
│   ├── defenses.py             # Matchup multipliers (live DvP + JSON fallback)
│   ├── nflverse.py             # CDN fetches: weekly stats, snaps, schedules, DvP
│   ├── statsguy.py             # Stats Guy Fantasy rankings (pressure test)
│   ├── draftkings.py           # Re-exports ingestion helpers
│   └── Defense_Predictions.json
│
├── ingestion/
│   └── csv_loader.py           # DK CSV → Player objects
│
├── models/
│   ├── player.py               # Player dataclass
│   ├── projections.py          # Enrichment + adjusted projections + floor/ceiling
│   └── monte_carlo.py          # Lineup Monte Carlo simulator
│
├── optimization/
│   └── optimizer.py            # PuLP ILP (strategies, multi-lineup, stacking)
│
├── static/
│   └── GridironOptimizer.jpg
│
└── .streamlit/
    └── config.toml
```

---

## Setup

### 1. Clone

```bash
git clone https://github.com/wieberew-oss/GGO-FFL-Optimizer.git
cd GGO-FFL-Optimizer
```

### 2. Install dependencies

Python 3.10+ recommended.

```bash
pip install -r requirements.txt
```

Core packages: `streamlit`, `pandas`, `pulp`, `requests`, `pyarrow` (for nflverse parquet).

### 3. Run

```bash
streamlit run app.py
```

---

## Usage

1. **Load Player Pool** — upload the DraftKings weekly CSV (Lobby → Export CSV)
   or paste a CSV URL.
2. **Load NFL Stats** *(recommended)* — select seasons (include the current year),
   set recent-weeks window, click **Load Stats**.
3. **Defensive Matchup Source**
   - **Season sample (auto)** — points allowed from completed games this year
     - *All weeks so far* or *Last N weeks*
   - **Pre-Season Predictions (JSON)** — legacy tiers
   - **No Defensive Adjustment**
4. **Optimizer Settings** — strategy, number of lineups, advanced constraints
   (min games, stacking, max from team), locks/excludes.
5. **Generate Lineup(s)** — results land in the **Generated Lineups Vault**.
6. **Pressure tests** (per lineup) — **Run Monte Carlo** and/or **Stats Guy check**.
7. **Player Pool** — inspect Adj Proj, Vegas Δ, Defense Δ, Def Rank, Def Pts/G,
   usage metrics, and the Decoder Ring.

---

## Data Sources

| Source | Provides |
|--------|----------|
| DraftKings CSV | Salaries, positions, injury status, AvgPointsPerGame |
| nflverse weekly player stats | Recent form, usage, **defense points allowed by position** |
| nflverse snap counts | Snap % |
| nflverse schedules | Game totals, spreads, home/away |
| Stats Guy Fantasy API | Redraft market ranks/values (pressure test only, free, no key) |
| Defense_Predictions.json | Preseason matchup fallback |

nflverse: [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases)  
Stats Guy: [api.statsguyfantasy.com](https://api.statsguyfantasy.com/api/v1) (attribution appreciated)

---

## Projection Model

### Mean projection (by position)

| Position | Blend |
|----------|--------|
| QB | `DK×0.40 + recent×0.60 + vegas + home` |
| RB | `DK×0.35 + recent×0.65 + vegas + home + snap_bonus` |
| WR | `DK×0.30 + recent×0.60 + vegas + home + target_bonus + wopr_bonus` |
| TE | `DK×0.35 + recent×0.65 + vegas + home + target_bonus` |
| DST | DK average only |

Then apply **defense multiplier** (~0.88–1.12) from opponent rank vs that position.

```text
final_proj ≈ (enriched_mean) × matchup_multiplier
```

### Defense rank scale

| Rank vs position | Multiplier | Badge |
|------------------|------------|--------|
| 1 (most pts allowed) | ~1.12 | 🟢 Soft |
| 16 | ~1.00 | 🟡 Neutral |
| 32 (fewest pts allowed) | ~0.88 | 🔴 Tough |

### Floor / ceiling

- Heuristic bands around the mean (used by High Floor / High Ceiling strategies)
- Monte Carlo supplies distribution-based 10th / 90th percentiles for pressure testing

### Grid icons

- **★** — enriched with nflverse recent stats  
- **◆** — Vegas context only  
- **·** — DK average only  

---

## Monte Carlo notes

- Independent normal draws per player, mean = optimizer projection  
- Position-specific coefficient of variation (QB lower, WR/TE/DST higher)  
- Scores truncated at 0; 3,000 simulations by default  
- This is a **variance pressure test**, not a full game-script simulator  

---

## Requirements

See `requirements.txt`. Typical pins:

```
streamlit>=1.35.0
pandas>=2.0.0
pulp>=2.7.0
requests>=2.31.0
pyarrow>=14.0.0
```

---

## Roadmap

- [x] Multi-game constraint (≥ 2 games)
- [x] High Floor / High Ceiling / Contrarian strategies
- [x] Multiple lineup generation with diversity
- [x] Live defense vs position (season sample)
- [x] Monte Carlo lineup pressure test
- [x] Stats Guy market-rank pressure test
- [x] Export lineup CSV
- [ ] Ownership / leverage integration
- [ ] Residual-based player SDs from historical weeks
- [ ] Full game-script Monte Carlo (correlated QB/pass-catchers)

---

## Notes

- Personal use only.
- Do not scrape or bypass DraftKings authentication.
- nflverse data is public for personal/research use.
- Stats Guy values are market rankings, not weekly point projections.
