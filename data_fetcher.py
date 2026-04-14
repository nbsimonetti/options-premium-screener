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

# Central Time for display, Eastern for market hours check
_CT = pytz.timezone("US/Central")
_ET = pytz.timezone("US/Eastern")


def _now_str() -> str:
    """Current time in Central Time."""
    return dt.datetime.now(_CT).strftime("%Y-%m-%d %H:%M:%S CT")


# ---------------------------------------------------------------------------
# Market hours detection
# ---------------------------------------------------------------------------

def is_market_open() -> bool:
    """Check if US equity markets are currently open (9:30-16:00 ET, weekdays)."""
    now_et = dt.datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def market_status_message() -> str:
    """Return a human-readable market status string in Central Time."""
    now_ct = dt.datetime.now(_CT)
    if is_market_open():
        return f"Market OPEN ({now_ct.strftime('%I:%M %p CT')}) — showing live data"
    return f"Market CLOSED ({now_ct.strftime('%a %I:%M %p CT')}) — showing data as of last close"


def _get_price_robust(ticker_obj: yf.Ticker, info: dict) -> float | None:
    """
    Robust price extraction that works both during and after market hours.
    Tries multiple fields and falls back to the last historical close.
    """
    # Try live/recent price fields in order of preference
    for field in [
        "currentPrice",
        "regularMarketPrice",
        "previousClose",
        "regularMarketPreviousClose",
        "open",
        "regularMarketOpen",
    ]:
        val = info.get(field)
        if val and val > 0:
            return float(val)

    # Final fallback: last close from price history
    try:
        hist = ticker_obj.history(period="5d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# 1. Ticker universe
# ---------------------------------------------------------------------------

def build_universe() -> list[str]:
    """Build the screening universe: S&P 500 + supplemental high-volume names."""
    sp500 = get_sp500_tickers()
    combined = list(dict.fromkeys(sp500 + SUPPLEMENTAL_TICKERS))  # dedupe, preserve order
    return combined[:MAX_UNIVERSE_SIZE]


# ---------------------------------------------------------------------------
# 2. Stock fundamentals (batch)
# ---------------------------------------------------------------------------

def fetch_stock_info(ticker: str) -> tuple[dict | None, str | None]:
    """Fetch key fundamental data for a single ticker via yfinance.
    Returns (data_dict, warning_string). Warning is None on success."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        price = _get_price_robust(t, info)
        if not price or price <= 0:
            return None, f"{ticker}: no valid price found"
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
        }, None
    except Exception as e:
        return None, f"{ticker}: {type(e).__name__}: {e}"


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
                          progress_callback=None) -> tuple[pd.DataFrame, list[str]]:
    """Fetch fundamentals for all tickers in parallel.
    Returns (DataFrame, warnings_list)."""
    results = []
    warnings = []
    total = len(tickers)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_stock_info, t): t for t in tickers}
        for f in as_completed(futures):
            done += 1
            ticker = futures[f]
            if progress_callback:
                progress_callback(done, total, ticker)
            try:
                res, warn = f.result()
            except Exception as e:
                warnings.append(f"{ticker}: executor error: {e}")
                continue
            if warn:
                warnings.append(warn)
            if res and res.get("price"):
                results.append(res)
    return pd.DataFrame(results), warnings


# ---------------------------------------------------------------------------
# 3. Historical prices (batch download for speed)
# ---------------------------------------------------------------------------

def fetch_historical_prices_batch(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Batch-download daily close prices for all tickers at once.
    Returns {ticker: DataFrame with Close column}. Much faster than per-ticker calls."""
    try:
        data = yf.download(tickers, period=period, auto_adjust=True,
                           threads=True, progress=False)
        if data.empty:
            return {}
        result = {}
        if len(tickers) == 1:
            if "Close" in data.columns:
                result[tickers[0]] = data[["Close"]].dropna()
        else:
            for ticker in tickers:
                try:
                    close = data["Close"][ticker].dropna()
                    if not close.empty:
                        result[ticker] = close.to_frame("Close")
                except (KeyError, TypeError):
                    continue
        return result
    except Exception:
        return {}


def fetch_historical_prices(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """Fetch daily close prices for a single ticker (fallback)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, auto_adjust=True)
        if hist.empty:
            return None
        return hist[["Close"]].copy()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 4. Options chains
# ---------------------------------------------------------------------------

def fetch_options_chain(ticker: str, min_dte: int = 7, max_dte: int = 90) -> tuple[pd.DataFrame | None, str | None]:
    """Fetch options chain for a ticker. Returns (DataFrame, warning)."""
    try:
        t = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            return None, f"{ticker}: no options expirations available"

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
            return None, f"{ticker}: no chains in DTE range {min_dte}-{max_dte}"
        return pd.concat(frames, ignore_index=True), None
    except Exception as e:
        return None, f"{ticker}: {type(e).__name__}: {e}"


def fetch_all_options(tickers: list[str], min_dte: int = 7, max_dte: int = 90,
                       max_workers: int = 10, progress_callback=None) -> tuple[pd.DataFrame, list[str]]:
    """Fetch options chains for all tickers in parallel.
    Returns (DataFrame, warnings_list)."""
    results = []
    warnings = []
    total = len(tickers)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_options_chain, t, min_dte, max_dte): t for t in tickers}
        for f in as_completed(futures):
            done += 1
            ticker = futures[f]
            if progress_callback:
                progress_callback(done, total, ticker)
            try:
                res, warn = f.result()
            except Exception as e:
                warnings.append(f"{ticker}: executor error: {e}")
                continue
            if warn:
                warnings.append(warn)
            if res is not None and not res.empty:
                results.append(res)
    if not results:
        return pd.DataFrame(), warnings
    return pd.concat(results, ignore_index=True), warnings


# ---------------------------------------------------------------------------
# 5. VIX data
# ---------------------------------------------------------------------------

def fetch_vix() -> dict:
    """Fetch current VIX level and 1-year history for percentile calc."""
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


# ---------------------------------------------------------------------------
# 6. Risk-free rates from FRED
# ---------------------------------------------------------------------------

def fetch_risk_free_rates(api_key: str | None = None) -> dict:
    """
    Fetch Treasury yields from FRED.
    Works without an API key by scraping the FRED page;
    with an API key uses the official API.
    """
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
                # Fallback: use yfinance for Treasury ETFs as proxy
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


# ---------------------------------------------------------------------------
# 7. Sector ETF IV (for relative comparison)
# ---------------------------------------------------------------------------

def fetch_sector_iv() -> dict:
    """Fetch ATM IV for each sector ETF from the nearest monthly expiry."""
    sector_ivs = {}
    for etf in SECTOR_ETFS:
        try:
            t = yf.Ticker(etf)
            exps = t.options
            if not exps:
                continue
            # Pick the first expiry that's 14+ days out
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


# ---------------------------------------------------------------------------
# 8. Historical IV for IV Rank / IV Percentile
# ---------------------------------------------------------------------------

def estimate_iv_history(ticker: str, periods: int = 252) -> pd.Series | None:
    """
    Estimate historical IV by computing rolling 20-day HV from daily returns
    as a proxy when true IV history isn't available through yfinance.
    For IV Rank/Percentile we use the ATM call IV at each point — but since
    historical chain data is not freely available, we use HV as a proxy scaled
    by a typical IV/HV ratio.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2y", auto_adjust=True)
        if len(hist) < 60:
            return None
        log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
        hv_20 = log_ret.rolling(20).std() * np.sqrt(252) * 100
        # Scale HV by typical IV/HV ratio (~1.2) to approximate IV
        iv_proxy = hv_20 * 1.2
        return iv_proxy.dropna().tail(periods)
    except Exception:
        return None
