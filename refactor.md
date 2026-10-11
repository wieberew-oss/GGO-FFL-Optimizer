# GGO-FFL-Optimizer — Refactor Guide

This document describes the concrete changes to make in your local repo  
`https://github.com/wieberew-oss/GGO-FFL-Optimizer`.

Work through the files in order. Each section lists **what to change** and **why**.

---

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

---

## 1. `models/player.py`

### Changes

1. Import `List` from `typing`.
2. Type `roster_slots` as `List[str]`.
3. Add a `_recompute_value()` helper and call it from `__post_init__`.
4. Add `update_projection(new_proj)` that updates projection + value.
5. Add a `game_key` property used by the multi-game constraint:

```python
@property
def game_key(self) -> str:
    """Short matchup key (e.g. 'DET@ARI')."""
    if not self.game_info:
        return self.team or "UNK"
    return self.game_info.split()[0]
```

6. Extend `to_dict()` to include `"Floor"`, `"Ceiling"`, and `"Game"`.

### Why

`game_key` is required for the Classic “≥ 2 games” rule. Floor/ceiling fields are already declared; we just surface them cleanly.

---

## 2. `models/projections.py`

### A. Extend `PlayerStats`

Add two fields after `adjusted_projection`:

```python
floor: Optional[float] = None
ceiling: Optional[float] = None
```

Update `data_source` comment to include `'vegas_only'`.

In `to_display_dict()`, add:

```python
"Floor": _fmt(self.floor),
"Ceiling": _fmt(self.ceiling),
```

### B. Add floor/ceiling helper

Insert this function near the other projection helpers (before `_ADJUSTERS`):

```python
def _compute_floor_ceiling(
    base_proj: float,
    recent: Optional[float],
    games_played: Optional[int],
) -> tuple[float, float]:
    """
    Simple floor / ceiling estimates.
    Floor leans on the lower of DK avg and recent form.
    Ceiling leans on the higher of the two, with a modest upside bump.
    """
    if recent is None:
        floor = round(base_proj * 0.70, 2)
        ceiling = round(base_proj * 1.40, 2)
        return floor, ceiling

    sample = games_played or 1
    weight_recent = min(0.75, 0.40 + 0.05 * sample)

    blended = base_proj * (1 - weight_recent) + recent * weight_recent
    low = min(base_proj, recent, blended)
    high = max(base_proj, recent, blended)

    floor = round(max(0.0, low * 0.85), 2)
    ceiling = round(high * 1.25, 2)
    return floor, ceiling
```

### C. Wire it into `enrich_players`

After you set `stats.adjusted_projection` and `stats.data_source` (both the enriched branch and the vegas/dk_only branch), add:

```python
stats.floor, stats.ceiling = _compute_floor_ceiling(
    stats.adjusted_projection or player.projection,
    stats.recent_fantasy_pts,
    stats.games_played,
)
# Attach to Player for optimizer convenience
player.floor = stats.floor
player.ceiling = stats.ceiling
```

Do this **before** `results[player.dk_id] = stats`.

### Why

Floor/ceiling power the new High Floor / High Ceiling strategies and appear in the UI.

---

## 3. `optimization/optimizer.py` (largest change)

Replace / extend this module. Key additions:

### A. New constants and helpers

```python
from collections import defaultdict
from typing import Optional, List, Dict, Set, Tuple

VALID_STRATEGIES = {
    "best_projected",
    "best_value",
    "high_floor",
    "high_ceiling",
    "contrarian",
}
```

### B. Extend `OptimizationResult`

Add fields:

```python
total_floor: float = 0.0
total_ceiling: float = 0.0
games_used: int = 0
```

Update `to_display_rows()` to include Floor, Ceiling, and Game columns, and a TOTAL row that shows floor/ceiling/games.

Add a DK-style export helper:

```python
def to_dk_export_rows(self) -> list:
    """Rows suitable for a simple CSV download."""
    rows = []
    for player, slot in self.lineup:
        rows.append({
            "Position": slot,
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
```

### C. Floor / ceiling helpers used by the objective

```python
def _get_floor(player, enriched_stats, proj) -> float:
    if player.floor is not None:
        return player.floor
    ps = (enriched_stats or {}).get(player.dk_id)
    if ps and getattr(ps, "floor", None) is not None:
        return ps.floor
    return round(proj * 0.70, 2)

def _get_ceiling(player, enriched_stats, proj) -> float:
    if player.ceiling is not None:
        return player.ceiling
    ps = (enriched_stats or {}).get(player.dk_id)
    if ps and getattr(ps, "ceiling", None) is not None:
        return ps.ceiling
    return round(proj * 1.40, 2)
```

### D. Strategy-aware objective

```python
def _build_objective_value(player, strategy, projection, floor, ceiling) -> float:
    if strategy == "best_value":
        return (projection / (player.salary / 1000)) if player.salary > 0 else 0.0
    if strategy == "high_floor":
        return floor
    if strategy == "high_ceiling":
        return ceiling
    if strategy == "contrarian":
        return (ceiling / (player.salary / 1000)) if player.salary > 0 else 0.0
    return projection  # best_projected
```

