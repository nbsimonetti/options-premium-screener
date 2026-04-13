# Options Premium Screener — Debug & Rebuild Prompt

## Context

I have an Options Premium Screener dashboard deployed on Render at:
**https://options-premium-screener-fd1y.onrender.com/**

The GitHub repo is: **https://github.com/nbsimonetti/options-premium-screener** (public, branch: `master`)

The app is currently built with Streamlit and displays persistent errors at the bottom of the page. The dashboard is meant to screen for elevated option premium on cash-secured puts and covered calls, rank them with a composite scoring system, and be usable from a phone or desktop anywhere.

---

## The Errors

The deployed site shows Streamlit errors including but not limited to:

1. **`StreamlitDuplicateElementKey`** — Multiple elements share the same `key` argument. This happens because multiple tabs/components render widgets with identical keys. Every `st.download_button`, `st.slider`, `st.selectbox`, `st.checkbox`, `st.multiselect`, `st.number_input`, and `st.radio` call needs a globally unique `key` across ALL tabs, since Streamlit renders all tab contents in a single pass even if only one tab is visible.

2. **Potential additional errors** from the `render_filters()` function being called twice (once for CSP tab, once for CC tab) — both expanders have the same label "Filters — tap to adjust" and while the widget keys use `key_prefix`, the expander itself and any other non-keyed elements may collide.

3. **Potential errors from `render_trade_detail()`** being called twice (once for puts, once for calls based on radio selection) — the `st.selectbox` for ticker selection has no explicit key and could collide.

4. **The Vol Scanner tab** has a `st.download_button` with no explicit `key` argument, which may collide with other download buttons.

---

## Your Task

### Phase 1: Audit & Fix Every Key Collision

Systematically audit every file for Streamlit element key collisions. The rule is simple: every interactive widget in the entire app must have a unique `key` string, even across tabs (because Streamlit renders all tabs simultaneously). Specifically check:

- `render_filters()` is called with `key_prefix="csp"` and `key_prefix="cc"` — verify every widget inside uses the prefix
- `render_table()` is called with `tab_id="csp"` and `tab_id="cc"` — verify the download button key is unique
- `render_trade_detail()` is called for both puts and calls — the `st.selectbox` and any `st.radio` inside need unique keys
- `render_vol_scanner()` has a download button — needs a unique key
- The `st.radio("Strategy", ...)` in the Detail tab needs a unique key
- Any `st.metric`, `st.plotly_chart`, or other element that accepts a `key` parameter

### Phase 2: Evaluate Whether Streamlit Is the Right Framework

Streamlit has fundamental design constraints that cause recurring issues for this app:

1. **Full-page re-execution model** — Every interaction re-runs the entire script top-to-bottom. This means all tabs render simultaneously (causing key collisions), and any long-running data fetch blocks the entire UI.

2. **Session state is ephemeral** — On Render's free tier, the server sleeps after 15 min of no traffic. When it wakes, all session state is gone. We added a pickle-based disk cache as a workaround, but this is fragile.

3. **No true tab isolation** — Streamlit "tabs" are cosmetic. All content renders in one pass, which is why widget keys must be globally unique. This is a recurring source of bugs.

4. **Mobile limitations** — Streamlit's sidebar, expanders, and data tables were designed for desktop. We've injected significant custom CSS to make it mobile-usable, fighting the framework rather than working with it.

5. **No background data loading** — Streamlit can't fetch data in a background thread while showing the UI. The user sees a blank or frozen page during multi-minute data refreshes.

**Evaluate these alternatives and recommend whether to stay on Streamlit or migrate:**

| Framework | Pros | Cons |
|-----------|------|------|
| **Streamlit** (current) | Fast to prototype, built-in widgets, easy deploy | Key collisions, full re-execution, no background tasks, weak mobile |
| **Dash (Plotly)** | Callback-based (no re-execution), true tab isolation, native Plotly charts, background callbacks | More boilerplate, steeper learning curve |
| **FastAPI + vanilla HTML/JS** | Full control, REST API for data, real background tasks, true mobile-first | Most code to write, no pre-built widgets |
| **Panel (HoloViz)** | Similar to Streamlit but with better state management and background tasks | Smaller community, fewer deploy options |
| **NiceGUI** | Vue.js-based, true component isolation, background tasks, mobile-friendly | Newer framework, smaller ecosystem |

Make a clear recommendation based on:
- Eliminating the class of key-collision bugs permanently
- Mobile-first usability without CSS hacks
- Ability to show cached data instantly while refreshing in the background
- Ease of deployment on Render free tier
- Maintainability for a single developer

### Phase 3: Implement the Fix

Based on your Phase 2 recommendation:

**If staying on Streamlit:** Fix every key collision, add comprehensive `key=` arguments to every widget, and add a comment block at the top of `app.py` documenting the key naming convention (e.g., `{tab}_{widget}_{qualifier}`). Test that all 4 tabs render without errors simultaneously.

