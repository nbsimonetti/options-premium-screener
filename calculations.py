"""
Metric computation and PQS scoring for the Options Premium Screener Dashboard.
"""

import datetime as dt
import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import PQS_WEIGHTS, SECTOR_ETF_MAP, MARKET_CAP_TIERS


# ---------------------------------------------------------------------------
# Black-Scholes Greeks (since yfinance doesn't provide them)
# ---------------------------------------------------------------------------

def _bs_d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes delta. sigma is decimal (e.g. 0.30 for 30%)."""
    if T <= 0 or sigma <= 0:
        return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    if option_type == "call":
        return float(norm.cdf(d1))
    return float(norm.cdf(d1) - 1)


def bs_theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes theta (per day). sigma is decimal."""
    if T <= 0 or sigma <= 0:
        return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    common = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type == "call":
        theta_annual = common - r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        theta_annual = common + r * K * math.exp(-r * T) * norm.cdf(-d2)
    return float(theta_annual / 365)


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    return float(norm.pdf(d1) / (S * sigma * math.sqrt(T)))


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0
    d1 = _bs_d1(S, K, T, r, sigma)
    return float(S * norm.pdf(d1) * math.sqrt(T) / 100)  # per 1% IV move


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------

def compute_hv(prices: pd.DataFrame, window: int = 20) -> float | None:
    """Compute annualized historical volatility from daily closes."""
    if prices is None or len(prices) < window + 1:
        return None
    log_ret = np.log(prices["Close"] / prices["Close"].shift(1)).dropna()
    if len(log_ret) < window:
        return None
    return float(log_ret.tail(window).std() * np.sqrt(252) * 100)


def compute_all_hv(prices: pd.DataFrame) -> dict:
    """Return HV-20, HV-60, HV-252."""
    return {
        "hv_20": compute_hv(prices, 20),
        "hv_60": compute_hv(prices, 60),
        "hv_252": compute_hv(prices, 252),
    }


# ---------------------------------------------------------------------------
# IV Rank & IV Percentile
# ---------------------------------------------------------------------------

def compute_iv_rank(current_iv: float, iv_history: pd.Series | None) -> float | None:
    """IV Rank = (Current - 52wk Low) / (52wk High - 52wk Low) * 100."""
    if iv_history is None or len(iv_history) < 20 or current_iv is None:
        return None
    lo = iv_history.min()
    hi = iv_history.max()
    if hi == lo:
        return 50.0
    return float(np.clip((current_iv - lo) / (hi - lo) * 100, 0, 100))


def compute_iv_percentile(current_iv: float, iv_history: pd.Series | None) -> float | None:
    """IV Percentile = % of days in past year where IV was below current."""
    if iv_history is None or len(iv_history) < 20 or current_iv is None:
        return None
    return float((iv_history < current_iv).mean() * 100)


# ---------------------------------------------------------------------------
# Premium Yield Metrics
# ---------------------------------------------------------------------------

def compute_premium_metrics(row: pd.Series, option_type: str) -> dict:
    """
    Compute premium yield metrics for a single option contract.
    row must have: bid, ask, strike, dte, stock_price
    """
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
    else:  # call
        net_yield = (mid / stock_price) * 100 if stock_price > 0 else 0

    ann_net_yield = net_yield * (365 / dte) if dte > 0 else 0

    return {
        "mid": round(mid, 2),
        "raw_yield": round(raw_yield, 2),
        "ann_yield": round(ann_yield, 2),
        "net_yield": round(net_yield, 2),
        "ann_net_yield": round(ann_net_yield, 2),
    }


# ---------------------------------------------------------------------------
# Probability & Risk Metrics
# ---------------------------------------------------------------------------

def compute_probability_metrics(row: pd.Series, option_type: str) -> dict:
    """
    Compute PoP, breakeven, breakeven distance, max loss.
    row needs: delta (impliedVolatility-based or from chain), mid, strike, stock_price
    """
    delta = abs(row.get("delta", 0) or 0)
    mid = row.get("mid", 0) or 0
    strike = row.get("strike", 0)
    stock_price = row.get("price", 0) or 0

    if option_type == "put":
        pop = (1 - delta) * 100
        breakeven = strike - mid
        breakeven_dist = ((stock_price - breakeven) / stock_price * 100) if stock_price > 0 else 0
        max_loss = (breakeven) * 100  # per contract, if stock goes to 0
    else:  # call
        pop = (1 - delta + (mid / stock_price if stock_price > 0 else 0)) * 100
        pop = min(pop, 99.9)
        breakeven = stock_price - mid
        breakeven_dist = ((stock_price - breakeven) / stock_price * 100) if stock_price > 0 else 0
        max_loss = (stock_price - mid) * 100  # per contract

    return {
        "pop": round(pop, 1),
        "breakeven": round(breakeven, 2),
        "breakeven_dist": round(breakeven_dist, 2),
        "max_loss": round(max_loss, 2),
    }


