# GGO-FFL-Optimizer — Refactor Guide

This document describes the concrete changes implemented on branch `feature/optimizer-improvements`.

## Overview of improvements

| Area | Change |
|------|--------|
| Rules compliance | Enforce ≥ 2 distinct NFL games (Classic rule) |
| Strategies | Add High Floor, High Ceiling, Contrarian |
| Multi-lineup | Generate N diverse lineups with uniqueness penalty |
| Stacking | Optional QB + same-team WR/TE stack + max-from-team |
| Floor / Ceiling | Estimate and surface them; use in new strategies |
| Export | Download any generated lineup as CSV |
| CSV loading | Report skipped/malformed rows instead of silent drops |
| UI | New controls, better metrics, Floor/Ceiling/Game columns |
| Cleanup | Typo fix, small type/structure improvements |

## Files changed

- `models/player.py` — game_key, floor/ceiling helpers, typed roster_slots
- `models/projections.py` — floor/ceiling computation during enrichment
- `optimization/optimizer.py` — multi-game constraint, new strategies, multi-lineup, stacking
- `ingestion/csv_loader.py` — returns (players, skipped)
- `app.py` — UI wiring for all new features + export
- `data/defenses.py` — Tampa Bay typo fix
- `README.md` — feature list update

## How to use

1. Checkout the branch: `git fetch && git checkout feature/optimizer-improvements`
2. Run: `streamlit run app.py`
3. Load a DK CSV, optionally load nflverse stats, then Generate Lineup(s)

## Verification checklist

- [ ] Lineup always uses players from at least 2 games
- [ ] High Floor / High Ceiling / Contrarian appear in the strategy dropdown
- [ ] Number of lineups > 1 produces distinct lineups
- [ ] Floor and Ceiling columns show numbers
- [ ] Export button downloads a CSV
- [ ] Skipped malformed CSV rows surface a warning
- [ ] Stacking checkbox forces a same-team WR/TE when a QB is taken
- [ ] Salary still respects the $50,000 cap