**If migrating to a different framework:** Rewrite the app in the recommended framework, preserving ALL existing functionality:
- 4 tabs: Cash-Secured Puts, Covered Calls, Vol Scanner, Trade Detail
- Inline collapsible filters (DTE, delta, IV rank, yield, PoP, sectors, market cap, earnings toggle)
- Sortable data tables with PQS color-coding
- Payoff diagram (Plotly) in Trade Detail
- Greeks display
- CSV export per table
- Market open/closed banner
- Header metrics (VIX, rates, last refresh time)
- Auto-load from disk cache on cold start
- Background data refresh that doesn't block the UI
- Mobile-responsive layout (works on phone screens)
- Refresh button that re-fetches all data

Keep these backend files unchanged — they are the data layer and work correctly:
- `config.py` — scoring weights, defaults, ticker universe
- `data_fetcher.py` — all Yahoo Finance / FRED data sourcing
- `calculations.py` — HV, IV rank, greeks, PQS scoring, enrichment pipeline

Only rewrite the **presentation layer** (`app.py`) and update `requirements.txt` / `render.yaml` as needed.

### Phase 4: Automated Testing — Prove the Errors Are Gone

Before declaring the work done, you MUST run the following verification steps and show the output of each. Do NOT skip any step. If any step fails, fix the root cause and re-run ALL steps from the beginning.

#### 4A. Static Key Collision Audit

Write and run a Python script (`test_keys.py`) that:
1. Parses the final `app.py` (or whatever the main app file is) using `ast` or regex
2. Extracts every `key=` argument from every Streamlit widget call (or equivalent framework widget)
3. Asserts that ALL keys are unique — no duplicates
4. Prints the full list of keys found and a PASS/FAIL verdict
5. If the framework was changed away from Streamlit, adapt this test to verify the equivalent constraint (e.g., no duplicate HTML `id` attributes, no duplicate Dash component IDs)

```
Expected output:
Found 23 widget keys:
  csp_dte, csp_delta, csp_ivrank, csp_yield, csp_pop, csp_earn, csp_sectors, csp_cap,
  cc_dte, cc_delta, cc_ivrank, cc_yield, cc_pop, cc_earn, cc_sectors, cc_cap,
  csv_csp_25, csv_cc_25, csv_vol, detail_strategy, detail_ticker, ...
Duplicates: NONE
RESULT: PASS
```

#### 4B. Import & Syntax Validation

Run the app module through Python's import system to catch syntax errors, missing imports, and circular dependencies:

```bash
python -c "import app; print('Import OK')"
```

This must succeed with no errors or warnings (Streamlit "missing ScriptRunContext" warnings are acceptable).

#### 4C. Data Pipeline Smoke Test

Run a quick end-to-end test that fetches data for 3 tickers, enriches them, and verifies the output DataFrame has all required columns:

```python
from data_fetcher import fetch_stock_info, fetch_all_options, fetch_historical_prices, estimate_iv_history, fetch_sector_iv
from calculations import compute_all_hv, enrich_options
import pandas as pd

tickers = ['AAPL', 'TSLA', 'NVDA']
# ... fetch, enrich, and assert:
# - enriched DataFrame is not empty
# - enriched DataFrame has all required display columns
# - PQS scores are between 0 and 100
# - Both puts and calls are present
# - No NaN in critical columns (ticker, strike, dte, mid, pqs)
```

#### 4D. Simulated Full-Page Render (Streamlit-specific, skip if migrated)

If staying on Streamlit, run a headless test that simulates a full page render and catches duplicate key errors at runtime:

```python
import subprocess, sys

# Launch Streamlit in headless mode for 10 seconds, capture stderr
result = subprocess.run(
    [sys.executable, "-m", "streamlit", "run", "app.py",
     "--server.headless", "true", "--server.port", "8599"],
    capture_output=True, text=True, timeout=30
)

# Check stderr for DuplicateElementKey or any Streamlit error
assert "DuplicateElementKey" not in result.stderr, f"DUPLICATE KEY ERROR: {result.stderr}"
assert "Error" not in result.stderr or "ScriptRunContext" in result.stderr, f"RUNTIME ERROR: {result.stderr}"
print("Headless render: PASS — no duplicate key errors")
```

#### 4E. Framework-Specific Runtime Test (if migrated away from Streamlit)

If migrated to Dash, FastAPI, NiceGUI, or another framework:

1. Start the app server in the background
2. Wait for it to be ready (poll the health endpoint or port)
3. Use `requests` or `urllib` to fetch the main page and every tab/route
4. Assert each returns HTTP 200
5. Assert the response body contains expected content markers (e.g., "Cash-Secured Puts", "Covered Calls", "Vol Scanner", "PQS")
6. Assert no error strings in the response body (e.g., "Traceback", "500 Internal Server Error", "KeyError", "DuplicateElementKey")
7. Kill the server

```python
import requests, subprocess, time, sys

# Start server
proc = subprocess.Popen([sys.executable, "app.py"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(5)  # wait for startup

try:
    # Test main page
    r = requests.get("http://localhost:8050/")  # adjust port for framework
    assert r.status_code == 200, f"Main page returned {r.status_code}"
    assert "Traceback" not in r.text, "Traceback found in page"
    assert "Error" not in r.text or "error" in r.text.lower() and "no error" in r.text.lower()
    
    # Verify key content markers exist
    for marker in ["Cash-Secured Put", "Covered Call", "Vol Scanner", "PQS", "Yahoo Finance"]:
        assert marker in r.text, f"Missing content marker: {marker}"
    
    print("Runtime test: PASS — all pages render without errors")
finally:
    proc.terminate()
```