def compute_upside_cap(strike: float, stock_price: float) -> float:
    """For covered calls: % upside forfeited."""
    if stock_price <= 0:
        return 0
    return round((strike - stock_price) / stock_price * 100, 2)


# ---------------------------------------------------------------------------
# Theta Efficiency
# ---------------------------------------------------------------------------

def compute_theta_efficiency(theta: float | None, option_price: float) -> float:
    """Daily theta as % of option price."""
    if theta is None or option_price <= 0:
        return 0
    return round(abs(theta) / option_price * 100, 2)


# ---------------------------------------------------------------------------
# Liquidity Metrics
# ---------------------------------------------------------------------------

def compute_liquidity_metrics(row: pd.Series) -> dict:
    bid = row.get("bid", 0) or 0
    ask = row.get("ask", 0) or 0
    mid = (bid + ask) / 2
    spread = ask - bid
    spread_pct = (spread / mid * 100) if mid > 0 else 100

    vol = row.get("volume", 0)
    oi = row.get("openInterest", 0)

    return {
        "spread": round(spread, 2),
        "spread_pct": round(spread_pct, 2),
        "volume": int(vol) if pd.notna(vol) else 0,
        "open_interest": int(oi) if pd.notna(oi) else 0,
    }


# ---------------------------------------------------------------------------
# Fundamental Safety
# ---------------------------------------------------------------------------

def classify_market_cap(market_cap: float | None) -> str:
    if market_cap is None:
        return "Unknown"
    if market_cap >= MARKET_CAP_TIERS["Large"]:
        return "Large"
    if market_cap >= MARKET_CAP_TIERS["Mid"]:
        return "Mid"
    return "Small"


def earnings_within_dte(earnings_date_str: str | None, dte: int) -> bool:
    """Check if the next earnings date falls within the option's DTE window."""
    if not earnings_date_str:
        return False
    try:
        earn_date = dt.datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
        today = dt.date.today()
        days_to_earnings = (earn_date - today).days
        return 0 <= days_to_earnings <= dte
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PQS Component Scorers (each returns 0–10)
# ---------------------------------------------------------------------------

def _score_annualized_yield(ann_yield: float, risk_free: float = 4.5) -> float:
    """Linear scale: 0% -> 0, 8% -> 5, 20%+ -> 10. Subtract 1 if < 2x risk-free."""
    if ann_yield <= 0:
        return 0
    score = min(ann_yield / 2.0, 10.0)  # 20% -> 10
    if ann_yield < risk_free * 2:
        score = max(score - 1, 0)
    return score


def _score_iv_rank(iv_rank: float | None) -> float:
    if iv_rank is None:
        return 3
    if iv_rank >= 80:
        return 10
    if iv_rank >= 50:
        return 7 + (iv_rank - 50) / 30 * 2
    if iv_rank >= 30:
        return 4 + (iv_rank - 30) / 20 * 3
    return max(iv_rank / 30 * 3, 0)


def _score_vrp(vrp: float | None) -> float:
    if vrp is None:
        return 3
    if vrp < 0:
        return 0
    if vrp >= 15:
        return 10
    if vrp >= 5:
        return 6 + (vrp - 5) / 10 * 4
    return vrp / 5 * 3


def _score_pop(pop: float) -> float:
    if pop >= 90:
        return 10
    if pop >= 80:
        return 9
    if pop >= 70:
        return 7
    if pop >= 60:
        return 5
    return max(pop / 60 * 2, 0)


def _score_breakeven_dist(dist: float) -> float:
    if dist >= 10:
        return 10
    if dist >= 5:
        return 7
    if dist >= 2:
        return 4
    return max(dist / 2, 0)


def _score_liquidity(spread_pct: float) -> float:
    if spread_pct <= 0:
        return 5
    if spread_pct < 2:
        return 10
    if spread_pct < 5:
        return 7
    if spread_pct < 10:
        return 4
    return 1


