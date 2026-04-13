"""
Options Premium Screener Dashboard
====================================
Mobile-friendly, cloud-deployable Streamlit dashboard for screening
elevated option premium on cash-secured puts and covered calls,
ranked by a composite Premium Quality Score (PQS).

Launch locally:   streamlit run app.py
Deploy:           Push to GitHub -> connect on share.streamlit.io
"""

import datetime as dt
import sys
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure local imports resolve
sys.path.insert(0, os.path.dirname(__file__))

from config import (
    CSP_DEFAULTS,
    CC_DEFAULTS,
    SECTOR_ETF_MAP,
    MAX_UNIVERSE_SIZE,
)
from data_fetcher import (
    build_universe,
    fetch_all_stock_info,
    fetch_historical_prices,
    fetch_all_options,
    fetch_vix,
    get_vix_regime,
    fetch_risk_free_rates,
    fetch_sector_iv,
    estimate_iv_history,
)
from calculations import (
    compute_all_hv,
    enrich_options,
    pqs_color,
)

# ---------------------------------------------------------------------------
# Page config — no sidebar, wide layout
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Options Premium Screener",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Mobile-responsive CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* ---- Hide default sidebar hamburger on mobile ---- */
[data-testid="collapsedControl"] { display: none !important; }
section[data-testid="stSidebar"] { display: none !important; }

/* ---- Base typography & spacing ---- */
.block-container {
    padding-top: 1rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    max-width: 100% !important;
}

/* ---- Header metrics: 2-col grid on mobile ---- */
[data-testid="stMetric"] {
    background: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    text-align: center;
}
[data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
    font-weight: 600;
}
[data-testid="stMetricValue"] {
    font-size: 1rem !important;
}

/* ---- Tabs: scrollable on mobile ---- */
.stTabs [data-baseweb="tab-list"] {
    gap: 0px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    flex-wrap: nowrap !important;
}
.stTabs [data-baseweb="tab"] {
    white-space: nowrap;
    padding: 0.5rem 0.8rem;
    font-size: 0.85rem;
}

/* ---- Expander (filter panel) ---- */
.streamlit-expanderHeader {
    font-size: 0.9rem !important;
    font-weight: 600;
}

/* ---- Dataframe: horizontal scroll ---- */
[data-testid="stDataFrame"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
}
[data-testid="stDataFrame"] table {
    font-size: 0.78rem !important;
    min-width: 800px;
}

/* ---- Buttons: full-width touch targets ---- */
.stButton > button {
    width: 100%;
    min-height: 48px;
    font-size: 1rem;
    border-radius: 8px;
}
.stDownloadButton > button {
    width: 100%;
    min-height: 44px;
    font-size: 0.9rem;
}

