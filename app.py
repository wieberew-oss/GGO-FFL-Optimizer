# ===========================================================================
# File: app.py
# ===========================================================================
"""
app.py
------
Gampy GO — Gampy's Gridiron Optimizer
Streamlit UI: DK CSV ingestion, nflverse enrichment with flexible defensive matchup scaling,
lineup optimizer, and interactive Decoder Ring.
"""

import sys
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import streamlit as st

from ingestion.csv_loader import load_from_upload, load_from_url
from optimization.optimizer import optimize, SALARY_CAP
from data.nflverse import is_available as nfl_available, clear_cache
from models.projections import enrich_players
from data.defenses import get_opponent_defensive_factor

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Gampy GO",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
for key, default in {
    "players": [],
    "enriched_stats": {},
    "last_source": None,
    "nfl_seasons": [],
    "nfl_loaded": False,
    "lineup_history": [],  # List of saved OptimizationResult objects
    "lock_names": set(),
    "exclude_names": set(),
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------
CURRENT_YEAR = 2026
AVAILABLE_SEASONS = list(range(2019, 2026))

STRATEGY_LABELS = {
    "best_projected": "Best Projected Score",
    "best_value": "Best Value (Pts per $1k)",
}

STATUS_COLOR = {
    "": "🟢",
    "Q": "🟡",
    "OUT": "🔴",
    "IR": "🔴",
}

DATA_SOURCE_LEGEND = "★ enriched with nflverse  ◆ Vegas only  · DK avg only"


def status_badge(s: str) -> str:
    return STATUS_COLOR.get(s, "⚪") + " " + (s if s else "OK")


def get_matchup_multiplier_and_badge(position: str, opponent: str, use_preseason: bool) -> tuple[float, str]:
    """
    Calculates defensive matchup scaling factor and visual badge using
    either pre-season JSON predictions or live game history.
    """
    multiplier = get_opponent_defensive_factor(position, opponent, use_preseason=use_preseason)

    if use_preseason:
        if multiplier < 0.95:
            badge = "🔴 Tough"
        elif multiplier > 1.05:
            badge = "🟢 Soft"
        else:
            badge = "🟡 Neutral"
    else:
        badge = "🟡 Live Matchup"

    return multiplier, badge


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    logo_path = os.path.join(os.path.dirname(__file__), "static", "GridironOptimizer.jpg")
    if os.path.exists(logo_path):
        st.image(logo_path, use_container_width=True)
    else:
        st.title("🏈 Gampy GO")
    st.caption("Gampy's Gridiron Optimizer")
    st.markdown("---")

    # ---- 1. Player Pool ----
    st.subheader("1. Load Player Pool")
    source = st.radio("Data source", ["Upload CSV", "DraftKings URL"], index=0)

    players = []
    load_error = None

    if source == "Upload CSV":
        uploaded = st.file_uploader(
            "Upload DraftKings player CSV",
            type=["csv"],
            help="Download from DraftKings → Lobby → Export CSV",
        )
        if uploaded:
            try:
                players = load_from_upload(uploaded)
                st.session_state.players = players
                st.session_state.nfl_loaded = False
                st.session_state.enriched_stats = {}
                st.session_state.lineup_history = []
                st.session_state.lock_names = set()
                st.session_state.exclude_names = {"Tay Martin"} if any(
                    p.name == "Tay Martin" for p in players) else set()
                st.session_state.pop("sb_locks", None)
                st.session_state.pop("sb_excludes", None)
                st.session_state.pop("player_pool_grid_editor", None)
            except Exception as e:
                load_error = str(e)
    else:
        dk_url = st.text_input(
            "DraftKings CSV URL",
            value="https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=21&draftGroupId=151307",
        )
        if st.button("Fetch Player Pool", type="primary"):
            with st.spinner("Fetching from DraftKings..."):
                fetched, err = load_from_url(dk_url)
                if err:
                    load_error = err
                else:
                    st.session_state.players = fetched
                    st.session_state.nfl_loaded = False
                    st.session_state.enriched_stats = {}
                    st.session_state.lineup_history = []
                    st.session_state.lock_names = set()
                    st.session_state.exclude_names = {"Tay Martin"} if any(
                        p.name == "Tay Martin" for p in fetched) else set()
                    st.session_state.pop("sb_locks", None)
                    st.session_state.pop("sb_excludes", None)
                    st.session_state.pop("player_pool_grid_editor", None)

    if load_error:
        st.error(f"❌ {load_error}")

    if not players and st.session_state.players:
        players = st.session_state.players

    if players:
        st.success(f"✅ {len(players)} players loaded")

    st.markdown("---")

    # ---- 2. NFL Stats (nflverse) & Matchups ----
    st.subheader("2. NFL Stats & Matchups")

    if not nfl_available():
        st.warning("nfl_data_py not installed. Run: pip install nfl-data-py")
    else:
        seasons_selected = st.multiselect(
            "Stat seasons to include",
            options=AVAILABLE_SEASONS,
            default=[2024, 2025],
            help="Select one or more past seasons for stable averages.",
        )

        recent_weeks = st.slider(
            "Recent weeks for form",
            min_value=2,
            max_value=10,
            value=4,
        )

        min_snap_slider = st.slider(
            "Minimum Snap Rate %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=5.0,
        )
        min_snap_fraction = min_snap_slider / 100.0 if min_snap_slider > 0 else None

        st.markdown("#### 🛡️ Defensive Matchup Source")
        def_mode = st.radio(
            "Matchup Basis",
            options=["Pre-Season Predictions (JSON)", "Live Game History (nflverse)"],
            index=0,
            help="Use pre-season returning starter predictions early in the year, then switch to live game stats once sample sizes grow."
        )
        use_preseason_def = ("Pre-Season" in def_mode)

        col_load, col_clear = st.columns(2)
        load_nfl_btn = col_load.button("Load Stats", type="primary", disabled=not players or not seasons_selected)
        clear_nfl_btn = col_clear.button("Clear Cache")

        if clear_nfl_btn:
            clear_cache()
            st.session_state.nfl_loaded = False
            st.session_state.enriched_stats = {}
            st.toast("Cache cleared")

        if load_nfl_btn and players and seasons_selected:
            progress = st.progress(0, text="Fetching weekly stats...")
            try:
                progress.progress(25, text="Fetching weekly stats...")
                progress.progress(50, text="Fetching snap counts...")
                progress.progress(75, text="Fetching schedules...")
                enriched = enrich_players(
                    players,
                    seasons_selected,
                    recent_weeks=recent_weeks,
                    min_snap_pct=min_snap_fraction
                )
                progress.progress(100, text="Done!")
                st.session_state.enriched_stats = enriched
                st.session_state.nfl_loaded = True
                st.session_state.nfl_seasons = seasons_selected
                progress.empty()
                matched = sum(1 for ps in enriched.values() if ps.data_source == "enriched")
                st.success(f"✅ Stats loaded — {matched} players enriched")
            except Exception as e:
                progress.empty()
                st.error(f"❌ Stats load failed: {e}")

        if st.session_state.nfl_loaded:
            seasons_str = ", ".join(str(s) for s in st.session_state.nfl_seasons)
            st.caption(f"Using seasons: {seasons_str} | {recent_weeks}wk form")

    # Fallback toggle variable if nfl_data_py is unavailable
    if 'use_preseason_def' not in locals():
        use_preseason_def = True

    st.markdown("---")

    # ---- 3. Optimizer Settings & Roster Constraints ----
    st.subheader("3. Optimizer Settings")

    strategy = st.selectbox(
        "Strategy",
        options=list(STRATEGY_LABELS.keys()),
        format_func=lambda k: STRATEGY_LABELS[k],
    )

    exclude_injured = st.checkbox("Exclude OUT / IR players", value=True)
    exclude_questionable = st.checkbox("Exclude Questionable (Q) players", value=False)

    player_names_sorted = sorted([p.name for p in players]) if players else []

    # Clean sets to ensure all defaults exist in the current player options
    st.session_state.lock_names = {name for name in st.session_state.lock_names if name in player_names_sorted}
    st.session_state.exclude_names = {name for name in st.session_state.exclude_names if name in player_names_sorted}

    # Sidebar multiselects driven cleanly by session state sets
    sidebar_locks = st.multiselect(
        "🔒 Lock Players",
        options=player_names_sorted,
        default=list(st.session_state.lock_names),
        key="sb_locks",
        help="Selected players are guaranteed a spot in generated lineups.",
    )
    st.session_state.lock_names = set(sidebar_locks)

    sidebar_excludes = st.multiselect(
        "❌ Exclude Players (Fades)",
        options=player_names_sorted,
        default=list(st.session_state.exclude_names),
        key="sb_excludes",
        help="Selected players will be completely removed from optimization pools.",
    )
    st.session_state.exclude_names = set(sidebar_excludes)

    st.markdown("---")
    run_btn = st.button("🚀 Generate New Lineup Alternative", type="primary", disabled=not players)

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🏈 Gampy's Gridiron Optimizer")

if not players:
    st.info("👈 Load a DraftKings player CSV using the sidebar to get started.")
    st.stop()

# Handle generation trigger with explicit lock/exclude passing
if run_btn:
    with st.spinner("Optimizing new lineup alternative..."):
        result = optimize(
            players,
            strategy=strategy,
            exclude_names=st.session_state.exclude_names,
            lock_names=st.session_state.lock_names,
            exclude_injured=exclude_injured,
            exclude_questionable=exclude_questionable,
            enriched_stats=st.session_state.enriched_stats,
        )
    if result.feasible:
        st.session_state.lineup_history.insert(0, result)
        st.toast(f"Generated lineup #{len(st.session_state.lineup_history)}! ({result.total_projection:.1f} pts)")
    else:
        st.error(f"❌ Optimization failed: {result.message}")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_lineup, tab_pool = st.tabs(["📋 Generated Lineups Vault", "📊 Player Pool View"])

# ---------------------------------------------------------------------------
# Player Pool tab
# ---------------------------------------------------------------------------
with tab_pool:
    st.subheader("Player Pool & Metrics View")

    # Decoder Ring Expander
    with st.expander("🔍 Decoder Ring: How Projections Are Calculated"):
        st.markdown("""
        The **Adj Proj** (Adjusted Projection) column combines baseline metrics with game environment and defensive matchup scaling:
        1. **Baseline Base (DK Avg / nflverse):** Starts with DraftKings historical average points per game or multi-season performance baselines.
        2. **Recent Form Weighting:** Incorporates player usage trends over the selected recent week window (snap percentages, target shares, and carry volume).
        3. **Vegas Game Environment:** Scales projections higher if the team has a high implied Vegas total or plays in a high over/under game environment.
        4. **Opposing Defense Matchup:** Applies positional funnel adjustments based on the opponent:
           * **🟢 Soft Matchup:** Up to a **+12% boost** facing bottom-tier units against that position.
           * **🟡 Neutral Matchup:** **1.0x baseline** multiplier.
           * **🔴 Tough Matchup:** Up to a **-12% discount** facing top-tier shutdown defenses.
        """)

    latest_lineup = st.session_state.lineup_history[0] if st.session_state.lineup_history else None
    picked_ids = {p.dk_id: slot for p, slot in latest_lineup.lineup} if latest_lineup and latest_lineup.feasible else {}

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        pos_filter = st.multiselect("Position", ["QB", "RB", "WR", "TE", "DST"], default=[], placeholder="All", key="pool_pos_filter")
    with c2:
        status_filter = st.multiselect("Status", ["OK", "Q", "OUT", "IR"], default=[], placeholder="All", key="pool_status_filter")
    with c3:
        team_options = sorted({p.team for p in players if p.team})
        team_filter = st.multiselect("Team", team_options, default=[], placeholder="All teams", key="pool_team_filter")
    with c4:
        sal_min, sal_max = st.slider("Salary", 2500, 10000, (2500, 10000), 100, format="$%d", key="pool_sal_slider")

    filtered_players = players
    if pos_filter:
        filtered_players = [p for p in filtered_players if p.position in pos_filter]
    if status_filter:
        filtered_players = [
            p for p in filtered_players
            if (p.status if p.status else "OK") in status_filter or p.status in [("" if s == "OK" else s) for s in status_filter]
        ]
    if team_filter:
        filtered_players = [p for p in filtered_players if p.team in team_filter]
    filtered_players = [p for p in filtered_players if sal_min <= p.salary <= sal_max]

    pool_rows = []
    for p in filtered_players:
        ps = st.session_state.enriched_stats.get(p.dk_id)
        in_lineup_tag = "🏈 In Lineup" if p.dk_id in picked_ids else ""

        matchup_mult, matchup_badge = get_matchup_multiplier_and_badge(p.position, p.opponent, use_preseason_def)
        base_proj = ps.adjusted_projection if (ps and ps.adjusted_projection is not None) else p.projection
        final_adj_proj = base_proj * matchup_mult

        row_dict = {
            "Name": p.name,
            "State": in_lineup_tag,
            "Pos": p.position,
            "Team": p.team,
            "Opp": p.opponent,
            "Salary": f"${p.salary:,}",
            "DK Avg": p.projection,
            "Adj Proj": f"{final_adj_proj:.1f}",
            "Matchup": matchup_badge,
            "Value": f"{p.value:.2f}",
            "Injury": status_badge(p.status),
            "Data": {"enriched": "★", "vegas_only": "◆", "dk_only": "·"}.get(ps.data_source, "·") if ps else "·",
            "Snap%": f"{ps.avg_snap_pct * 100:.0f}%" if ps and ps.avg_snap_pct is not None else "-",
            "Targets": f"{ps.avg_targets:.1f}" if ps and ps.avg_targets is not None else "-",
            "Tgt Share": f"{ps.avg_target_share * 100:.1f}%" if ps and ps.avg_target_share is not None else "-",
            "WOPR": f"{ps.avg_wopr:.2f}" if ps and ps.avg_wopr is not None else "-",
            "Carries": f"{ps.avg_carries:.1f}" if ps and ps.avg_carries is not None else "-",
            "Rush Yds": f"{ps.avg_rushing_yards:.1f}" if ps and ps.avg_rushing_yards is not None else "-",
            "Implied": f"{ps.implied_total:.1f}" if ps and ps.implied_total is not None else "-",
            "Total": f"{ps.total_line:.1f}" if ps and ps.total_line is not None else "-",
        }
        pool_rows.append(row_dict)

    df_pool = pd.DataFrame(pool_rows)

    st.dataframe(
        df_pool,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", width=160),
            "State": st.column_config.TextColumn("Lineup Status", width=100),
            "Pos": st.column_config.TextColumn("Pos", width=55),
            "Team": st.column_config.TextColumn("Team", width=55),
            "Opp": st.column_config.TextColumn("Opp", width=55),
            "Salary": st.column_config.TextColumn("Salary", width=85),
            "DK Avg": st.column_config.NumberColumn("DK Avg", format="%.1f"),
            "Adj Proj": st.column_config.TextColumn("Adj Proj"),
            "Matchup": st.column_config.TextColumn("Matchup vs Def", width=110),
            "Value": st.column_config.TextColumn("Value"),
            "Injury": st.column_config.TextColumn("Injury"),
            "Data": st.column_config.TextColumn("Data", width=50),
            "Snap%": st.column_config.TextColumn("Snap%", width=70),
            "Targets": st.column_config.TextColumn("Targets", width=75),
            "Tgt Share": st.column_config.TextColumn("Tgt Share", width=85),
            "WOPR": st.column_config.TextColumn("WOPR", width=65),
            "Carries": st.column_config.TextColumn("Carries", width=70),
            "Rush Yds": st.column_config.TextColumn("Rush Yds", width=80),
            "Implied": st.column_config.TextColumn("Implied", width=75),
            "Total": st.column_config.TextColumn("Total", width=65),
        }
    )

    l_count = len(st.session_state.lock_names)
    e_count = len(st.session_state.exclude_names)
    st.caption(f"Showing {len(filtered_players)} of {len(players)} players  |  🔒 Locked: {l_count}  |  ❌ Excluded: {e_count}  |  {DATA_SOURCE_LEGEND}")