def _score_theta_efficiency(theta_pct: float) -> float:
    if theta_pct >= 3:
        return 10
    if theta_pct >= 1.5:
        return 8
    if theta_pct >= 0.5:
        return 5
    return 2


def _score_fundamental_safety(market_cap_tier: str, short_pct: float,
                                spans_earnings: bool) -> float:
    score = 5.0
    if market_cap_tier == "Large":
        score += 2
    elif market_cap_tier == "Mid":
        score += 1
    elif market_cap_tier == "Small":
        score -= 1

    if short_pct > 0.20:
        score -= 2
    elif short_pct > 0.10:
        score -= 1

    if not spans_earnings:
        score += 2

    return max(min(score, 10), 0)


# ---------------------------------------------------------------------------
# Composite PQS Score
# ---------------------------------------------------------------------------

def compute_pqs(row: pd.Series, risk_free: float = 4.5) -> float:
    """
    Compute the Premium Quality Score (0–100) for a single option candidate.
    row must contain all computed metrics.
    """
    scores = {
        "annualized_yield": _score_annualized_yield(row.get("ann_net_yield", 0), risk_free),
        "iv_rank": _score_iv_rank(row.get("iv_rank")),
        "vrp": _score_vrp(row.get("vrp")),
        "pop": _score_pop(row.get("pop", 0)),
        "breakeven_dist": _score_breakeven_dist(row.get("breakeven_dist", 0)),
        "liquidity": _score_liquidity(row.get("spread_pct", 100)),
        "theta_efficiency": _score_theta_efficiency(row.get("theta_efficiency", 0)),
        "fundamental_safety": _score_fundamental_safety(
            row.get("market_cap_tier", "Unknown"),
            row.get("short_pct_float", 0),
            row.get("spans_earnings", False),
        ),
    }

    weighted = sum(scores[k] * PQS_WEIGHTS[k] for k in PQS_WEIGHTS)
    pqs = round(weighted * 10, 1)  # Scale 0–10 weighted avg to 0–100
    return min(pqs, 100.0)


def pqs_label(score: float) -> str:
    if score >= 80:
        return "Strong Sell Premium"
    if score >= 60:
        return "Favorable"
    if score >= 40:
        return "Neutral / Watch"
    return "Avoid / Poor Risk-Reward"


def pqs_color(score: float) -> str:
    if score >= 80:
        return "#2e7d32"  # green
    if score >= 60:
        return "#689f38"  # yellow-green
    if score >= 40:
        return "#f9a825"  # yellow
    return "#c62828"  # red


# ---------------------------------------------------------------------------
# Full pipeline: enrich options DataFrame with all computed metrics
# ---------------------------------------------------------------------------