/* ---- Card styling for trade detail ---- */
.metric-card {
    background: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 0.8rem;
    text-align: center;
    margin-bottom: 0.5rem;
}
.metric-card .label { font-size: 0.7rem; color: #666; font-weight: 600; }
.metric-card .value { font-size: 1.2rem; font-weight: 700; color: #1a1a1a; }

/* ---- PQS badge ---- */
.pqs-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    color: white;
    font-weight: 700;
    font-size: 0.85rem;
}

/* ---- Mobile breakpoints ---- */
@media (max-width: 768px) {
    .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    [data-testid="stMetricValue"] { font-size: 0.9rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.65rem !important; }

    .stTabs [data-baseweb="tab"] {
        padding: 0.4rem 0.6rem;
        font-size: 0.75rem;
    }

    [data-testid="stDataFrame"] table {
        font-size: 0.7rem !important;
    }

    h1 { font-size: 1.4rem !important; }
    h2 { font-size: 1.1rem !important; }
    h3 { font-size: 1rem !important; }
}

@media (max-width: 480px) {
    .block-container {
        padding-left: 0.3rem !important;
        padding-right: 0.3rem !important;
    }
    [data-testid="stMetricValue"] { font-size: 0.8rem !important; }

    [data-testid="stDataFrame"] table {
        font-size: 0.65rem !important;
        min-width: 600px;
    }
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
for key in ["data_loaded", "enriched_puts", "enriched_calls", "vol_scanner",
            "vix_data", "risk_free", "sector_iv", "stock_info", "last_refresh"]:
    if key not in st.session_state:
        st.session_state[key] = None

if "refresh_running" not in st.session_state:
    st.session_state.refresh_running = False


# ---------------------------------------------------------------------------
# Data loading pipeline
# ---------------------------------------------------------------------------

def run_full_refresh():
    """Execute the full data fetch and enrichment pipeline."""
    st.session_state.refresh_running = True

    progress = st.progress(0, text="Starting data refresh...")
    status = st.empty()

    # --- Step 1: Build universe ---
    status.text("Building ticker universe...")
    progress.progress(2, text="Building ticker universe...")
    tickers = build_universe()

    # --- Step 2: Fetch VIX & risk-free rates & sector IV ---
    status.text("Fetching market data (VIX, rates, sector IV)...")
    progress.progress(5, text="Fetching VIX, Treasury rates, sector IV...")
    vix_data = fetch_vix()
    risk_free_data = fetch_risk_free_rates()
    sector_iv_data = fetch_sector_iv()

    rf_rate = risk_free_data.get("3mo") or risk_free_data.get("1mo") or 4.5

    st.session_state.vix_data = vix_data
    st.session_state.risk_free = risk_free_data
    st.session_state.sector_iv = sector_iv_data

    # --- Step 3: Fetch stock info ---
    def stock_progress(done, total, ticker):
        pct = 5 + int(done / total * 30)
        progress.progress(pct, text=f"Fetching stock info: {ticker} ({done}/{total})")

    status.text("Fetching stock fundamentals...")
    stock_info = fetch_all_stock_info(tickers, max_workers=20, progress_callback=stock_progress)
    st.session_state.stock_info = stock_info

    if stock_info.empty:
        st.error("Failed to fetch any stock data. Check your internet connection.")
        st.session_state.refresh_running = False
        return

    valid_tickers = stock_info["ticker"].tolist()

    # --- Step 4: Fetch historical prices & compute HV ---
    status.text("Computing historical volatility...")
    hv_cache = {}
    iv_history_cache = {}
    total_t = len(valid_tickers)
    for i, ticker in enumerate(valid_tickers):
        pct = 35 + int(i / total_t * 20)
        progress.progress(pct, text=f"Computing HV: {ticker} ({i+1}/{total_t})")
        prices = fetch_historical_prices(ticker)
        if prices is not None:
            hv_cache[ticker] = compute_all_hv(prices)
        iv_hist = estimate_iv_history(ticker)
        if iv_hist is not None:
            iv_history_cache[ticker] = iv_hist

    # --- Step 5: Fetch options chains ---
    def opts_progress(done, total, ticker):
        pct = 55 + int(done / total * 35)
        progress.progress(pct, text=f"Fetching options: {ticker} ({done}/{total})")

    status.text("Fetching options chains...")
    options_df = fetch_all_options(valid_tickers, min_dte=7, max_dte=90,
                                    max_workers=10, progress_callback=opts_progress)

    if options_df.empty:
        st.error("No options data retrieved. The market may be closed or data unavailable.")
        st.session_state.refresh_running = False
        return

    # --- Step 6: Enrich & Score ---
    progress.progress(92, text="Calculating metrics & scoring...")
    status.text("Enriching options data and computing PQS scores...")

    enriched = enrich_options(
        options_df, stock_info, hv_cache, iv_history_cache,
        sector_iv_data, risk_free=rf_rate,
    )

    if enriched.empty:
        st.error("No valid options found after enrichment.")
        st.session_state.refresh_running = False
        return

    # Split into puts and calls
    st.session_state.enriched_puts = enriched[enriched["option_type"] == "put"].copy()
    st.session_state.enriched_calls = enriched[enriched["option_type"] == "call"].copy()

    # Vol scanner: one row per ticker with best IV rank
    vol_data = []
    for ticker in valid_tickers:
        tdf = enriched[enriched["ticker"] == ticker]
        if tdf.empty:
            continue
        best = tdf.iloc[0]
        vol_data.append({
            "ticker": ticker,
            "sector": best.get("sector", "Unknown"),
            "iv": best.get("iv"),
            "hv_20": best.get("hv_20"),
            "hv_60": best.get("hv_60"),
            "iv_rank": best.get("iv_rank"),
            "iv_percentile": best.get("iv_percentile"),
            "vrp": best.get("vrp"),
            "iv_vs_sector": best.get("iv_vs_sector"),
        })
    st.session_state.vol_scanner = pd.DataFrame(vol_data)

    st.session_state.last_refresh = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.data_loaded = True
    st.session_state.refresh_running = False

    progress.progress(100, text="Done!")
    status.text("Refresh complete!")


# ---------------------------------------------------------------------------
# Inline filters (replaces sidebar — works on mobile)
# ---------------------------------------------------------------------------

def render_filters(defaults: dict, key_prefix: str) -> dict:
    """Render filter controls inside a collapsible expander."""
    with st.expander("Filters — tap to adjust", expanded=False):
        # Row 1: DTE and Delta
        c1, c2 = st.columns(2)
        with c1:
            dte_range = st.slider(
                "DTE Range", 7, 120,
                (defaults["min_dte"], defaults["max_dte"]),
                key=f"{key_prefix}_dte",
            )
        with c2:
            delta_range = st.slider(
                "Delta Range", 0.05, 0.50,
                (defaults["min_delta"], defaults["max_delta"]),
                step=0.05,
                key=f"{key_prefix}_delta",
            )

        # Row 2: IV Rank, Yield, PoP
        c3, c4, c5 = st.columns(3)
        with c3:
            min_iv_rank = st.slider(
                "Min IV Rank", 0, 100, defaults["min_iv_rank"],
                key=f"{key_prefix}_ivrank",
            )
        with c4:
            min_yield = st.number_input(
                "Min Ann. Yield %", value=defaults["min_annualized_yield"],
                min_value=0.0, step=1.0,
                key=f"{key_prefix}_yield",
            )
        with c5:
            min_pop = st.slider(
                "Min PoP %", 0, 100, int(defaults["min_pop"]),
                key=f"{key_prefix}_pop",
            )

        # Row 3: Toggles and multi-selects
        c6, c7, c8 = st.columns(3)
        with c6:
            exclude_earnings = st.checkbox(
                "Exclude earnings window",
                value=defaults["exclude_earnings"],
                key=f"{key_prefix}_earn",
            )
        with c7:
            all_sectors = list(SECTOR_ETF_MAP.keys()) + ["Unknown"]
            sectors = st.multiselect(
                "Sectors", all_sectors, default=all_sectors,
                key=f"{key_prefix}_sectors",
            )
        with c8:
            cap_tiers = st.multiselect(
                "Market Cap", ["Large", "Mid", "Small", "Unknown"],
                default=["Large", "Mid", "Small", "Unknown"],
                key=f"{key_prefix}_cap",
            )

    return {
        "min_dte": dte_range[0],
        "max_dte": dte_range[1],
        "min_delta": delta_range[0],
        "max_delta": delta_range[1],
        "min_iv_rank": min_iv_rank,
        "min_yield": min_yield,
        "min_pop": min_pop,
        "exclude_earnings": exclude_earnings,
        "sectors": sectors,
        "cap_tiers": cap_tiers,
    }


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Apply user-selected filters to the enriched options DataFrame."""
    if df is None or df.empty:
        return pd.DataFrame()

    mask = (
        (df["dte"] >= filters["min_dte"])
        & (df["dte"] <= filters["max_dte"])
        & (df["ann_net_yield"] >= filters["min_yield"])
        & (df["pop"] >= filters["min_pop"])
        & (df["sector"].isin(filters["sectors"]))
        & (df["market_cap_tier"].isin(filters["cap_tiers"]))
    )

    if "delta" in df.columns:
        has_delta = df["delta"].notna()
        delta_ok = (df["delta"] >= filters["min_delta"]) & (df["delta"] <= filters["max_delta"])
        mask = mask & (delta_ok | ~has_delta)

    if filters["min_iv_rank"] > 0:
        has_ivr = df["iv_rank"].notna()
        ivr_ok = df["iv_rank"] >= filters["min_iv_rank"]
        mask = mask & (ivr_ok | ~has_ivr)

    if filters["exclude_earnings"]:
        mask = mask & (~df["spans_earnings"])

    return df[mask].copy()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

# Compact column set for mobile — show the most important columns first
DISPLAY_COLS_CSP = [
    "ticker", "strike", "expiry", "dte", "mid",
    "ann_net_yield", "iv", "iv_rank", "vrp", "delta",
    "pop", "breakeven_dist", "spread_pct", "pqs", "flags",
]

DISPLAY_COLS_CC = [
    "ticker", "strike", "expiry", "dte", "mid",
    "ann_net_yield", "iv", "iv_rank", "vrp", "delta",
    "pop", "breakeven_dist", "upside_cap", "spread_pct", "pqs", "flags",
]

COL_LABELS = {
    "ticker": "Ticker", "sector": "Sector", "price": "Price", "strike": "Strike",
    "dte": "DTE", "expiry": "Expiry", "bid": "Bid", "ask": "Ask", "mid": "Mid",
    "ann_net_yield": "Yield%", "iv": "IV%", "iv_rank": "IVR",
    "vrp": "VRP", "delta": "Delta", "pop": "PoP%",
    "breakeven": "BE", "breakeven_dist": "BE%",
    "upside_cap": "Cap%", "spread_pct": "Sprd%",
    "volume": "Vol", "open_interest": "OI", "pqs": "PQS", "flags": "Flags",
}


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Add a human-readable flags column."""
    if df.empty:
        return df
    flags = []
    for _, row in df.iterrows():
        f = []
        if row.get("spans_earnings"):
            f.append("Earn")
        if row.get("ex_div_date"):
            f.append("Div")
        if (row.get("short_pct_float") or 0) > 0.10:
            f.append(f"SI{row['short_pct_float']:.0%}")
        flags.append(",".join(f) if f else "")
    df = df.copy()
    df["flags"] = flags
    return df


def style_pqs(val):
    """Color PQS cells."""
    color = pqs_color(val) if isinstance(val, (int, float)) else "#ffffff"
    return f"background-color: {color}; color: white; font-weight: bold"


def render_table(df: pd.DataFrame, columns: list[str], top_n: int = 25):
    """Render a styled, sortable table optimized for mobile scroll."""
    if df.empty:
        st.info("No results match the current filters. Try adjusting your criteria.")
        return

    df = add_flags(df)
    display = df.sort_values("pqs", ascending=False).head(top_n)

    cols = [c for c in columns if c in display.columns]
    display = display[cols].reset_index(drop=True)
    display.index = display.index + 1
    display.index.name = "#"

    display = display.rename(columns=COL_LABELS)

    # Format numeric columns for compactness
    format_map = {}
    for col in display.columns:
        if col in ("Yield%", "IV%", "IVR", "VRP", "PoP%", "BE%", "Cap%", "Sprd%"):
            format_map[col] = "{:.1f}"
        elif col in ("Delta",):
            format_map[col] = "{:.2f}"
        elif col in ("Mid", "Strike", "BE"):
            format_map[col] = "{:.2f}"
        elif col == "PQS":
            format_map[col] = "{:.0f}"

    styled = display.style.map(
        style_pqs, subset=["PQS"] if "PQS" in display.columns else []
    ).format(format_map, na_rep="—")

    st.dataframe(
        styled,
        use_container_width=True,
        height=min(700, 35 * len(display) + 50),
    )

    csv = display.to_csv(index=True)
    st.download_button("Export CSV", csv, "options_screen.csv", "text/csv",
                       key=f"csv_{columns[0]}_{top_n}")


# ---------------------------------------------------------------------------
# Trade detail panel — card-based layout for mobile
# ---------------------------------------------------------------------------

def _metric_card(label: str, value: str, color: str = "#1a1a1a") -> str:
    return f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value" style="color:{color}">{value}</div>
    </div>"""


def render_trade_detail(df: pd.DataFrame):
    """Render a detailed view for a selected ticker — mobile-friendly cards."""
    if df is None or df.empty:
        return

    tickers = sorted(df["ticker"].unique())
    selected = st.selectbox("Select ticker for detail view", tickers)

    ticker_data = df[df["ticker"] == selected].sort_values("pqs", ascending=False)
    if ticker_data.empty:
        return

    top = ticker_data.iloc[0]

    # Metric cards in a 2x3 grid (works on any screen width)
    pqs_val = top["pqs"]
    pqs_c = pqs_color(pqs_val)
    iv_rank_str = f"{top['iv_rank']:.0f}" if pd.notna(top.get("iv_rank")) else "N/A"

    cards_html = f"""
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:8px; margin-bottom:1rem;">
        {_metric_card("Price", f"${top['price']:.2f}")}
        {_metric_card("Strike", f"${top['strike']:.2f}")}
        {_metric_card("DTE", f"{top['dte']}")}
        {_metric_card("Ann. Yield", f"{top['ann_net_yield']:.1f}%", "#1565c0")}
        {_metric_card("PoP", f"{top['pop']:.1f}%", "#2e7d32")}
        {_metric_card("PQS", f"{pqs_val:.0f}", pqs_c)}
        {_metric_card("IV", f"{top['iv']:.1f}%")}
        {_metric_card("IV Rank", iv_rank_str)}
        {_metric_card("Breakeven", f"${top['breakeven']:.2f}")}
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)

    # Payoff diagram — responsive
    st.markdown("#### Payoff at Expiry")
    strike = top["strike"]
    mid = top["mid"]
    opt_type = top["option_type"]

    price_range = np.linspace(strike * 0.7, strike * 1.3, 200)

    if opt_type == "put":
        pnl = np.where(
            price_range >= strike,
            mid * 100,
            (mid - (strike - price_range)) * 100,
        )
    else:
        pnl = np.where(
            price_range <= strike,
            mid * 100,
            (mid - (price_range - strike)) * 100,
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=price_range, y=pnl,
        mode="lines", name="P&L",
        line=dict(color="#1976d2", width=2),
        fill="tozeroy",
        fillcolor="rgba(25, 118, 210, 0.1)",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_vline(x=strike, line_dash="dot", line_color="red",
                  annotation_text=f"Strike ${strike:.0f}")
    fig.add_vline(x=top["breakeven"], line_dash="dot", line_color="orange",
                  annotation_text=f"BE ${top['breakeven']:.0f}")
    fig.update_layout(
        xaxis_title="Stock Price at Expiry",
        yaxis_title="P&L / Contract ($)",
        height=300,
        margin=dict(t=10, b=40, l=40, r=10),
        font=dict(size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Greeks — compact horizontal
    st.markdown("#### Greeks")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Delta", f"{top.get('delta', 0):.3f}" if pd.notna(top.get("delta")) else "—")
    g2.metric("Gamma", f"{top.get('gamma', 0):.5f}" if top.get("gamma") else "—")
    g3.metric("Theta", f"{top.get('theta', 0):.4f}" if pd.notna(top.get("theta")) else "—")
    g4.metric("Vega", f"{top.get('vega', 0):.4f}" if top.get("vega") else "—")

    # Other strikes for this ticker
    st.markdown(f"#### All Contracts: {selected}")
    other_cols = ["strike", "expiry", "dte", "mid", "ann_net_yield", "iv", "delta", "pop", "pqs"]
    other_cols = [c for c in other_cols if c in ticker_data.columns]
    st.dataframe(
        ticker_data[other_cols].reset_index(drop=True),
        use_container_width=True,
        height=min(400, 35 * len(ticker_data) + 50),
    )


# ---------------------------------------------------------------------------
# Vol scanner tab
# ---------------------------------------------------------------------------

def render_vol_scanner(vol_df: pd.DataFrame):
    """Render the volatility scanner heatmap/table."""
    if vol_df is None or vol_df.empty:
        st.info("No volatility data available. Run a refresh first.")
        return

    display = vol_df.sort_values("iv_rank", ascending=False).reset_index(drop=True)
    display.index = display.index + 1
    display.index.name = "#"

    def color_iv_rank(val):
        if pd.isna(val):
            return ""
        if val >= 80:
            return "background-color: #2e7d32; color: white"
        if val >= 60:
            return "background-color: #689f38; color: white"
        if val >= 40:
            return "background-color: #f9a825; color: black"
        if val >= 20:
            return "background-color: #ff8f00; color: black"
        return "background-color: #c62828; color: white"

    display = display.rename(columns={
        "ticker": "Ticker", "sector": "Sector", "iv": "IV%",
        "hv_20": "HV20", "hv_60": "HV60", "iv_rank": "IVR",
        "iv_percentile": "IV%ile", "vrp": "VRP", "iv_vs_sector": "vs Sect",
    })

    st.dataframe(
        display.style.map(color_iv_rank, subset=["IVR"] if "IVR" in display.columns else []),
        use_container_width=True,
        height=min(700, 35 * len(display) + 50),
    )

    csv = display.to_csv(index=True)
    st.download_button("Export Vol Scanner CSV", csv, "vol_scanner.csv", "text/csv")


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # --- Header ---
    st.markdown("## Options Premium Screener")

    # Refresh button — prominent, full-width, at the top
    if st.button(
        "Refresh All Data",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.refresh_running,
    ):
        run_full_refresh()
        st.rerun()

    # Header metrics — responsive 2-col on mobile, 5-col on desktop
    vix = st.session_state.vix_data
    rf = st.session_state.risk_free

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        lr = st.session_state.last_refresh
        st.metric("Refreshed", lr.split(" ")[1] if lr else "Never",
                  help=f"Full timestamp: {lr}" if lr else "Click Refresh to load data")
    with m2:
        if vix and vix.get("current"):
            regime = get_vix_regime(vix["current"])
            st.metric("VIX", f"{vix['current']:.1f}", help=f"Regime: {regime} | Source: {vix['source']}")
        else:
            st.metric("VIX", "—")
    with m3:
        if vix and vix.get("percentile_1y"):
            st.metric("VIX %ile", f"{vix['percentile_1y']:.0f}%", help="1-year VIX percentile rank")
        else:
            st.metric("VIX %ile", "—")
    with m4:
        if rf and rf.get("3mo"):
            st.metric("3M Rate", f"{rf['3mo']:.2f}%", help=f"Source: {rf.get('source','')}")
        else:
            st.metric("3M Rate", "—")
    with m5:
        if rf and rf.get("1yr"):
            st.metric("1Y Rate", f"{rf['1yr']:.2f}%", help=f"Source: {rf.get('source','')}")
        else:
            st.metric("1Y Rate", "—")

    # --- Pre-load state ---
    if not st.session_state.data_loaded:
        st.markdown("---")
        st.info("Tap **Refresh All Data** above to load live options data. "
                "Initial load takes a few minutes (~150 tickers).")

        st.markdown("""
### How it works
1. **Refresh** pulls live options data from Yahoo Finance for S&P 500 + high-volume names
2. Each contract is scored with a **Premium Quality Score (PQS)** from 0–100:

| Weight | Factor |
|--------|--------|
| 20% | Annualized net yield |
| 15% | IV Rank |
| 15% | Volatility Risk Premium (IV − HV) |
| 15% | Probability of Profit |
| 10% | Breakeven distance |
| 10% | Liquidity (bid-ask spread) |
| 5% | Theta decay efficiency |
| 10% | Fundamental safety |

3. Top 25 ideas surface for **Cash-Secured Puts** and **Covered Calls**

### Data Sources
All data is publicly sourced with timestamps for traceability:
- **Options chains, fundamentals, greeks** — Yahoo Finance (`yfinance`)
- **Historical volatility** — Calculated from Yahoo Finance daily closes
- **IV Rank / IV Percentile** — Derived from 1-year HV proxy
- **VIX / Market regime** — CBOE VIX via Yahoo Finance
- **Risk-free rate** — FRED / Yahoo Finance Treasury proxies
- **Sector IV** — Yahoo Finance sector ETF options (XLK, XLF, XLE, etc.)
        """)
        return

    # --- Tabs ---
    tab_csp, tab_cc, tab_vol, tab_detail = st.tabs([
        "Puts (CSP)", "Calls (CC)", "Vol Scanner", "Detail",
    ])

    # --- Tab 1: Cash-Secured Puts ---
    with tab_csp:
        st.caption(f"Top cash-secured put ideas by PQS | Source: Yahoo Finance | {st.session_state.last_refresh or ''}")
        filters = render_filters(CSP_DEFAULTS, "csp")
        filtered = apply_filters(st.session_state.enriched_puts, filters)
        render_table(filtered, DISPLAY_COLS_CSP, top_n=25)

    # --- Tab 2: Covered Calls ---
    with tab_cc:
        st.caption(f"Top covered call ideas by PQS | Source: Yahoo Finance | {st.session_state.last_refresh or ''}")
        filters = render_filters(CC_DEFAULTS, "cc")
        filtered = apply_filters(st.session_state.enriched_calls, filters)
        render_table(filtered, DISPLAY_COLS_CC, top_n=25)

    # --- Tab 3: Volatility Scanner ---
    with tab_vol:
        st.caption("All tickers ranked by IV Rank — find the richest vol | Calculated from 1-year HV proxy")
        render_vol_scanner(st.session_state.vol_scanner)

    # --- Tab 4: Trade Detail ---
    with tab_detail:
        st.caption("Drill into a ticker for payoff diagrams, greeks, and alternative strikes")
        detail_type = st.radio("Strategy", ["Cash-Secured Put", "Covered Call"], horizontal=True)
        if detail_type == "Cash-Secured Put":
            render_trade_detail(st.session_state.enriched_puts)
        else:
            render_trade_detail(st.session_state.enriched_calls)

    # --- Footer ---
    st.markdown("---")
    st.caption(
        "**Sources**: Yahoo Finance · FRED · CBOE VIX · "
        "All calculations derived from public data. "
        "Not financial advice."
    )


if __name__ == "__main__":
    main()
