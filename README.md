# 🏈 Gampy GO — Gampy's Gridiron Optimizer

A personal weekly fantasy football lineup optimizer built with Streamlit.
Combines your DraftKings player pool with real NFL stats from nflverse to
generate data-driven lineups under a $50,000 salary cap.

---

## Features

- **DraftKings CSV ingestion** — upload your weekly player pool or fetch via URL
- **nflverse stat enrichment** — pulls real player stats from the nflverse CDN
  (2019–2025 seasons available), including:
  - Recent fantasy points (last N weeks)
  - Targets & target share
  - WOPR (Weighted Opportunity Rating)
  - Snap percentage
  - Carries & rushing yards
  - Vegas game totals, spreads & implied team totals
  - Home/away indicator
- **Adjusted projections** — blends DK averages with recent form and Vegas context
  by position (QB / RB / WR / TE)
- **Integer linear program optimizer** — finds the legally valid lineup that
  maximizes projected points under the salary cap
- **Two optimization strategies**
  - Best Projected Score
  - Best Value (pts per $1,000 of salary)
- **Player pool filters** — position, status, team, salary range
- **My Picks toggle** — shows only your current lineup in the pool grid with
  assigned slot labels
- **Injury controls** — toggle to exclude OUT/IR and/or Questionable players
- **Lock / exclude players** — force players in or out of the lineup
- **Dark theme** with green accent

---

## Roster Format

| Slot  | Count | Notes              |
|-------|-------|--------------------|
| QB    | 1     |                    |
| RB    | 2     |                    |
| WR    | 3     |                    |
| TE    | 1     |                    |
| FLEX  | 1     | RB, WR, or TE      |
| DST   | 1     |                    |
| **Total** | **9** | Cap: **$50,000** |

---

## Project Structure

```
FFL/
├── app.py                      # Streamlit entry point
├── requirements.txt
├── verify.py                   # End-to-end sanity check script
│
├── data/
│   ├── draftkings.py           # DK CSV ingestion (re-exports ingestion/)
│   └── nflverse.py             # nflverse CDN fetcher + caching
│
├── ingestion/
│   └── csv_loader.py           # DK CSV parser → Player objects
│
├── models/
│   ├── player.py               # Player dataclass
│   └── projections.py          # Stat enrichment + adjusted projection engine
│
├── optimization/
│   └── optimizer.py            # PuLP integer linear program optimizer
│
├── static/
│   └── GridironOptimizer.jpg   # Sidebar logo
│
└── .streamlit/
    └── config.toml             # Dark theme configuration
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/gampy-go.git
cd gampy-go
```

### 2. Install dependencies

Python 3.10+ recommended.

```bash
pip install -r requirements.txt
```

> **Note:** `nfl-data-py` requires `pandas < 2.0`. The requirements file pins
> this correctly.

### 3. Run the app

```bash
streamlit run app.py
```

---

## Usage

1. **Load Player Pool** — upload the DraftKings weekly CSV (downloaded from
   DraftKings → Lobby → Export CSV) or paste the CSV URL into the sidebar.

2. **Load NFL Stats** *(optional but recommended)* — select one or more past
   seasons (e.g. 2024, 2025), set the recent-weeks window, and click
   **Load Stats**. This fetches parquet files from the nflverse CDN (~10–30s).

3. **Optimizer Settings** — choose a strategy, toggle injury exclusions, and
   optionally lock or exclude specific players.

4. **Generate Lineup** — click the button. The recommended lineup appears in
   the **Recommended Lineup** tab with projected scores, salary breakdown, and
   per-player explanations.

5. **My Picks** — switch to the **Player Pool** tab and toggle **🏈 My Picks
   only** to see just your lineup players with their assigned slots and full
   stat context.

---

## Data Sources

| Source | What it provides |
|--------|-----------------|
| DraftKings CSV | Player pool, salaries, positions, injury status |
| nflverse `stats_player` CDN | Weekly player stats (2019–2025) |
| nflverse `snap_counts` CDN | Snap percentage (2019–2025) |
| nflverse `schedules` CDN | Game totals, spreads, home/away |

nflverse data is fetched directly from the
[nflverse-data GitHub releases](https://github.com/nflverse/nflverse-data/releases).
No API key required.

---

## Projection Model

Adjusted projections blend DK's `AvgPointsPerGame` with nflverse recent form
and Vegas context:

| Position | Formula |
|----------|---------|
| QB | `base × 0.40 + recent × 0.60 + vegas_boost + home_boost` |
| RB | `base × 0.35 + recent × 0.65 + vegas + home + snap_bonus` |
| WR | `base × 0.30 + recent × 0.60 + vegas + home + target_bonus + wopr_bonus` |
| TE | `base × 0.35 + recent × 0.65 + vegas + home + target_bonus` |
| DST | DK average (no enrichment) |

Data source icons in the grid:
- **★** — fully enriched with nflverse recent stats
- **◆** — Vegas context only (no recent stat match found)
- **·** — DK average only

---

## Requirements

```
streamlit>=1.35.0
pandas>=1.5.0,<2.0.0
pulp>=2.7.0
requests>=2.31.0
nfl-data-py==0.3.3
```

---

## Roadmap

- [ ] Monte Carlo simulation for lineup variance analysis
- [ ] High Floor / High Ceiling / Contrarian optimization strategies
- [ ] Opponent / league historical lineup analysis
- [ ] Automated DraftKings CSV fetch (when feasible without scraping)
- [ ] Multiple lineup generation
- [ ] Export lineup to DraftKings upload format

---

## Notes

- This app is for personal use only.
- Do not scrape or bypass DraftKings authentication.
- nflverse data is publicly available for personal/research use.