def enrich_options(
    options_df: pd.DataFrame,
    stock_info_df: pd.DataFrame,
    hv_cache: dict,
    iv_history_cache: dict,
    sector_iv: dict,
    risk_free: float = 4.5,
) -> pd.DataFrame:
    """
    Join options data with stock fundamentals, compute all metrics,
    and score with PQS.
    """
    if options_df.empty:
        return pd.DataFrame()

    # Merge stock info
    merged = options_df.merge(
        stock_info_df[["ticker", "price", "market_cap", "sector", "dividend_yield",
                        "ex_div_date", "earnings_date", "fifty_two_week_high",
                        "fifty_two_week_low", "avg_volume", "short_pct_float"]],
        on="ticker",
        how="left",
    )

    rows = []
    for _, row in merged.iterrows():
        ticker = row["ticker"]
        opt_type = row["option_type"]

        # IV from chain (yfinance gives decimal, convert to %)
        iv = (row.get("impliedVolatility") or 0) * 100

        # HV
        hv_data = hv_cache.get(ticker, {})
        hv_20 = hv_data.get("hv_20")
        hv_60 = hv_data.get("hv_60")

        # VRP
        vrp = (iv - hv_20) if (hv_20 is not None and iv > 0) else None

        # IV Rank & Percentile
        iv_hist = iv_history_cache.get(ticker)
        iv_rank = compute_iv_rank(iv, iv_hist)
        iv_pctile = compute_iv_percentile(iv, iv_hist)

        # Sector IV comparison
        sector = row.get("sector", "Unknown")
        sector_etf = SECTOR_ETF_MAP.get(sector)
        sector_iv_val = sector_iv.get(sector_etf) if sector_etf else None
        iv_vs_sector = (iv - sector_iv_val) if sector_iv_val else None

        # Stock price (extract early for greeks calc)
        stock_price = row.get("price") or 0

        # Premium metrics
        pm = compute_premium_metrics(row, opt_type)

        # Compute greeks via Black-Scholes (yfinance doesn't provide them)
        strike = row.get("strike", 0)
        dte = row.get("dte", 1) or 1
        T = dte / 365.0
        sigma = iv / 100.0  # convert % to decimal
        r = risk_free / 100.0  # convert % to decimal

        if stock_price > 0 and strike > 0 and sigma > 0:
            delta_val = bs_delta(stock_price, strike, T, r, sigma, opt_type)
            theta_val = bs_theta(stock_price, strike, T, r, sigma, opt_type)
            gamma_val = bs_gamma(stock_price, strike, T, r, sigma)
            vega_val = bs_vega(stock_price, strike, T, r, sigma)
        else:
            delta_val = None
            theta_val = None
            gamma_val = 0
            vega_val = 0

        # Probability metrics
        row_with_mid = row.copy()
        row_with_mid["mid"] = pm["mid"]
        if delta_val is not None:
            row_with_mid["delta"] = delta_val
        prob = compute_probability_metrics(row_with_mid, opt_type)

        # Theta efficiency
        theta_eff = compute_theta_efficiency(theta_val, pm["mid"]) if theta_val else 0

        # Liquidity
        liq = compute_liquidity_metrics(row)

        # Fundamental flags
        cap_tier = classify_market_cap(row.get("market_cap"))
        spans_earn = earnings_within_dte(row.get("earnings_date"), row.get("dte", 0))

        # 52-week percentile
        hi52 = row.get("fifty_two_week_high") or 0
        lo52 = row.get("fifty_two_week_low") or 0
        week52_pctile = ((stock_price - lo52) / (hi52 - lo52) * 100) if (hi52 > lo52) else 50

        # Upside cap (calls only)
        upside_cap = compute_upside_cap(row.get("strike", 0), stock_price) if opt_type == "call" else None

        enriched = {
            "ticker": ticker,
            "sector": sector,
            "price": stock_price,
            "strike": row.get("strike"),
            "expiry": row.get("expiry"),
            "dte": row.get("dte"),
            "option_type": opt_type,
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "mid": pm["mid"],
            "ann_net_yield": pm["ann_net_yield"],
            "raw_yield": pm["raw_yield"],
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
            "pop": prob["pop"],
            "breakeven": prob["breakeven"],
            "breakeven_dist": prob["breakeven_dist"],
            "max_loss": prob["max_loss"],
            "upside_cap": upside_cap,
            "spread": liq["spread"],
            "spread_pct": liq["spread_pct"],
            "volume": liq["volume"],
            "open_interest": liq["open_interest"],
            "theta_efficiency": theta_eff,
            "market_cap": row.get("market_cap"),
            "market_cap_tier": cap_tier,
            "short_pct_float": row.get("short_pct_float", 0),
            "dividend_yield": row.get("dividend_yield", 0),
            "earnings_date": row.get("earnings_date"),
            "spans_earnings": spans_earn,
            "ex_div_date": row.get("ex_div_date"),
            "week52_pctile": round(week52_pctile, 1),
            "avg_volume": row.get("avg_volume"),
            "source": "Yahoo Finance",
            "fetched_at": row.get("fetched_at"),
        }

        # Compute PQS
        enriched_series = pd.Series(enriched)
        enriched["pqs"] = compute_pqs(enriched_series, risk_free)
        enriched["pqs_label"] = pqs_label(enriched["pqs"])

        rows.append(enriched)

    result = pd.DataFrame(rows)

    # Filter out obviously bad data
    result = result[result["mid"] > 0].copy()
    result = result[result["spread_pct"] < 50].copy()

    # Filter out deep ITM options that aren't practical trades
    # For puts: strike should be at or below stock price (OTM puts)
    # For calls: strike should be at or above stock price (OTM calls)
    puts_mask = (result["option_type"] == "put") & (result["strike"] <= result["price"] * 1.05)
    calls_mask = (result["option_type"] == "call") & (result["strike"] >= result["price"] * 0.95)
    result = result[puts_mask | calls_mask].copy()

    return result