#### 4F. After-Hours Data Verification

Verify the app loads data correctly when the market is closed:

```python
from data_fetcher import is_market_open, fetch_stock_info

# Confirm current market status
print(f"Market open: {is_market_open()}")

# Fetch a stock and verify price is not None regardless of market status
for ticker in ['AAPL', 'TSLA', 'NVDA']:
    info = fetch_stock_info(ticker)
    assert info is not None, f"{ticker}: fetch_stock_info returned None"
    assert info['price'] is not None and info['price'] > 0, f"{ticker}: price is {info['price']}"
    print(f"{ticker}: ${info['price']:.2f} — OK")

print("After-hours data test: PASS")
```

#### 4G. Test Summary Gate

After running ALL tests above, print a final summary:

```
=== TEST SUMMARY ===
4A. Key Collision Audit:     PASS / FAIL
4B. Import Validation:       PASS / FAIL
4C. Data Pipeline Smoke:     PASS / FAIL
4D. Headless Render:         PASS / FAIL (or SKIPPED if migrated)
4E. Runtime Route Test:      PASS / FAIL (or SKIPPED if on Streamlit)
4F. After-Hours Data:        PASS / FAIL

OVERALL: PASS / FAIL
```

**If ANY test shows FAIL:** Fix the issue, then re-run ALL tests from 4A. Do not declare the work complete until OVERALL is PASS.

**If ALL tests PASS:** Commit the changes, push to GitHub, and confirm Render will auto-redeploy. Provide the final commit hash.

---

## Current File Contents

### requirements.txt
```
streamlit>=1.30.0,<2.0.0
yfinance>=1.2.0,<2.0.0
pandas>=2.0.0,<3.1.0
numpy>=1.24.0,<3.0.0
plotly>=5.18.0,<7.0.0
requests>=2.31.0,<3.0.0
scipy>=1.11.0,<2.0.0
pytz>=2023.3
```

### render.yaml
```yaml
services:
  - type: web
    name: options-premium-screener
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
    envVars:
      - key: PYTHON_VERSION
        value: "3.11"
```

### .streamlit/config.toml
```toml
[theme]
primaryColor = "#1976d2"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f8f9fa"
textColor = "#1a1a1a"
font = "sans serif"

[server]
headless = true
enableCORS = true
enableXsrfProtection = true
maxUploadSize = 5

[browser]
gatherUsageStats = false

[runner]
magicEnabled = false
```

### config.py
```python
"""
Configuration constants for the Options Premium Screener Dashboard.
Scoring weights, default filters, sector mappings, and ticker universe helpers.
"""

import pandas as pd
import requests

PQS_WEIGHTS = {
    "annualized_yield": 0.20,
    "iv_rank": 0.15,
    "vrp": 0.15,
    "pop": 0.15,
    "breakeven_dist": 0.10,
    "liquidity": 0.10,
    "theta_efficiency": 0.05,
    "fundamental_safety": 0.10,
}

CSP_DEFAULTS = {
    "min_dte": 14,
    "max_dte": 60,
    "min_delta": 0.15,
    "max_delta": 0.35,
    "min_iv_rank": 30,
    "min_annualized_yield": 10.0,
    "min_pop": 65.0,
    "exclude_earnings": True,
}

CC_DEFAULTS = {
    "min_dte": 14,
    "max_dte": 45,
    "min_delta": 0.20,
    "max_delta": 0.40,
    "min_iv_rank": 30,
    "min_annualized_yield": 10.0,
    "min_pop": 65.0,
    "exclude_earnings": True,
}

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}

ETF_SECTOR_MAP = {v: k for k, v in SECTOR_ETF_MAP.items()}
SECTOR_ETFS = list(SECTOR_ETF_MAP.values())

VIX_REGIMES = {
    "Low Vol": (0, 15),
    "Normal": (15, 20),
    "Elevated": (20, 30),
    "Crisis": (30, 100),
}

MARKET_CAP_TIERS = {
    "Large": 10_000_000_000,
    "Mid": 2_000_000_000,
    "Small": 0,
}

CACHE_TTL_SECONDS = 900

FRED_SERIES = {
    "1mo": "DGS1MO",
    "3mo": "DGS3MO",
    "1yr": "DGS1",
}

def get_sp500_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        return sorted(tickers)
    except Exception:
        return _FALLBACK_TICKERS

SUPPLEMENTAL_TICKERS = [
    "MARA", "RIOT", "RIVN", "LCID", "PLTR", "SOFI", "HOOD", "SNAP",
    "RBLX", "DKNG", "NIO", "XPEV", "LI", "FUBO", "IONQ", "RGTI",
    "SMCI", "ARM", "MSTR", "COIN", "AFRM", "UPST", "LUNR", "RKLB",
]

_FALLBACK_TICKERS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK-B",
    "UNH", "JNJ", "JPM", "V", "PG", "XOM", "HD", "CVX", "MA", "ABBV",
    "MRK", "LLY", "PEP", "KO", "COST", "AVGO", "WMT", "MCD", "CSCO",
    "ACN", "TMO", "ABT", "DHR", "NEE", "LIN", "PM", "TXN", "UNP",
    "RTX", "LOW", "HON", "AMGN", "IBM", "GS", "CAT", "BA", "SPGI",
    "DE", "AXP", "BLK", "SYK", "ISRG", "MDLZ", "ADI", "GILD", "MMC",
    "VRTX", "REGN", "BKNG", "LRCX", "PANW", "KLAC", "SNPS", "CDNS",
    "CME", "SHW", "CI", "ZTS", "APD", "CMG", "EQIX", "ITW", "ETN",
    "AON", "MCO", "PLD", "WM", "GE", "EMR", "MSI", "ADSK", "ROP",
    "NXPI", "FTNT", "ADP", "ABNB", "CRWD", "DDOG", "NET", "SNOW",
    "ENPH", "FSLR", "SQ", "SHOP", "ROKU", "TTD", "PINS", "ZS",
    "OKTA", "MDB", "BILL", "HUBS", "VEEV", "WDAY", "TEAM", "SPLK",
]

MAX_UNIVERSE_SIZE = 150
```