### E. Expand `optimize()` signature

Add these parameters (with defaults):

```python
require_min_games: int = 2,
stack_qb_with_receiver: bool = False,
max_from_same_team: Optional[int] = None,
previously_used_ids: Optional[Set[int]] = None,
uniqueness_penalty: float = 0.0,
```

### F. Multi-game constraint (Classic rule)

After the lock constraints, add:

```python
if require_min_games and require_min_games > 1:
    game_to_indices = defaultdict(list)
    for i, p in enumerate(pool):
        game_to_indices[p.game_key].append(i)

    game_vars = []
    for g_idx, (g, idxs) in enumerate(game_to_indices.items()):
        gv = pulp.LpVariable(f"game_{g_idx}", cat="Binary")
        game_vars.append(gv)
        for i in idxs:
            # Selecting a player from this game forces the game var on
            prob += x[i] <= gv, f"game_link_{g_idx}_{i}"

    prob += pulp.lpSum(game_vars) >= require_min_games, "Min_Games"
```

### G. Optional QB + receiver stack

```python
if stack_qb_with_receiver:
    qb_indices = [i for i, p in enumerate(pool) if p.position == "QB"]
    for qi in qb_indices:
        qb = pool[qi]
        same_team_receivers = [
            i for i, p in enumerate(pool)
            if p.team == qb.team and p.position in {"WR", "TE"}
        ]
        if same_team_receivers:
            prob += (
                pulp.lpSum(x[i] for i in same_team_receivers) >= x[qi],
                f"Stack_QB_{qi}",
            )
```

### H. Optional max-from-team

```python
if max_from_same_team is not None and max_from_same_team > 0:
    team_to_indices = defaultdict(list)
    for i, p in enumerate(pool):
        team_to_indices[p.team].append(i)
    for team, idxs in team_to_indices.items():
        if len(idxs) > max_from_same_team:
            prob += (
                pulp.lpSum(x[i] for i in idxs) <= max_from_same_team,
                f"MaxTeam_{team}",
            )
```

### I. Uniqueness penalty in the objective

When building the objective terms, if a player’s `dk_id` is in `previously_used_ids` and `uniqueness_penalty > 0`, subtract the penalty from that player’s objective value.

### J. Result totals

After building the lineup, compute:

```python
total_floor = sum(floors[p.dk_id] for p, _ in lineup)
total_ceiling = sum(ceilings[p.dk_id] for p, _ in lineup)
games_used = len({p.game_key for p, _ in lineup})
```

and pass them into `OptimizationResult`.

### K. New function: `optimize_multiple_lineups`

```python
def optimize_multiple_lineups(
    players,
    n_lineups: int = 3,
    strategy: str = "best_projected",
    # ... same kwargs as optimize (exclude_names, lock_names, etc.)
    uniqueness_penalty: float = 5.0,
) -> List[OptimizationResult]:
    results = []
    used_ids: Set[int] = set()
    for _ in range(max(1, n_lineups)):
        res = optimize(
            players,
            strategy=strategy,
            # ... pass through all kwargs ...
            previously_used_ids=used_ids,
            uniqueness_penalty=uniqueness_penalty,
        )
        if not res.feasible:
            break
        results.append(res)
        for p, _ in res.lineup:
            used_ids.add(p.dk_id)
    return results
```

Keep the existing `optimize_multiple` (multi-strategy) helper; just expand its default strategy list if you want.

---

## 4. `ingestion/csv_loader.py`

### Changes

1. Change `load_from_dataframe` to return `(players, skipped)` where `skipped` is a list of `(row_index, reason)`.
2. On empty/NaN names or parse errors, append to `skipped` instead of only `continue`.
3. Update wrappers:

```python
def load_from_file(filepath: str) -> tuple:
    df = pd.read_csv(filepath)
    return load_from_dataframe(df)

def load_from_upload(uploaded_file) -> tuple:
    df = pd.read_csv(uploaded_file)
    return load_from_dataframe(df)
```

4. In `load_from_url`, after `load_from_dataframe`, surface a soft message if any rows were skipped (optional).

### Why

Silent drops make debugging hard. Surface the count in the UI.

---

## 5. `app.py`

### A. Imports

```python
from optimization.optimizer import (
    optimize,
    optimize_multiple_lineups,
    effective_projection,
    SALARY_CAP,
)
```

### B. Strategy labels

```python
STRATEGY_LABELS = {
    "best_projected": "Best Projected Score",
    "best_value": "Best Value (Pts per $1k)",
    "high_floor": "High Floor (safer)",
    "high_ceiling": "High Ceiling (upside)",
    "contrarian": "Contrarian (ceiling / $)",
}
```

### C. CSV upload handling

Where you currently do:

```python
players = load_from_upload(uploaded)
```

change to:

```python
players, skipped = load_from_upload(uploaded)
if skipped:
    st.warning(f"Skipped {len(skipped)} malformed rows")
```

### D. Optimizer settings (sidebar)

After the strategy selectbox, add:

```python
n_lineups = st.slider("Number of lineups to generate", 1, 10, 1)

with st.expander("Advanced constraints"):
    require_min_games = st.number_input("Min distinct games (Classic rule)", 1, 5, 2)
    stack_qb = st.checkbox("Force QB + same-team WR/TE stack", value=False)
    max_team = st.number_input("Max players from one team (0 = no limit)", 0, 5, 0)
    uniqueness_penalty = st.slider("Diversity penalty (pts)", 0.0, 15.0, 5.0, 0.5)
```

Rename the generate button to something like **“Generate Lineup(s)”**.

### E. Generate trigger

Replace the single `optimize(...)` call with:

```python
common_kwargs = dict(
    strategy=strategy,
    exclude_names=st.session_state.exclude_names,
    lock_names=st.session_state.lock_names,
    exclude_injured=exclude_injured,
    exclude_questionable=exclude_questionable,
    enriched_stats=st.session_state.enriched_stats if use_adjusted_projection else {},
    matchup_multipliers=matchup_multipliers if use_adjusted_projection else {},
    projection_mode=projection_mode,
    require_min_games=int(require_min_games),
    stack_qb_with_receiver=stack_qb,
    max_from_same_team=int(max_team) if max_team > 0 else None,
    uniqueness_penalty=float(uniqueness_penalty),
)

if n_lineups <= 1:
    results = [optimize(players, **common_kwargs)]
else:
    results = optimize_multiple_lineups(players, n_lineups=n_lineups, **common_kwargs)

for result in results:
    if result.feasible:
        st.session_state.lineup_history.insert(0, result)
    else:
        st.error(f"Optimization failed: {result.message}")
```

### F. Lineup display metrics

In the lineup expander header / metrics, show:

- Projected  
- Floor  
- Ceiling  
- Salary  
- Cap remaining  
- Games used (`res.games_used`)

Example title:

```text
⭐ [LATEST] — Proj: 170.4 | Floor 119 / Ceil 239 | $49,900 | 7 games
```

### G. Table columns

In the lineup `st.dataframe` `column_config`, add:

```python
"Floor": st.column_config.TextColumn("Floor", width=60),
"Ceiling": st.column_config.TextColumn("Ceiling", width=65),
"Game": st.column_config.TextColumn("Game", width=90),
```

(These columns already come from the updated `to_display_rows()`.)

### H. Export button

After the lineup dataframe, add:

```python
import pandas as pd  # if not already

export_df = pd.DataFrame(res.to_dk_export_rows())
csv_bytes = export_df.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Export this lineup (CSV)",
    data=csv_bytes,
    file_name=f"ggo_lineup_{run_num}.csv",
    mime="text/csv",
    key=f"export_{idx}_{run_num}",
)
```

---

## 6. `data/defenses.py` (tiny)

Fix the typo:

```text
"Tampa Bank Buccaneers"  →  "Tampa Bay Buccaneers"
```

---

## 7. `README.md` (optional but recommended)

Under Features, add bullets for:

- Multi-game constraint (≥ 2 games)
- Multiple diverse lineups
- High Floor / High Ceiling / Contrarian strategies
- Optional QB + receiver stacking
- Floor / ceiling estimates
- DK CSV export

---

## Implementation order (recommended)

1. `models/player.py` — small, no dependencies  
2. `models/projections.py` — floor/ceiling  
3. `optimization/optimizer.py` — core logic  
4. `ingestion/csv_loader.py` — return tuple  
5. `app.py` — wire UI + new kwargs  
6. `data/defenses.py` + `README.md` — polish  

After each step, run:

```bash
python -m py_compile models/player.py models/projections.py optimization/optimizer.py ingestion/csv_loader.py
streamlit run app.py
```

and generate a lineup against a real DK CSV to confirm feasibility, salary ≤ $50k, and ≥ 2 games.

---

## Quick verification checklist

- [ ] Lineup always uses players from at least 2 games  
- [ ] High Floor / High Ceiling / Contrarian appear in the strategy dropdown  
- [ ] “Number of lineups” > 1 produces distinct lineups  
- [ ] Floor and Ceiling columns show numbers (or “—” when unavailable)  
- [ ] Export button downloads a CSV  
- [ ] Skipped malformed CSV rows surface a warning  
- [ ] Stacking checkbox forces a same-team WR/TE when a QB is taken  
- [ ] Salary still respects the $50,000 cap  

---

## Notes

- Floor/ceiling formulas are intentionally simple heuristics. You can later replace them with std-dev or percentile-based estimates from nflverse weekly history.
- The uniqueness penalty is a soft objective penalty (not a hard “cannot reuse” constraint), which keeps the ILP feasible while encouraging diversity.
- `require_min_games=2` matches the Classic rules you shared; leave it configurable so single-game or showdown-style pools still work if you ever need them.
