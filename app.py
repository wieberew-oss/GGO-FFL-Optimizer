"""
app.py
------
Gampy GO — Gampy's Gridiron Optimizer
Streamlit UI: DK CSV ingestion, nflverse enrichment, lineup optimizer.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import streamlit as st

from ingestion.csv_loader import load_from_upload, load_from_url
from optimization.optimizer import optimize, SALARY_CAP
from data.nflverse import is_available as nfl_available, clear_cache
from models.projections import enrich_players

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
    "players":        [],
    "enriched_stats": {},
    "last_source":    None,
    "nfl_seasons":    [],
    "nfl_loaded":     False,
    "last_lineup":    None,   # OptimizationResult, persisted across tab switches
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------
CURRENT_YEAR = 2026
AVAILABLE_SEASONS = list(range(2019, 2026))   # 2019–2025, CDN has all of these

STRATEGY_LABELS = {
    "best_projected": "Best Projected Score",
    "best_value":     "Best Value (Pts per $1k)",
}

STATUS_COLOR = {
    "":    "🟢",
    "Q":   "🟡",
    "OUT": "🔴",
    "IR":  "🔴",
}

DATA_SOURCE_LEGEND = "★ enriched with nflverse  ◆ Vegas only  · DK avg only"


def status_badge(s: str) -> str:
    return STATUS_COLOR.get(s, "⚪") + " " + (s if s else "OK")


def players_to_df(players: list, enriched_stats: dict) -> pd.DataFrame:
    rows = []
    for p in players:
        d = p.to_dict()
        ps = enriched_stats.get(p.dk_id)
        if ps:
            d["Adj Proj"] = f"{ps.adjusted_projection:.1f}" if ps.adjusted_projection is not None else "-"
            d["Data"]     = {"enriched": "★", "vegas_only": "◆", "dk_only": "·"}.get(ps.data_source, "·")
            d["Snap%"]    = f"{ps.avg_snap_pct*100:.0f}%" if ps.avg_snap_pct is not None else "-"
            d["Targets"]  = f"{ps.avg_targets:.1f}" if ps.avg_targets is not None else "-"
            d["Tgt Share"]= f"{ps.avg_target_share*100:.1f}%" if ps.avg_target_share is not None else "-"
            d["WOPR"]     = f"{ps.avg_wopr:.2f}" if ps.avg_wopr is not None else "-"
            d["Carries"]  = f"{ps.avg_carries:.1f}" if ps.avg_carries is not None else "-"
            d["Rush Yds"] = f"{ps.avg_rushing_yards:.1f}" if ps.avg_rushing_yards is not None else "-"
            d["Implied"]  = f"{ps.implied_total:.1f}" if ps.implied_total is not None else "-"
            d["Total"]    = f"{ps.total_line:.1f}" if ps.total_line is not None else "-"
            d["Home"]     = ("🏠" if ps.is_home else "✈") if ps.is_home is not None else "-"
        else:
            for col in ["Adj Proj","Data","Snap%","Targets","Tgt Share","WOPR","Carries","Rush Yds","Implied","Total","Home"]:
                d[col] = "-"
        rows.append(d)

    df = pd.DataFrame(rows)
    base_cols = ["Name", "Position", "Team", "Opponent", "Salary", "Adj Proj", "Projection", "Value", "Status", "Data"]
    stat_cols = ["Snap%", "Targets", "Tgt Share", "WOPR", "Carries", "Rush Yds", "Implied", "Total", "Home"]
    all_cols  = base_cols + stat_cols
    return df[[c for c in all_cols if c in df.columns]]


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

    players    = []
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
                st.session_state.players       = players
                st.session_state.nfl_loaded    = False   # reset enrichment on new file
                st.session_state.enriched_stats = {}
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
                    st.session_state.players        = fetched
                    st.session_state.nfl_loaded     = False
                    st.session_state.enriched_stats = {}

    if load_error:
        st.error(f"❌ {load_error}")

    if not players and st.session_state.players:
        players = st.session_state.players

    if players:
        st.success(f"✅ {len(players)} players loaded")

    st.markdown("---")

    # ---- 2. nflverse Stats ----
    st.subheader("2. NFL Stats (nflverse)")

    if not nfl_available():
        st.warning("nfl_data_py not installed. Run: pip install nfl-data-py")
        enriched_stats = {}
    else:
        seasons_selected = st.multiselect(
            "Stat seasons to include",
            options=AVAILABLE_SEASONS,
            default=[2024, 2025],
            help="Select one or more past seasons. More seasons = more stable averages.",
        )

        recent_weeks = st.slider(
            "Recent weeks for form",
            min_value=2,
            max_value=10,
            value=4,
            help="How many recent weeks to average for player form stats.",
        )

        col_load, col_clear = st.columns(2)
        load_nfl_btn  = col_load.button(
            "Load Stats",
            type="primary",
            disabled=not players or not seasons_selected,
        )
        clear_nfl_btn = col_clear.button("Clear Cache")

        if clear_nfl_btn:
            clear_cache()
            st.session_state.nfl_loaded     = False
            st.session_state.enriched_stats = {}
            st.toast("Cache cleared")

        if load_nfl_btn and players and seasons_selected:
            progress = st.progress(0, text="Fetching weekly stats...")
            try:
                progress.progress(25, text="Fetching weekly stats...")
                progress.progress(50, text="Fetching snap counts...")
                progress.progress(75, text="Fetching schedules...")
                enriched = enrich_players(players, seasons_selected, recent_weeks=recent_weeks)
                progress.progress(100, text="Done!")
                st.session_state.enriched_stats = enriched
                st.session_state.nfl_loaded     = True
                st.session_state.nfl_seasons    = seasons_selected
                progress.empty()
                matched = sum(1 for ps in enriched.values() if ps.data_source == "enriched")
                st.success(f"✅ Stats loaded — {matched} players enriched")
            except Exception as e:
                progress.empty()
                st.error(f"❌ Stats load failed: {e}")

        enriched_stats = st.session_state.enriched_stats

        if st.session_state.nfl_loaded:
            seasons_str = ", ".join(str(s) for s in st.session_state.nfl_seasons)
            st.caption(f"Using seasons: {seasons_str} | {recent_weeks}wk form")

    st.markdown("---")

    # ---- 3. Optimizer Settings ----
    st.subheader("3. Optimizer Settings")

    strategy = st.selectbox(
        "Strategy",
        options=list(STRATEGY_LABELS.keys()),
        format_func=lambda k: STRATEGY_LABELS[k],
    )

    exclude_injured      = st.checkbox("Exclude OUT / IR players",          value=True)
    exclude_questionable = st.checkbox("Exclude Questionable (Q) players",  value=False)

    st.markdown("**Lock players** (force into lineup)")
    lock_input = st.text_area(
        "lock_players",
        height=80,
        placeholder="Josh Allen\nJa'Marr Chase",
        label_visibility="collapsed",
    )
    lock_names = {n.strip() for n in lock_input.splitlines() if n.strip()}

    st.markdown("**Exclude players**")
    exclude_input = st.text_area(
        "exclude_players",
        height=80,
        placeholder="Bijan Robinson",
        label_visibility="collapsed",
    )
    exclude_names = {n.strip() for n in exclude_input.splitlines() if n.strip()}

    st.markdown("---")
    run_btn = st.button("🚀 Generate Lineup", type="primary", disabled=not players)


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🏈 Gampy's Gridiron Optimizer")

if not players:
    st.info("👈 Load a DraftKings player CSV using the sidebar to get started.")
    st.stop()

tab_lineup, tab_pool = st.tabs(["📋 Recommended Lineup", "📊 Player Pool"])

# ---------------------------------------------------------------------------
# Run optimizer — outside tabs so result is in session state before either
# tab renders. This ensures My Picks is available immediately in pool tab.
# ---------------------------------------------------------------------------
if run_btn:
    with st.spinner("Optimizing lineup..."):
        result = optimize(
            players,
            strategy=strategy,
            exclude_names=exclude_names,
            lock_names=lock_names,
            exclude_injured=exclude_injured,
            exclude_questionable=exclude_questionable,
            enriched_stats=enriched_stats,
        )
    if result.feasible:
        st.session_state.last_lineup = result
    else:
        st.error(f"❌ {result.message}")
        st.session_state.last_lineup = None

# ---------------------------------------------------------------------------
# Player Pool tab
# ---------------------------------------------------------------------------
with tab_pool:
    st.subheader("Player Pool")

    # My Picks toggle — only shown when a lineup has been generated
    last_lineup = st.session_state.last_lineup
    picked_ids  = {}   # dk_id -> slot string
    if last_lineup and last_lineup.feasible:
        picked_ids = {p.dk_id: slot for p, slot in last_lineup.lineup}

    pool_col1, pool_col2 = st.columns([3, 1])
    with pool_col2:
        my_picks_on = st.toggle(
            "🏈 My Picks only",
            value=False,
            disabled=not picked_ids,
            help="Filter the pool to show only players in your current lineup",
        )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        pos_filter = st.multiselect("Position", ["QB","RB","WR","TE","DST"], default=[], placeholder="All")
    with c2:
        status_filter = st.multiselect("Status", ["OK","Q","OUT","IR"], default=[], placeholder="All")
    with c3:
        team_options = sorted({p.team for p in players if p.team})
        team_filter = st.multiselect("Team", team_options, default=[], placeholder="All teams")
    with c4:
        sal_min, sal_max = st.slider("Salary", 2500, 10000, (2500, 10000), 100, format="$%d")

    visible = players

    # My Picks filter takes priority over other filters
    if my_picks_on and picked_ids:
        visible = [p for p in visible if p.dk_id in picked_ids]
    else:
        if pos_filter:
            visible = [p for p in visible if p.position in pos_filter]
        if status_filter:
            visible = [
                p for p in visible
                if (p.status if p.status else "OK") in status_filter
                or p.status in [("" if s == "OK" else s) for s in status_filter]
            ]
        if team_filter:
            visible = [p for p in visible if p.team in team_filter]
        visible = [p for p in visible if sal_min <= p.salary <= sal_max]

    df_pool = players_to_df(visible, enriched_stats)

    # Add Slot column when My Picks is on
    if my_picks_on and picked_ids:
        df_pool.insert(0, "Slot", df_pool.apply(
            lambda row: picked_ids.get(
                next((p.dk_id for p in visible if p.name == row["Name"]), None), ""
            ), axis=1
        ))

    # Highlight picked players in full pool view
    if not my_picks_on and picked_ids:
        picked_names = {p.name for p in players if p.dk_id in picked_ids}
        df_pool.insert(0, "✓", df_pool["Name"].apply(
            lambda n: "🏈" if n in picked_names else ""
        ))

    if "Status" in df_pool.columns:
        df_pool["Status"] = df_pool["Status"].apply(lambda s: status_badge(s if s else ""))

    col_config = {
        "Salary":     st.column_config.TextColumn("Salary"),
        "Projection": st.column_config.NumberColumn("DK Avg",  format="%.1f"),
        "Adj Proj":   st.column_config.TextColumn("Adj Proj", help="Projection adjusted with nflverse stats"),
        "Value":      st.column_config.NumberColumn("Value",   format="%.2f", help="Pts per $1k"),
        "Data":       st.column_config.TextColumn("Data",     help=DATA_SOURCE_LEGEND, width=60),
    }
    if my_picks_on:
        col_config["Slot"] = st.column_config.TextColumn("Slot", width=70)
    else:
        col_config["✓"] = st.column_config.TextColumn("✓", width=40)

    st.dataframe(
        df_pool,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
    )

    caption = f"Showing {len(visible)} of {len(players)} players  |  {DATA_SOURCE_LEGEND}"
    if my_picks_on:
        caption = f"My Picks — {len(visible)} players  |  {DATA_SOURCE_LEGEND}"
    elif picked_ids:
        caption += "  |  🏈 = in your current lineup"
    st.caption(caption)

# ---------------------------------------------------------------------------
# Lineup tab
# ---------------------------------------------------------------------------
with tab_lineup:
    result = st.session_state.last_lineup
    if result is None:
        st.info("Configure settings in the sidebar and click **Generate Lineup**.")
    else:
        remaining = SALARY_CAP - result.total_salary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Strategy",        STRATEGY_LABELS[strategy])
        c2.metric("Projected Score", f"{result.total_projection:.1f} pts")
        c3.metric("Total Salary",    f"${result.total_salary:,}")
        c4.metric("Cap Remaining",   f"${remaining:,}")

        if enriched_stats:
            enriched_count = sum(
                1 for p, _ in result.lineup
                if enriched_stats.get(p.dk_id) and enriched_stats[p.dk_id].data_source == "enriched"
            )
            st.caption(f"★ {enriched_count}/9 players enriched with nflverse stats")

        st.markdown("---")

        rows = result.to_display_rows()
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
                "Slot":   st.column_config.TextColumn("Slot",    width=70),
                "Player": st.column_config.TextColumn("Player",  width=180),
                "Pos":    st.column_config.TextColumn("Pos",     width=55),
                "Team":   st.column_config.TextColumn("Team",    width=55),
                "Opp":    st.column_config.TextColumn("Opp",     width=55),
                "Salary": st.column_config.TextColumn("Salary",  width=85),
                "Proj":   st.column_config.TextColumn("Proj",    width=65, help="Adjusted projection"),
                "DK Avg": st.column_config.TextColumn("DK Avg",  width=65, help="DraftKings AvgPointsPerGame"),
                "Value":  st.column_config.TextColumn("Value",   width=65),
                "Status": st.column_config.TextColumn("Status",  width=65),
                "Data":   st.column_config.TextColumn("Data",    width=50, help=DATA_SOURCE_LEGEND),
            },
        )

        st.markdown("---")
        st.subheader("Why these players?")

        for player, slot in result.lineup:
            ps      = enriched_stats.get(player.dk_id)
            badge   = STATUS_COLOR.get(player.status, "⚪")
            adj_str = ""
            ctx_str = ""

            if ps:
                if ps.adjusted_projection is not None and ps.data_source != "dk_only":
                    diff    = ps.adjusted_projection - player.projection
                    sign    = "+" if diff >= 0 else ""
                    adj_str = f" → adj **{ps.adjusted_projection:.1f}** ({sign}{diff:.1f})"
                if ps.implied_total is not None:
                    home_str = "home" if ps.is_home else "away"
                    ctx_str  = f" | {home_str}, implied {ps.implied_total:.1f}"
                if ps.avg_target_share is not None and player.position in ("WR","TE"):
                    ctx_str += f", {ps.avg_target_share*100:.0f}% tgt share"
                if ps.avg_snap_pct is not None and player.position in ("RB","WR","TE"):
                    ctx_str += f", {ps.avg_snap_pct*100:.0f}% snap"

            st.markdown(
                f"**{slot} — {player.name}** ({player.team} vs {player.opponent}) "
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