### data_fetcher.py
```python
"""
Data sourcing layer for the Options Premium Screener Dashboard.
All fetches are timestamped and attributed to their public source.
Works both during market hours and after-hours using last-close data.
"""

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf

from config import (
    SECTOR_ETFS,
    SECTOR_ETF_MAP,
    SUPPLEMENTAL_TICKERS,
    MAX_UNIVERSE_SIZE,
    FRED_SERIES,
    get_sp500_tickers,
)

_ET = pytz.timezone("US/Eastern")


def _now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_market_open() -> bool:
    now_et = dt.datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def market_status_message() -> str:
    if is_market_open():
        return "Market OPEN — showing live data"
    now_et = dt.datetime.now(_ET)
    return f"Market CLOSED ({now_et.strftime('%a %I:%M %p ET')}) — showing data as of last close"


def _get_price_robust(ticker_obj: yf.Ticker, info: dict) -> float | None:
    for field in [
        "currentPrice", "regularMarketPrice", "previousClose",
        "regularMarketPreviousClose", "open", "regularMarketOpen",
    ]:
        val = info.get(field)
        if val and val > 0:
            return float(val)
    try:
        hist = ticker_obj.history(period="5d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def build_universe() -> list[str]:
    sp500 = get_sp500_tickers()
    combined = list(dict.fromkeys(sp500 + SUPPLEMENTAL_TICKERS))
    return combined[:MAX_UNIVERSE_SIZE]


def fetch_stock_info(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        price = _get_price_robust(t, info)
        return {
            "ticker": ticker,
            "price": price,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "sector": info.get("sector", "Unknown"),
            "dividend_yield": info.get("dividendYield", 0) or 0,
            "ex_div_date": _safe_timestamp(info.get("exDividendDate")),
            "earnings_date": _get_next_earnings(t),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageDailyVolume10Day") or info.get("averageVolume"),
            "short_pct_float": info.get("shortPercentOfFloat", 0) or 0,
            "source": "Yahoo Finance",
            "fetched_at": _now_str(),
        }
    except Exception:
        return None


def _safe_timestamp(val) -> str | None:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return dt.datetime.fromtimestamp(val).strftime("%Y-%m-%d")
        return str(val)
    except Exception:
        return None


def _get_next_earnings(t: yf.Ticker) -> str | None:
    try:
        cal = t.calendar
        if cal is None:
            return None
        if isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.columns:
                dates = cal["Earnings Date"]
            elif "Earnings Date" in cal.index:
                dates = cal.loc["Earnings Date"]
            else:
                return None
            future = [d for d in pd.to_datetime(dates) if d >= pd.Timestamp.now()]
            return min(future).strftime("%Y-%m-%d") if future else None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
            future = [d for d in pd.to_datetime(dates) if d >= pd.Timestamp.now()]
            return min(future).strftime("%Y-%m-%d") if future else None
        return None
    except Exception:
        return None


def fetch_all_stock_info(tickers: list[str], max_workers: int = 20,
                          progress_callback=None) -> pd.DataFrame:
    results = []
    total = len(tickers)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_stock_info, t): t for t in tickers}
        for f in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total, futures[f])
            res = f.result()
            if res and res.get("price"):
                results.append(res)
    return pd.DataFrame(results)


def fetch_historical_prices(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, auto_adjust=True)
        if hist.empty:
            return None
        return hist[["Close"]].copy()
    except Exception:
        return None


def fetch_options_chain(ticker: str, min_dte: int = 7, max_dte: int = 90) -> pd.DataFrame | None:
    try:
        t = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            return None
        today = dt.date.today()
        frames = []
        for exp_str in expirations:
            exp_date = dt.datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < min_dte or dte > max_dte:
                continue
            chain = t.option_chain(exp_str)
            for opt_type, df in [("put", chain.puts), ("call", chain.calls)]:
                if df.empty:
                    continue
                df = df.copy()
                df["ticker"] = ticker
                df["expiry"] = exp_str
                df["dte"] = dte
                df["option_type"] = opt_type
                df["source"] = "Yahoo Finance"
                df["fetched_at"] = _now_str()
                frames.append(df)
        if not frames:
            return None
        return pd.concat(frames, ignore_index=True)
    except Exception:
        return None


def fetch_all_options(tickers: list[str], min_dte: int = 7, max_dte: int = 90,
                       max_workers: int = 10, progress_callback=None) -> pd.DataFrame:
    results = []
    total = len(tickers)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_options_chain, t, min_dte, max_dte): t for t in tickers}
        for f in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total, futures[f])
            res = f.result()
            if res is not None and not res.empty:
                results.append(res)
    if not results:
        return pd.DataFrame()
    return pd.concat(results, ignore_index=True)


def fetch_vix() -> dict:
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1y")
        current = hist["Close"].iloc[-1] if not hist.empty else None
        ma20 = hist["Close"].rolling(20).mean().iloc[-1] if len(hist) >= 20 else current
        pctile = (hist["Close"] < current).mean() * 100 if current and not hist.empty else None
        return {
            "current": round(current, 2) if current else None,
            "ma20": round(ma20, 2) if ma20 else None,
            "percentile_1y": round(pctile, 1) if pctile is not None else None,
            "source": "CBOE VIX via Yahoo Finance (^VIX)",
            "fetched_at": _now_str(),
        }
    except Exception:
        return {"current": None, "ma20": None, "percentile_1y": None,
                "source": "CBOE VIX via Yahoo Finance (^VIX)", "fetched_at": _now_str()}


def get_vix_regime(vix_level: float | None) -> str:
    if vix_level is None:
        return "Unknown"
    from config import VIX_REGIMES
    for label, (lo, hi) in VIX_REGIMES.items():
        if lo <= vix_level < hi:
            return label
    return "Crisis"


def fetch_risk_free_rates(api_key: str | None = None) -> dict:
    rates = {}
    for label, series_id in FRED_SERIES.items():
        try:
            if api_key:
                url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=5"
                resp = requests.get(url, timeout=10)
                data = resp.json()
                obs = data.get("observations", [])
                for o in obs:
                    if o["value"] != ".":
                        rates[label] = float(o["value"])
                        break
            else:
                proxy_map = {"1mo": "^IRX", "3mo": "^IRX", "1yr": "^FVX"}
                ticker = proxy_map.get(label, "^IRX")
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if not hist.empty:
                    rates[label] = round(hist["Close"].iloc[-1], 2)
        except Exception:
            rates[label] = None
    rates["source"] = "FRED (DGS1MO, DGS3MO, DGS1)" if api_key else "Yahoo Finance Treasury proxies"
    rates["fetched_at"] = _now_str()
    return rates


def fetch_sector_iv() -> dict:
    sector_ivs = {}
    for etf in SECTOR_ETFS:
        try:
            t = yf.Ticker(etf)
            exps = t.options
            if not exps:
                continue
            today = dt.date.today()
            target_exp = None
            for e in exps:
                d = dt.datetime.strptime(e, "%Y-%m-%d").date()
                if (d - today).days >= 14:
                    target_exp = e
                    break
            if not target_exp:
                target_exp = exps[0]
            chain = t.option_chain(target_exp)
            calls = chain.calls
            info = t.info or {}
            price = _get_price_robust(t, info)
            if price and not calls.empty:
                calls["dist"] = abs(calls["strike"] - price)
                atm = calls.loc[calls["dist"].idxmin()]
                iv = atm.get("impliedVolatility")
                if iv:
                    sector_ivs[etf] = round(iv * 100, 2)
        except Exception:
            continue
    sector_ivs["source"] = "Yahoo Finance (sector ETF options)"
    sector_ivs["fetched_at"] = _now_str()
    return sector_ivs


def estimate_iv_history(ticker: str, periods: int = 252) -> pd.Series | None:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2y", auto_adjust=True)
        if len(hist) < 60:
            return None
        log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
        hv_20 = log_ret.rolling(20).std() * np.sqrt(252) * 100
        iv_proxy = hv_20 * 1.2
        return iv_proxy.dropna().tail(periods)
    except Exception:
        return None
```

