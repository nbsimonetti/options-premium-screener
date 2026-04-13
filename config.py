"""
Configuration constants for the Options Premium Screener Dashboard.
Scoring weights, default filters, sector mappings, and ticker universe helpers.
"""

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# PQS (Premium Quality Score) Weights — must sum to 1.0
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Default filter ranges
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Sector ETF mapping (for sector-relative IV comparison)
# ---------------------------------------------------------------------------
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

# Reverse mapping: ETF -> sector name
ETF_SECTOR_MAP = {v: k for k, v in SECTOR_ETF_MAP.items()}

# All sector ETF tickers for fetching IV
SECTOR_ETFS = list(SECTOR_ETF_MAP.values())

# ---------------------------------------------------------------------------
# VIX regime thresholds
# ---------------------------------------------------------------------------
VIX_REGIMES = {
    "Low Vol": (0, 15),
    "Normal": (15, 20),
    "Elevated": (20, 30),
    "Crisis": (30, 100),
}

# ---------------------------------------------------------------------------
# Market cap tiers (USD)
# ---------------------------------------------------------------------------
MARKET_CAP_TIERS = {
    "Large": 10_000_000_000,   # > $10B
    "Mid": 2_000_000_000,      # $2B - $10B
    "Small": 0,                # < $2B
}

# ---------------------------------------------------------------------------
# Cache duration (seconds)
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = 900  # 15 minutes

# ---------------------------------------------------------------------------
# FRED series IDs for risk-free rates
# ---------------------------------------------------------------------------
FRED_SERIES = {
    "1mo": "DGS1MO",
    "3mo": "DGS3MO",
    "1yr": "DGS1",
}

# ---------------------------------------------------------------------------
# Ticker universe helpers
# ---------------------------------------------------------------------------

def get_sp500_tickers() -> list[str]:
    """Fetch current S&P 500 constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        return sorted(tickers)
    except Exception:
        # Fallback: a static subset of major tickers
        return _FALLBACK_TICKERS


# High-volume optionable names outside S&P 500
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

# Maximum number of tickers to screen (to keep fetch times reasonable)
MAX_UNIVERSE_SIZE = 150
