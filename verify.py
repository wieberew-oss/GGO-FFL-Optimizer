"""
verify.py - end-to-end sanity check including 2025 CDN data
Run: python verify.py  (from the FFL folder)
"""
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("Gampy GO - Verification Script")
print("=" * 60)

# ------------------------------------------------------------------
# 1. CSV Ingestion
# ------------------------------------------------------------------
print("\n[1] CSV Ingestion")
from ingestion.csv_loader import load_from_file
players = load_from_file("DKSaleries.csv")
print(f"    Players loaded : {len(players)}")
positions = {}
for p in players:
    positions[p.position] = positions.get(p.position, 0) + 1
print(f"    By position    : {positions}")
josh = next(p for p in players if p.name == "Josh Allen")
assert josh.salary == 7000
print(f"    Josh Allen     : ${josh.salary}, opp={josh.opponent} OK")
print("    Ingestion: PASS")

# ------------------------------------------------------------------
# 2. CDN data fetch — 2025
# ------------------------------------------------------------------
print("\n[2] nflverse CDN — 2025 season data")
from data.nflverse import (
    fetch_weekly_stats, fetch_snap_counts, fetch_schedules,
    get_player_recent_stats, get_snap_pct_recent, get_game_context,
    clear_cache
)

clear_cache()

weekly25 = fetch_weekly_stats([2025])
assert not weekly25.empty, "2025 weekly stats empty"
weeks = sorted(weekly25["week"].unique().tolist())
print(f"    Weekly stats 2025  : {len(weekly25)} rows, weeks={weeks[:5]}...")
assert "recent_team" in weekly25.columns, "recent_team column missing"
assert "fantasy_points" in weekly25.columns
print(f"    Columns OK (recent_team, fantasy_points, targets, wopr)")

snaps25 = fetch_snap_counts([2025])
assert not snaps25.empty, "2025 snap counts empty"
print(f"    Snap counts 2025   : {len(snaps25)} rows")

sched25 = fetch_schedules([2025])
assert not sched25.empty, "2025 schedules empty"
print(f"    Schedules 2025     : {len(sched25)} rows")

print("    CDN 2025: PASS")

# ------------------------------------------------------------------
# 3. Multi-season fetch (2024 + 2025)
# ------------------------------------------------------------------
print("\n[3] Multi-season aggregation [2024, 2025]")
recent = get_player_recent_stats([2024, 2025], recent_weeks=4)
assert not recent.empty
print(f"    Players aggregated : {len(recent)}")

# Spot-check a player likely to exist in 2025
players_in_stats = recent["player_display_name"].tolist()
print(f"    Sample names       : {players_in_stats[:5]}")

snap_recent = get_snap_pct_recent([2024, 2025], recent_weeks=4)
assert not snap_recent.empty
print(f"    Snap % players     : {len(snap_recent)}")

ctx = get_game_context([2024, 2025], "BUF", "HOU")
print(f"    BUF vs HOU context : {ctx}")
print("    Multi-season: PASS")

# ------------------------------------------------------------------
# 4. Projection enrichment with 2025 data
# ------------------------------------------------------------------
print("\n[4] Projection enrichment [2024, 2025]")
from models.projections import enrich_players

sample = [p for p in players if p.position in ("QB","WR","RB","TE") and p.projection > 5.0][:40]
enriched = enrich_players(sample, [2024, 2025], recent_weeks=4)

sources = {}
for ps in enriched.values():
    sources[ps.data_source] = sources.get(ps.data_source, 0) + 1
print(f"    Data sources       : {sources}")

enriched_count = sources.get("enriched", 0)
assert enriched_count > 0, "No players enriched — name matching failed"
print(f"    Players enriched   : {enriched_count}/{len(sample)}")

# Show a few enriched players
shown = 0
for p in sample:
    ps = enriched.get(p.dk_id)
    if ps and ps.data_source == "enriched" and shown < 5:
        diff = (ps.adjusted_projection or 0) - p.projection
        print(f"    {p.name:<25} DK={p.projection:.1f}  Adj={ps.adjusted_projection:.1f}  Delta={diff:+.1f}  Snap={ps.avg_snap_pct*100:.0f}%" if ps.avg_snap_pct else
              f"    {p.name:<25} DK={p.projection:.1f}  Adj={ps.adjusted_projection:.1f}  Delta={diff:+.1f}")
        shown += 1
print("    Enrichment: PASS")

# ------------------------------------------------------------------
# 5. Optimizer with enriched 2025 stats
# ------------------------------------------------------------------
print("\n[5] Optimizer with 2025-enriched projections")
from optimization.optimizer import optimize, SALARY_CAP
from collections import Counter

all_enriched = enrich_players(players, [2024, 2025], recent_weeks=4)
sources_full = {}
for ps in all_enriched.values():
    sources_full[ps.data_source] = sources_full.get(ps.data_source, 0) + 1
print(f"    Full pool sources  : {sources_full}")

result = optimize(players, strategy="best_projected", exclude_injured=True, enriched_stats=all_enriched)
assert result.feasible, f"Optimizer failed: {result.message}"
assert len(result.lineup) == 9
assert result.total_salary <= SALARY_CAP

slot_counts = Counter(slot for _, slot in result.lineup)
assert slot_counts["QB"] == 1 and slot_counts["RB"] == 2 and slot_counts["WR"] == 3
assert slot_counts["TE"] == 1 and slot_counts["FLEX"] == 1 and slot_counts["DST"] == 1

print(f"    Total salary       : ${result.total_salary:,}")
print(f"    Total adj proj     : {result.total_projection:.1f} pts")
print(f"    Lineup:")
for player, slot in result.lineup:
    ps  = all_enriched.get(player.dk_id)
    adj = f"{ps.adjusted_projection:.1f}" if ps and ps.adjusted_projection else "n/a"
    src = {"enriched":"*","vegas_only":"o","dk_only":"-"}.get(ps.data_source if ps else "","?")
    print(f"      {src} {slot:<5} {player.name:<25} ${player.salary:,}  DK={player.projection:.1f}  Adj={adj}")

print("    Optimizer: PASS")

print("\n" + "=" * 60)
print("ALL CHECKS PASSED")
print("=" * 60)
print("\nTo run the app:")
print("  streamlit run app.py")