### calculations.py
```python
"""
Metric computation and PQS scoring for the Options Premium Screener Dashboard.
"""

import datetime as dt
import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import PQS_WEIGHTS, SECTOR_ETF_MAP, MARKET_CAP_TIERS


def _bs_d1(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))

def bs_delta(S, K, T, r, sigma, option_type):
    if T <= 0 or sigma <= 0: return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    return float(norm.cdf(d1)) if option_type == "call" else float(norm.cdf(d1) - 1)

def bs_theta(S, K, T, r, sigma, option_type):
    if T <= 0 or sigma <= 0: return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    common = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type == "call":
        theta_annual = common - r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        theta_annual = common + r * K * math.exp(-r * T) * norm.cdf(-d2)
    return float(theta_annual / 365)

def bs_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0: return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    return float(norm.pdf(d1) / (S * sigma * math.sqrt(T)))

def bs_vega(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    return float(S * norm.pdf(d1) * math.sqrt(T) / 100)

def compute_hv(prices, window=20):
    if prices is None or len(prices) < window + 1: return None
    log_ret = np.log(prices["Close"] / prices["Close"].shift(1)).dropna()
    if len(log_ret) < window: return None
    return float(log_ret.tail(window).std() * np.sqrt(252) * 100)

def compute_all_hv(prices):
    return {"hv_20": compute_hv(prices, 20), "hv_60": compute_hv(prices, 60), "hv_252": compute_hv(prices, 252)}

def compute_iv_rank(current_iv, iv_history):
    if iv_history is None or len(iv_history) < 20 or current_iv is None: return None
    lo, hi = iv_history.min(), iv_history.max()
    if hi == lo: return 50.0
    return float(np.clip((current_iv - lo) / (hi - lo) * 100, 0, 100))

def compute_iv_percentile(current_iv, iv_history):
    if iv_history is None or len(iv_history) < 20 or current_iv is None: return None
    return float((iv_history < current_iv).mean() * 100)

def compute_premium_metrics(row, option_type):
    bid = row.get("bid", 0) or 0
    ask = row.get("ask", 0) or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    strike = row.get("strike", 0)
    dte = row.get("dte", 1) or 1
    stock_price = row.get("price", 0) or 0
    if strike <= 0 or mid <= 0:
        return {"mid": 0, "raw_yield": 0, "ann_yield": 0, "net_yield": 0, "ann_net_yield": 0}
    raw_yield = (mid / strike) * 100
    ann_yield = raw_yield * (365 / dte) if dte > 0 else 0
    if option_type == "put":
        capital = strike - mid
        net_yield = (mid / capital) * 100 if capital > 0 else 0
    else:
        net_yield = (mid / stock_price) * 100 if stock_price > 0 else 0
    ann_net_yield = net_yield * (365 / dte) if dte > 0 else 0
    return {"mid": round(mid, 2), "raw_yield": round(raw_yield, 2), "ann_yield": round(ann_yield, 2),
            "net_yield": round(net_yield, 2), "ann_net_yield": round(ann_net_yield, 2)}

def compute_probability_metrics(row, option_type):
    delta = abs(row.get("delta", 0) or 0)
    mid = row.get("mid", 0) or 0
    strike = row.get("strike", 0)
    stock_price = row.get("price", 0) or 0
    if option_type == "put":
        pop = (1 - delta) * 100
        breakeven = strike - mid
        breakeven_dist = ((stock_price - breakeven) / stock_price * 100) if stock_price > 0 else 0
        max_loss = breakeven * 100
    else:
        pop = min((1 - delta + (mid / stock_price if stock_price > 0 else 0)) * 100, 99.9)
        breakeven = stock_price - mid
        breakeven_dist = ((stock_price - breakeven) / stock_price * 100) if stock_price > 0 else 0
        max_loss = (stock_price - mid) * 100
    return {"pop": round(pop, 1), "breakeven": round(breakeven, 2),
            "breakeven_dist": round(breakeven_dist, 2), "max_loss": round(max_loss, 2)}

def compute_upside_cap(strike, stock_price):
    if stock_price <= 0: return 0
    return round((strike - stock_price) / stock_price * 100, 2)

def compute_theta_efficiency(theta, option_price):
    if theta is None or option_price <= 0: return 0
    return round(abs(theta) / option_price * 100, 2)

def compute_liquidity_metrics(row):
    bid = row.get("bid", 0) or 0
    ask = row.get("ask", 0) or 0
    mid = (bid + ask) / 2
    spread = ask - bid
    spread_pct = (spread / mid * 100) if mid > 0 else 100
    vol = row.get("volume", 0)
    oi = row.get("openInterest", 0)
    return {"spread": round(spread, 2), "spread_pct": round(spread_pct, 2),
            "volume": int(vol) if pd.notna(vol) else 0, "open_interest": int(oi) if pd.notna(oi) else 0}

def classify_market_cap(market_cap):
    if market_cap is None: return "Unknown"
    if market_cap >= MARKET_CAP_TIERS["Large"]: return "Large"
    if market_cap >= MARKET_CAP_TIERS["Mid"]: return "Mid"
    return "Small"

def earnings_within_dte(earnings_date_str, dte):
    if not earnings_date_str: return False
    try:
        earn_date = dt.datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
        days_to_earnings = (earn_date - dt.date.today()).days
        return 0 <= days_to_earnings <= dte
    except Exception:
        return False

# PQS scoring functions (0-10 scale each)
def _score_annualized_yield(ann_yield, risk_free=4.5):
    if ann_yield <= 0: return 0
    score = min(ann_yield / 2.0, 10.0)
    if ann_yield < risk_free * 2: score = max(score - 1, 0)
    return score

def _score_iv_rank(iv_rank):
    if iv_rank is None: return 3
    if iv_rank >= 80: return 10
    if iv_rank >= 50: return 7 + (iv_rank - 50) / 30 * 2
    if iv_rank >= 30: return 4 + (iv_rank - 30) / 20 * 3
    return max(iv_rank / 30 * 3, 0)

def _score_vrp(vrp):
    if vrp is None: return 3
    if vrp < 0: return 0
    if vrp >= 15: return 10
    if vrp >= 5: return 6 + (vrp - 5) / 10 * 4
    return vrp / 5 * 3

def _score_pop(pop):
    if pop >= 90: return 10
    if pop >= 80: return 9
    if pop >= 70: return 7
    if pop >= 60: return 5
    return max(pop / 60 * 2, 0)

def _score_breakeven_dist(dist):
    if dist >= 10: return 10
    if dist >= 5: return 7
    if dist >= 2: return 4
    return max(dist / 2, 0)

def _score_liquidity(spread_pct):
    if spread_pct <= 0: return 5
    if spread_pct < 2: return 10
    if spread_pct < 5: return 7
    if spread_pct < 10: return 4
    return 1

def _score_theta_efficiency(theta_pct):
    if theta_pct >= 3: return 10
    if theta_pct >= 1.5: return 8
    if theta_pct >= 0.5: return 5
    return 2

def _score_fundamental_safety(market_cap_tier, short_pct, spans_earnings):
    score = 5.0
    if market_cap_tier == "Large": score += 2
    elif market_cap_tier == "Mid": score += 1
    elif market_cap_tier == "Small": score -= 1
    if short_pct > 0.20: score -= 2
    elif short_pct > 0.10: score -= 1
    if not spans_earnings: score += 2
    return max(min(score, 10), 0)

def compute_pqs(row, risk_free=4.5):
    scores = {
        "annualized_yield": _score_annualized_yield(row.get("ann_net_yield", 0), risk_free),
        "iv_rank": _score_iv_rank(row.get("iv_rank")),
        "vrp": _score_vrp(row.get("vrp")),
        "pop": _score_pop(row.get("pop", 0)),
        "breakeven_dist": _score_breakeven_dist(row.get("breakeven_dist", 0)),
        "liquidity": _score_liquidity(row.get("spread_pct", 100)),
        "theta_efficiency": _score_theta_efficiency(row.get("theta_efficiency", 0)),
        "fundamental_safety": _score_fundamental_safety(
            row.get("market_cap_tier", "Unknown"), row.get("short_pct_float", 0), row.get("spans_earnings", False)),
    }
    weighted = sum(scores[k] * PQS_WEIGHTS[k] for k in PQS_WEIGHTS)
    return min(round(weighted * 10, 1), 100.0)

def pqs_label(score):
    if score >= 80: return "Strong Sell Premium"
    if score >= 60: return "Favorable"
    if score >= 40: return "Neutral / Watch"
    return "Avoid / Poor Risk-Reward"

def pqs_color(score):
    if score >= 80: return "#2e7d32"
    if score >= 60: return "#689f38"
    if score >= 40: return "#f9a825"
    return "#c62828"

def enrich_options(options_df, stock_info_df, hv_cache, iv_history_cache, sector_iv, risk_free=4.5):
    if options_df.empty: return pd.DataFrame()
    merged = options_df.merge(
        stock_info_df[["ticker", "price", "market_cap", "sector", "dividend_yield",
                        "ex_div_date", "earnings_date", "fifty_two_week_high",
                        "fifty_two_week_low", "avg_volume", "short_pct_float"]],
        on="ticker", how="left")
    rows = []
    for _, row in merged.iterrows():
        ticker = row["ticker"]
        opt_type = row["option_type"]
        iv = (row.get("impliedVolatility") or 0) * 100
        hv_data = hv_cache.get(ticker, {})
        hv_20 = hv_data.get("hv_20")
        hv_60 = hv_data.get("hv_60")
        vrp = (iv - hv_20) if (hv_20 is not None and iv > 0) else None
        iv_hist = iv_history_cache.get(ticker)
        iv_rank = compute_iv_rank(iv, iv_hist)
        iv_pctile = compute_iv_percentile(iv, iv_hist)
        sector = row.get("sector", "Unknown")
        sector_etf = SECTOR_ETF_MAP.get(sector)
        sector_iv_val = sector_iv.get(sector_etf) if sector_etf else None
        iv_vs_sector = (iv - sector_iv_val) if sector_iv_val else None
        stock_price = row.get("price") or 0
        pm = compute_premium_metrics(row, opt_type)
        strike = row.get("strike", 0)
        dte = row.get("dte", 1) or 1
        T = dte / 365.0
        sigma = iv / 100.0
        r = risk_free / 100.0
        if stock_price > 0 and strike > 0 and sigma > 0:
            delta_val = bs_delta(stock_price, strike, T, r, sigma, opt_type)
            theta_val = bs_theta(stock_price, strike, T, r, sigma, opt_type)
            gamma_val = bs_gamma(stock_price, strike, T, r, sigma)
            vega_val = bs_vega(stock_price, strike, T, r, sigma)
        else:
            delta_val = theta_val = None
            gamma_val = vega_val = 0
        row_with_mid = row.copy()
        row_with_mid["mid"] = pm["mid"]
        if delta_val is not None: row_with_mid["delta"] = delta_val
        prob = compute_probability_metrics(row_with_mid, opt_type)
        theta_eff = compute_theta_efficiency(theta_val, pm["mid"]) if theta_val else 0
        liq = compute_liquidity_metrics(row)
        cap_tier = classify_market_cap(row.get("market_cap"))
        spans_earn = earnings_within_dte(row.get("earnings_date"), row.get("dte", 0))
        hi52 = row.get("fifty_two_week_high") or 0
        lo52 = row.get("fifty_two_week_low") or 0
        week52_pctile = ((stock_price - lo52) / (hi52 - lo52) * 100) if (hi52 > lo52) else 50
        upside_cap = compute_upside_cap(row.get("strike", 0), stock_price) if opt_type == "call" else None
        enriched = {
            "ticker": ticker, "sector": sector, "price": stock_price,
            "strike": row.get("strike"), "expiry": row.get("expiry"), "dte": row.get("dte"),
            "option_type": opt_type, "bid": row.get("bid"), "ask": row.get("ask"),
            "mid": pm["mid"], "ann_net_yield": pm["ann_net_yield"], "raw_yield": pm["raw_yield"],
            "iv": round(iv, 1),
            "hv_20": round(hv_20, 1) if hv_20 else None,
            "hv_60": round(hv_60, 1) if hv_60 else None,
            "iv_rank": round(iv_rank, 1) if iv_rank is not None else None,
            "iv_percentile": round(iv_pctile, 1) if iv_pctile is not None else None,
            "vrp": round(vrp, 1) if vrp is not None else None,
            "iv_vs_sector": round(iv_vs_sector, 1) if iv_vs_sector is not None else None,
            "delta": round(abs(delta_val), 3) if delta_val is not None else None,
            "theta": round(theta_val, 4) if theta_val is not None else None,
            "gamma": round(gamma_val, 5) if gamma_val else 0,
            "vega": round(vega_val, 4) if vega_val else 0,
            "pop": prob["pop"], "breakeven": prob["breakeven"],
            "breakeven_dist": prob["breakeven_dist"], "max_loss": prob["max_loss"],
            "upside_cap": upside_cap,
            "spread": liq["spread"], "spread_pct": liq["spread_pct"],
            "volume": liq["volume"], "open_interest": liq["open_interest"],
            "theta_efficiency": theta_eff,
            "market_cap": row.get("market_cap"), "market_cap_tier": cap_tier,
            "short_pct_float": row.get("short_pct_float", 0),
            "dividend_yield": row.get("dividend_yield", 0),
            "earnings_date": row.get("earnings_date"), "spans_earnings": spans_earn,
            "ex_div_date": row.get("ex_div_date"),
            "week52_pctile": round(week52_pctile, 1),
            "avg_volume": row.get("avg_volume"),
            "source": "Yahoo Finance", "fetched_at": row.get("fetched_at"),
        }
        enriched_series = pd.Series(enriched)
        enriched["pqs"] = compute_pqs(enriched_series, risk_free)
        enriched["pqs_label"] = pqs_label(enriched["pqs"])
        rows.append(enriched)
    result = pd.DataFrame(rows)
    result = result[result["mid"] > 0].copy()
    result = result[result["spread_pct"] < 50].copy()
    puts_mask = (result["option_type"] == "put") & (result["strike"] <= result["price"] * 1.05)
    calls_mask = (result["option_type"] == "call") & (result["strike"] >= result["price"] * 0.95)
    result = result[puts_mask | calls_mask].copy()
    return result
```