# ---------------------------------------------------------------------------
# Lineup tab (Lineup History Vault & Comparison)
# ---------------------------------------------------------------------------
with tab_lineup:
    history = st.session_state.lineup_history
    if not history:
        st.info("No lineups generated yet. Configure your locks/fades in the sidebar and click **🚀 Generate New Lineup Alternative**.")
    else:
        st.subheader(f"Generated Lineup Alternatives ({len(history)} saved)")
        st.markdown("Compare your generated options below. Keep your preferred build or promote a previous run.")

        if st.button("🗑️ Clear History"):
            st.session_state.lineup_history = []
            st.rerun()

        for idx, res in enumerate(history):
            run_num = len(history) - idx
            is_latest = (idx == 0)
            prefix = "⭐ [LATEST ACTIVE]" if is_latest else f"Alternative #{run_num}"

            remaining = SALARY_CAP - res.total_salary
            card_title = f"{prefix} — Proj: **{res.total_projection:.1f} pts** | Salary: **${res.total_salary:,}**"

            with st.expander(card_title, expanded=is_latest):
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Projected Score", f"{res.total_projection:.1f} pts")
                m2.metric("Total Salary", f"${res.total_salary:,}")
                m3.metric("Cap Remaining", f"${remaining:,}")

                if not is_latest:
                    if st.button(f"Make Active / Promote #{run_num}", key=f"promote_{idx}"):
                        st.session_state.lineup_history.pop(idx)
                        st.session_state.lineup_history.insert(0, res)
                        st.rerun()

                st.markdown("---")

                rows = res.to_display_rows()
                df_lineup = pd.DataFrame(rows)


                def highlight_total(row):
                    if row["Slot"] == "TOTAL":
                        return ["font-weight: bold; background-color: #1e3a5f; color: white"] * len(row)
                    return [""] * len(row)


                st.dataframe(
                    df_lineup.style.apply(highlight_total, axis=1),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Slot": st.column_config.TextColumn("Slot", width=70),
                        "Player": st.column_config.TextColumn("Player", width=180),
                        "Pos": st.column_config.TextColumn("Pos", width=55),
                        "Team": st.column_config.TextColumn("Team", width=55),
                        "Opp": st.column_config.TextColumn("Opp", width=55),
                        "Salary": st.column_config.TextColumn("Salary", width=85),
                        "Proj": st.column_config.TextColumn("Proj", width=65, help="Adjusted projection"),
                        "DK Avg": st.column_config.TextColumn("DK Avg", width=65, help="DraftKings AvgPointsPerGame"),
                        "Value": st.column_config.TextColumn("Value", width=65),
                        "Status": st.column_config.TextColumn("Status", width=65),
                        "Data": st.column_config.TextColumn("Data", width=50, help=DATA_SOURCE_LEGEND),
                    },
                )

                st.markdown("---")
                for player, slot in res.lineup:
                    ps = st.session_state.enriched_stats.get(player.dk_id)
                    badge = STATUS_COLOR.get(player.status, "⚪")
                    adj_str = ""
                    ctx_str = ""

                    if ps:
                        if ps.adjusted_projection is not None and ps.data_source != "dk_only":
                            diff = ps.adjusted_projection - player.projection
                            sign = "+" if diff >= 0 else ""
                            adj_str = f" → adj **{ps.adjusted_projection:.1f}** ({sign}{diff:.1f})"
                        if ps.implied_total is not None:
                            home_str = "home" if ps.is_home else "away"
                            ctx_str = f" | {home_str}, implied {ps.implied_total:.1f}"
                        if ps.avg_target_share is not None and player.position in ("WR", "TE"):
                            ctx_str += f", {ps.avg_target_share * 100:.0f}% tgt share"
                        if ps.avg_snap_pct is not None and player.position in ("RB", "WR", "TE"):
                            ctx_str += f", {ps.avg_snap_pct * 100:.0f}% snap"

                    st.caption(
                        f"• **{slot} — {player.name}** ({player.team} vs {player.opponent}) "
                        f"| ${player.salary:,} | DK avg {player.projection:.1f} pts{adj_str}"
                        f"{ctx_str} {badge}"
                    )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "Gampy's Gridiron Optimizer (Gampy GO)  •  "
    "Salary cap $50,000  •  QB / RB / RB / WR / WR / WR / TE / FLEX / DST  •  "
    f"{DATA_SOURCE_LEGEND}"
)