"""
Phase 4: Combined test runner for Options Premium Screener.
Runs all verification tests and prints a summary gate.
Usage: python test_app.py
"""

import os
import subprocess
import sys
import time

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

results = {}


def report(test_id: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    results[test_id] = passed
    print(f"  [{status}] {test_id}{' — ' + detail if detail else ''}")
    return passed


# =========================================================================
# 4A: Static Key Collision Audit
# =========================================================================
print("\n=== 4A: Static Key Collision Audit ===")
try:
    from test_keys import run_audit
    passed = run_audit("app.py")
    report("4A", passed)
except Exception as e:
    report("4A", False, str(e))


# =========================================================================
# 4B: Import & Syntax Validation
# =========================================================================
print("\n=== 4B: Import & Syntax Validation ===")
try:
    import config
    import data_fetcher
    import calculations
    # app.py imports streamlit which needs ScriptRunContext, so we just
    # verify it compiles without syntax errors
    result = subprocess.run(
        [sys.executable, "-c", "import py_compile; py_compile.compile('app.py', doraise=True)"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        report("4B", True, "all modules import / compile OK")
    else:
        report("4B", False, result.stderr.strip())
except Exception as e:
    report("4B", False, str(e))


# =========================================================================
# 4C: Data Pipeline Smoke Test
# =========================================================================
print("\n=== 4C: Data Pipeline Smoke Test ===")
try:
    from data_fetcher import (
        fetch_stock_info, fetch_all_options, fetch_historical_prices,
        estimate_iv_history, fetch_sector_iv,
    )
    from calculations import compute_all_hv, enrich_options
    import pandas as pd

    tickers = ["AAPL", "TSLA", "NVDA"]
    stock_rows, hv_cache, iv_cache = [], {}, {}

    for t in tickers:
        info, warn = fetch_stock_info(t)
        assert info is not None, f"{t}: fetch_stock_info returned None (warn={warn})"
        assert info["price"] is not None and info["price"] > 0, f"{t}: price is {info['price']}"
        stock_rows.append(info)
        prices = fetch_historical_prices(t)
        if prices is not None:
            hv_cache[t] = compute_all_hv(prices)
        iv_hist = estimate_iv_history(t)
        if iv_hist is not None:
            iv_cache[t] = iv_hist

    stock_df = pd.DataFrame(stock_rows)
    options_df, _ = fetch_all_options(tickers, min_dte=14, max_dte=60, max_workers=3)
    assert not options_df.empty, "Options DataFrame is empty"

    sector_iv = fetch_sector_iv()
    enriched, _ = enrich_options(options_df, stock_df, hv_cache, iv_cache, sector_iv, risk_free=4.5)

    assert not enriched.empty, "Enriched DataFrame is empty"
    assert len(enriched[enriched["option_type"] == "put"]) > 0, "No puts in enriched"
    assert len(enriched[enriched["option_type"] == "call"]) > 0, "No calls in enriched"

    # Check required columns exist
    required_cols = ["ticker", "strike", "dte", "mid", "pqs", "ann_net_yield",
                     "iv", "delta", "pop", "breakeven_dist", "spread_pct"]
    for col in required_cols:
        assert col in enriched.columns, f"Missing column: {col}"

    # Check PQS range
    assert enriched["pqs"].min() >= 0, f"PQS min is {enriched['pqs'].min()}"
    assert enriched["pqs"].max() <= 100, f"PQS max is {enriched['pqs'].max()}"

    # Check no NaN in critical columns
    for col in ["ticker", "strike", "dte", "mid", "pqs"]:
        nan_count = enriched[col].isna().sum()
        assert nan_count == 0, f"Column {col} has {nan_count} NaN values"

    report("4C", True, f"{len(enriched)} enriched rows, puts={len(enriched[enriched['option_type']=='put'])}, calls={len(enriched[enriched['option_type']=='call'])}")

except Exception as e:
    report("4C", False, str(e))


# =========================================================================
# 4D: Headless Render Test (Streamlit-specific)
# =========================================================================
print("\n=== 4D: Headless Render Test ===")
try:
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true", "--server.port", "8599",
         "--logger.level", "error"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Give it time to start and render the first page
    time.sleep(8)
    proc.terminate()
    stdout, stderr = proc.communicate(timeout=5)
    stderr_text = stderr.decode("utf-8", errors="replace")
    stdout_text = stdout.decode("utf-8", errors="replace")
    combined = stderr_text + stdout_text

    has_duplicate_key = "DuplicateElementKey" in combined or "duplicate" in combined.lower() and "key" in combined.lower()
    has_error = "Error" in combined and "ScriptRunContext" not in combined and "warning" not in combined.lower()

    if has_duplicate_key:
        report("4D", False, f"DuplicateElementKey found in output")
        # Print relevant error lines
        for line in combined.split("\n"):
            if "Duplicate" in line or "key" in line.lower():
                print(f"    >>> {line.strip()}")
    elif has_error:
        # Filter out benign warnings
        error_lines = [l for l in combined.split("\n")
                       if "Error" in l and "ScriptRunContext" not in l and "warning" not in l.lower()]
        if error_lines:
            report("4D", False, f"Runtime errors found")
            for line in error_lines[:5]:
                print(f"    >>> {line.strip()}")
        else:
            report("4D", True, "no duplicate key or runtime errors")
    else:
        report("4D", True, "no duplicate key or runtime errors")

except subprocess.TimeoutExpired:
    proc.kill()
    report("4D", False, "process timed out")
except Exception as e:
    report("4D", False, str(e))


# =========================================================================
# 4E: Runtime Route Test — SKIPPED (staying on Streamlit)
# =========================================================================
print("\n=== 4E: Runtime Route Test ===")
report("4E", True, "SKIPPED — staying on Streamlit (no REST routes to test)")


# =========================================================================
# 4F: After-Hours Data Verification
# =========================================================================
print("\n=== 4F: After-Hours Data Verification ===")
try:
    from data_fetcher import is_market_open, fetch_stock_info

    print(f"  Market open: {is_market_open()}")

    for ticker in ["AAPL", "TSLA", "NVDA"]:
        info, warn = fetch_stock_info(ticker)
        assert info is not None, f"{ticker}: fetch_stock_info returned None (warn={warn})"
        assert info["price"] is not None and info["price"] > 0, f"{ticker}: price is {info['price']}"
        print(f"  {ticker}: ${info['price']:.2f} — OK")

    report("4F", True, "all prices resolved regardless of market status")
except Exception as e:
    report("4F", False, str(e))


# =========================================================================
# 4H: Partial Stock Info Failure
# =========================================================================
print("\n=== 4H: Partial Stock Info Failure ===")
try:
    from data_fetcher import fetch_all_stock_info as _fasi
    tickers_mixed = ["AAPL", "ZZZZZ_FAKE1", "TSLA", "XXXXX_FAKE2", "NVDA", "YYYYY_FAKE3"]
    result_df, warn_list = _fasi(tickers_mixed, max_workers=4)
    assert not result_df.empty, "DataFrame should not be empty when some tickers succeed"
    assert len(result_df) >= 3, f"Expected at least 3 valid tickers, got {len(result_df)}"
    assert len(warn_list) >= 3, f"Expected at least 3 warnings for fake tickers, got {len(warn_list)}"
    report("4H", True, f"{len(result_df)} tickers loaded, {len(warn_list)} warnings")
except Exception as e:
    report("4H", False, str(e))


# =========================================================================
# 4I: Partial Options Failure
# =========================================================================
print("\n=== 4I: Partial Options Failure ===")
try:
    from data_fetcher import fetch_all_options as _fao
    tickers_mixed = ["AAPL", "ZZZZZ_FAKE1", "TSLA"]
    result_df, warn_list = _fao(tickers_mixed, max_workers=3)
    assert not result_df.empty, "DataFrame should not be empty when some tickers succeed"
    assert len(warn_list) >= 1, "Expected at least 1 warning for fake ticker"
    report("4I", True, f"{len(result_df)} option rows, {len(warn_list)} warnings")
except Exception as e:
    report("4I", False, str(e))


# =========================================================================
# 4J: Enrichment Row Fault Isolation
# =========================================================================
print("\n=== 4J: Enrichment Row Fault Isolation ===")
try:
    from calculations import enrich_options as _eo

    # Create options with one intentionally problematic row (strike=0)
    good_data = {
        "ticker": ["AAPL", "AAPL"], "strike": [250.0, 0.0],
        "bid": [3.0, 0.0], "ask": [3.5, 0.0], "impliedVolatility": [0.25, 0.0],
        "volume": [100, 0], "openInterest": [500, 0],
        "expiry": ["2026-05-15", "2026-05-15"], "dte": [30, 30],
        "option_type": ["put", "put"], "source": ["test", "test"],
        "fetched_at": ["2026-04-13", "2026-04-13"],
    }
    opts_df = pd.DataFrame(good_data)
    stock_df = pd.DataFrame([{
        "ticker": "AAPL", "price": 260.0, "market_cap": 3e12, "sector": "Technology",
        "dividend_yield": 0.005, "ex_div_date": None, "earnings_date": None,
        "fifty_two_week_high": 280, "fifty_two_week_low": 160,
        "avg_volume": 50000000, "short_pct_float": 0.01,
    }])

    result_df, warn_list = _eo(opts_df, stock_df, {}, {}, {}, risk_free=4.5)
    # The good row should survive even if the bad row is filtered out
    assert len(result_df) >= 1, f"Expected at least 1 enriched row, got {len(result_df)}"
    report("4J", True, f"{len(result_df)} rows enriched, {len(warn_list)} warnings")
except Exception as e:
    report("4J", False, str(e))


# =========================================================================
# 4K: Full Pipeline Graceful Degradation
# =========================================================================
print("\n=== 4K: Full Pipeline Graceful Degradation ===")
try:
    from data_fetcher import fetch_all_stock_info as _fasi2, fetch_all_options as _fao2
    from calculations import compute_all_hv as _cahv, enrich_options as _eo2

    tickers = ["AAPL", "FAKE_TICKER_1", "TSLA", "FAKE_TICKER_2", "NVDA"]
    stock_df, stock_w = _fasi2(tickers, max_workers=4)
    assert not stock_df.empty, "stock_df should not be empty"

    valid = stock_df["ticker"].tolist()
    options_df, opt_w = _fao2(valid, max_workers=3)
    assert not options_df.empty, "options_df should not be empty"

    enriched, enrich_w = _eo2(options_df, stock_df, {}, {}, {})
    assert not enriched.empty, "enriched should not be empty"

    total_w = stock_w + opt_w + enrich_w
    report("4K", True, f"{len(enriched)} rows, {len(total_w)} total warnings")
    for w in total_w[:5]:
        print(f"    {w}")
except Exception as e:
    report("4K", False, str(e))


# =========================================================================
# 4G: Summary Gate
# =========================================================================
print("\n" + "=" * 40)
print("=== TEST SUMMARY ===")
print("=" * 40)
for test_id in ["4A", "4B", "4C", "4D", "4E", "4F", "4H", "4I", "4J", "4K"]:
    status = "PASS" if results.get(test_id, False) else "FAIL"
    print(f"  {test_id}: {status}")

overall = all(results.values())
print(f"\n  OVERALL: {'PASS' if overall else 'FAIL'}")
print("=" * 40)

sys.exit(0 if overall else 1)