---

## Deployment Requirements

- The app runs on **Render free tier** (web service, Python 3.11)
- Start command is defined in `render.yaml`
- Must work when market is open OR closed (after-hours data from last close)
- Must auto-load cached data on cold start (Render sleeps after 15 min idle)
- Mobile-first responsive design (used on phone)
- All data sourced from Yahoo Finance with timestamps
- The GitHub repo is `nbsimonetti/options-premium-screener`, branch `master`
- Render auto-deploys on push to `master`

## Output — Required Deliverables

You must provide ALL of the following. Incomplete output is not acceptable.

1. **Phase 2 recommendation** — Clear verdict on whether to stay on Streamlit or migrate, with reasoning.

2. **Complete rewritten files** — Full, working code for every file that changes. Do not abbreviate, use placeholder comments like `# ... rest of code ...`, or truncate. If a file is 500 lines, output all 500 lines. Files that don't change (config.py, data_fetcher.py, calculations.py) should NOT be re-output.

3. **`test_keys.py`** — The static key collision audit script from Phase 4A. This file must be runnable standalone.

4. **`test_app.py`** — A combined test runner that executes all Phase 4 tests (4A–4F) and prints the summary gate (4G). This file must be runnable standalone with `python test_app.py`.

5. **Test output** — Show the actual console output from running `python test_app.py`. Every test must show PASS. If any test shows FAIL, you must fix the issue and re-run before presenting the output.

6. **Git commands** — The exact git commands to stage, commit, and push the changes. Include the commit message.

Do NOT declare the task complete until the test summary gate shows `OVERALL: PASS`.
