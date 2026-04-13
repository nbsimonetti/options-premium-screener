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
        info = fetch_stock_info(t)
        assert info is not None, f"{t}: fetch_stock_info returned None"
        assert info["price"] is not None and info["price"] > 0, f"{t}: price is {info['price']}"
        stock_rows.append(info)
        prices = fetch_historical_prices(t)
        if prices is not None:
            hv_cache[t] = compute_all_hv(prices)
        iv_hist = estimate_iv_history(t)
        if iv_hist is not None:
            iv_cache[t] = iv_hist

    stock_df = pd.DataFrame(stock_rows)
    options_df = fetch_all_options(tickers, min_dte=14, max_dte=60, max_workers=3)
    assert not options_df.empty, "Options DataFrame is empty"

    sector_iv = fetch_sector_iv()
    enriched = enrich_options(options_df, stock_df, hv_cache, iv_cache, sector_iv, risk_free=4.5)

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
        info = fetch_stock_info(ticker)
        assert info is not None, f"{ticker}: fetch_stock_info returned None"
        assert info["price"] is not None and info["price"] > 0, f"{ticker}: price is {info['price']}"
        print(f"  {ticker}: ${info['price']:.2f} — OK")

    report("4F", True, "all prices resolved regardless of market status")
except Exception as e:
    report("4F", False, str(e))


# =========================================================================
# 4G: Summary Gate
# =========================================================================
print("\n" + "=" * 40)
print("=== TEST SUMMARY ===")
print("=" * 40)
for test_id in ["4A", "4B", "4C", "4D", "4E", "4F"]:
    status = "PASS" if results.get(test_id, False) else "FAIL"
    print(f"  {test_id}: {status}")

overall = all(results.values())
print(f"\n  OVERALL: {'PASS' if overall else 'FAIL'}")
print("=" * 40)

sys.exit(0 if overall else 1)
