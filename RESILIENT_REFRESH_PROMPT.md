# Options Premium Screener — Resilient Refresh Error Handling

## Problem

The "Refresh All Data" pipeline in `app.py` has **3 hard-abort points** that kill the entire refresh and return nothing to the user when any step fails:

```python
# Abort 1: If stock info fetch returns empty
if stock_info.empty:
    st.error("Failed to fetch any stock data. Check your internet connection.")
    st.session_state.refresh_running = False
    return  # <-- USER SEES NOTHING

# Abort 2: If options chain fetch returns empty
if options_df.empty:
    st.error("No options data retrieved. Try again in a few minutes.")
    st.session_state.refresh_running = False
    return  # <-- USER SEES NOTHING

# Abort 3: If enrichment produces empty results
if enriched.empty:
    st.error("No valid options found after enrichment.")
    st.session_state.refresh_running = False
    return  # <-- USER SEES NOTHING
```

Additionally, the **data_fetcher.py** functions silently swallow individual ticker failures:
- `fetch_stock_info()` returns `None` on any exception — no logging, no tracking
- `fetch_all_stock_info()` silently drops tickers where `res.get("price")` is falsy
- `fetch_options_chain()` returns `None` on any exception — no logging
- `fetch_all_options()` silently drops tickers with no chain data

And **calculations.py** `enrich_options()` has no try/except around individual row processing — a single bad row (e.g., division by zero, unexpected NaN) will crash the entire enrichment loop and throw away ALL previously computed rows.

### Real-World Failure Scenarios

1. **Yahoo Finance rate-limits or throttles** — With 150 tickers fetching in parallel, Yahoo returns HTTP 429 or empty responses for some tickers. Currently: the fetch completes but silently drops 30-50% of the universe with no indication to the user.

2. **A single ticker has malformed data** — e.g., a recently IPO'd stock has no `fiftyTwoWeekHigh`, causing a division-by-zero in the 52-week percentile calc. Currently: the entire `enrich_options()` loop crashes and returns an empty DataFrame, triggering Abort 3.

3. **Network timeout during options chain fetch** — One slow ticker blocks the ThreadPoolExecutor future, and if the thread raises, it's silently swallowed. If *enough* tickers fail, `options_df` is empty, triggering Abort 2.

4. **VIX or Treasury rate fetch fails** — `fetch_vix()` and `fetch_risk_free_rates()` have try/except but return fallback dicts with `None` values. The pipeline continues but `rf_rate` defaults to 4.5, which may be significantly wrong.

---

## Desired Behavior

**Principle: Always show the user the best data you have, even if it's incomplete. Never show nothing.**

### 1. Per-Ticker Fault Isolation in data_fetcher.py

Each function that fetches data for a single ticker (`fetch_stock_info`, `fetch_options_chain`, `fetch_historical_prices`, `estimate_iv_history`) should:

- **Catch exceptions per-ticker** (already done via try/except returning None)
- **Log the failure** by appending to a `warnings` list that gets returned alongside the data
- **Track success/failure counts** so the UI can show "Loaded 127/150 tickers (23 failed: MARA, RIOT, LCID, ...)"

Modify the batch functions (`fetch_all_stock_info`, `fetch_all_options`) to return a tuple: `(DataFrame, list[str])` where the second element is a list of warning messages like `"MARA: fetch_stock_info failed (HTTPError 429)"`, `"RIOT: no options chains available"`.

### 2. Per-Row Fault Isolation in calculations.py

The `enrich_options()` function iterates over every merged row. Wrap the per-row logic in a try/except so that a single bad row doesn't crash the loop:

```python
for _, row in merged.iterrows():
    try:
        # ... all existing per-row computation ...
        rows.append(enriched)
    except Exception as e:
        warnings.append(f"{row.get('ticker','?')} {row.get('strike','?')} {row.get('option_type','?')}: {e}")
        continue  # skip this contract, keep processing others
```

Return the warnings alongside the DataFrame: `enrich_options(...)` should return `(pd.DataFrame, list[str])`.

### 3. Graceful Degradation in app.py `run_full_refresh()`

Replace the 3 hard-abort points with graceful degradation:

**Replace Abort 1** (empty stock info):
```python
# OLD: return with error, user sees nothing
# NEW: if SOME tickers loaded, continue with partial data and warn
if stock_info.empty:
    st.error("Could not fetch any stock data. Keeping previous data if available.")
    st.session_state.refresh_running = False
    return  # Only abort if truly zero data — this is unrecoverable
# If partial, warn but continue:
if len(stock_info) < len(tickers) * 0.5:
    st.warning(f"Only {len(stock_info)}/{len(tickers)} tickers loaded. Results may be incomplete.")
```

**Replace Abort 2** (empty options):
```python
# OLD: return with error
# NEW: if ANY options loaded, continue with what we have
if options_df.empty:
    st.warning("No options chains retrieved. Showing previous data if available.")
    # Fall back to cached data rather than showing nothing
    if st.session_state.enriched_puts is not None:
        st.session_state.refresh_running = False
        return  # keep showing stale data
    st.error("No data available at all. Please try again later.")
    st.session_state.refresh_running = False
    return
```

**Replace Abort 3** (empty enrichment):
```python
# Same pattern: warn and fall back to cached data if enrichment fails
```

### 4. Warning Aggregation & Display

After the refresh completes (whether fully or partially), display a collapsible warning summary:

```python
if warnings:
    with st.expander(f"⚠️ {len(warnings)} warnings during refresh — tap for details", expanded=False):
        for w in warnings[:50]:  # cap display at 50
            st.text(w)
        if len(warnings) > 50:
            st.text(f"... and {len(warnings) - 50} more")
```

### 5. Data Completeness Indicator

Add a visible indicator in the header showing data quality:

```python
total_universe = len(tickers)
loaded_stocks = len(stock_info)
loaded_options = options_df["ticker"].nunique() if not options_df.empty else 0

completeness = loaded_options / total_universe * 100
if completeness >= 90:
    st.success(f"Data loaded: {loaded_options}/{total_universe} tickers ({completeness:.0f}%)")
elif completeness >= 50:
    st.warning(f"Partial data: {loaded_options}/{total_universe} tickers ({completeness:.0f}%) — some tickers failed to load")
else:
    st.error(f"Limited data: {loaded_options}/{total_universe} tickers ({completeness:.0f}%) — many fetches failed, results may be unreliable")
```

---

## Files to Modify

### data_fetcher.py

1. Add a module-level `_warnings: list[str]` collector (or pass it through function signatures)
2. Modify `fetch_stock_info()` to log the exception message when it catches
3. Modify `fetch_all_stock_info()` to:
   - Track and return per-ticker failures with the specific exception
   - Return `(pd.DataFrame, list[str])` instead of just `pd.DataFrame`
4. Modify `fetch_options_chain()` same pattern
5. Modify `fetch_all_options()` to return `(pd.DataFrame, list[str])`
6. Modify `fetch_vix()`, `fetch_risk_free_rates()`, `fetch_sector_iv()` to return warnings when falling back to defaults

### calculations.py

1. Wrap the per-row loop in `enrich_options()` with try/except per iteration
2. Return `(pd.DataFrame, list[str])` — the enriched data and any per-row warnings

### app.py

1. Update `run_full_refresh()` to:
   - Collect warnings from every step into a single `all_warnings: list[str]`
   - Replace the 3 hard-abort `return` statements with graceful degradation
   - After the pipeline finishes (whether complete or partial), display the warning summary
   - Show data completeness indicator
   - Still save to disk cache even if data is partial (partial > nothing)
2. Store warnings in session state so they persist across reruns:
   ```python
   st.session_state.refresh_warnings = all_warnings
   ```
3. Display warnings in the main UI (outside `run_full_refresh`) in a collapsible expander below the header metrics

---

## Current File Contents

### app.py — `run_full_refresh()` function (lines 267–386)

```python
def run_full_refresh():
    """Execute the full data fetch and enrichment pipeline.
    Works during market hours (live data) and after hours (last close data)."""
    st.session_state.refresh_running = True

    progress = st.progress(0, text="Starting data refresh...")
    status = st.empty()

    mkt_open = is_market_open()
    if not mkt_open:
        status.info("Market is closed — fetching data as of most recent close...")

    # --- Step 1: Build universe ---
    progress.progress(2, text="Building ticker universe...")
    tickers = build_universe()

    # --- Step 2: Fetch VIX & risk-free rates & sector IV ---
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

    stock_info = fetch_all_stock_info(tickers, max_workers=20, progress_callback=stock_progress)
    st.session_state.stock_info = stock_info

    if stock_info.empty:
        st.error("Failed to fetch any stock data. Check your internet connection.")
        st.session_state.refresh_running = False
        return

    valid_tickers = stock_info["ticker"].tolist()

    # --- Step 4: Fetch historical prices & compute HV ---
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

    options_df = fetch_all_options(valid_tickers, min_dte=7, max_dte=90,
                                    max_workers=10, progress_callback=opts_progress)

    if options_df.empty:
        st.error("No options data retrieved. Try again in a few minutes.")
        st.session_state.refresh_running = False
        return

    # --- Step 6: Enrich & Score ---
    progress.progress(92, text="Calculating metrics & scoring...")

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

    # Persist to disk so data survives Render cold starts
    _save_cache({
        "enriched_puts": st.session_state.enriched_puts,
        "enriched_calls": st.session_state.enriched_calls,
        "vol_scanner": st.session_state.vol_scanner,
        "vix_data": st.session_state.vix_data,
        "risk_free": st.session_state.risk_free,
        "sector_iv": st.session_state.sector_iv,
        "stock_info": st.session_state.stock_info,
        "last_refresh": st.session_state.last_refresh,
    })

    progress.progress(100, text="Done!")
    status.text("Refresh complete!")
```

### data_fetcher.py — Batch fetch functions

```python
def fetch_all_stock_info(tickers: list[str], max_workers: int = 20,
                          progress_callback=None) -> pd.DataFrame:
    """Fetch fundamentals for all tickers in parallel."""
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


def fetch_all_options(tickers: list[str], min_dte: int = 7, max_dte: int = 90,
                       max_workers: int = 10, progress_callback=None) -> pd.DataFrame:
    """Fetch options chains for all tickers in parallel."""
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
```

### calculations.py — `enrich_options()` loop (no per-row error handling)

```python
rows = []
for _, row in merged.iterrows():
    ticker = row["ticker"]
    opt_type = row["option_type"]
    # ... ~80 lines of computation per row with no try/except ...
    rows.append(enriched)

result = pd.DataFrame(rows)
```

---

## Testing Requirements

After implementing the changes, run the existing test suite AND the following additional tests:

### Test: Partial Stock Info Failure

```python
def test_partial_stock_failure():
    """Simulate 50% of stock fetches failing — pipeline should still produce results."""
    from data_fetcher import fetch_all_stock_info
    # Use a mix of valid tickers and obviously invalid ones
    tickers = ["AAPL", "ZZZZZ_FAKE", "TSLA", "XXXXX_FAKE", "NVDA", "YYYYY_FAKE"]
    result, warnings = fetch_all_stock_info(tickers)
    assert not result.empty, "DataFrame should not be empty when some tickers succeed"
    assert len(result) >= 3, f"Expected at least 3 valid tickers, got {len(result)}"
    assert len(warnings) >= 3, f"Expected at least 3 warnings for fake tickers, got {len(warnings)}"
    print(f"PASS: {len(result)} tickers loaded, {len(warnings)} warnings")
```

### Test: Partial Options Failure

```python
def test_partial_options_failure():
    """Simulate some options fetches failing — pipeline should still produce results."""
    from data_fetcher import fetch_all_options
    tickers = ["AAPL", "ZZZZZ_FAKE", "TSLA"]
    result, warnings = fetch_all_options(tickers)
    assert not result.empty, "DataFrame should not be empty when some tickers succeed"
    assert len(warnings) >= 1, "Expected at least 1 warning for fake ticker"
    print(f"PASS: {len(result)} option rows, {len(warnings)} warnings")
```

### Test: Enrichment Row Fault Isolation

```python
def test_enrichment_fault_isolation():
    """Verify a single bad row doesn't crash the entire enrichment loop."""
    import pandas as pd
    from calculations import enrich_options

    # Create a DataFrame with one intentionally bad row (strike=0, which causes division errors)
    good_data = {
        "ticker": ["AAPL", "AAPL"], "strike": [250.0, 0.0],  # second row has bad strike
        "bid": [3.0, 0.0], "ask": [3.5, 0.0], "impliedVolatility": [0.25, 0.0],
        "volume": [100, 0], "openInterest": [500, 0],
        "expiry": ["2026-05-15", "2026-05-15"], "dte": [30, 30],
        "option_type": ["put", "put"], "source": ["test", "test"],
        "fetched_at": ["2026-04-13", "2026-04-13"],
    }
    options_df = pd.DataFrame(good_data)
    stock_df = pd.DataFrame([{
        "ticker": "AAPL", "price": 260.0, "market_cap": 3e12, "sector": "Technology",
        "dividend_yield": 0.005, "ex_div_date": None, "earnings_date": None,
        "fifty_two_week_high": 280, "fifty_two_week_low": 160,
        "avg_volume": 50000000, "short_pct_float": 0.01,
    }])

    result, warnings = enrich_options(options_df, stock_df, {}, {}, {}, risk_free=4.5)
    # The good row should survive even if the bad row fails
    assert len(result) >= 1, f"Expected at least 1 enriched row, got {len(result)}"
    print(f"PASS: {len(result)} rows enriched, {len(warnings)} warnings")
```

### Test: Full Pipeline Graceful Degradation

```python
def test_full_pipeline_graceful():
    """Run refresh with a mix of valid and invalid tickers — should produce partial results, not crash."""
    # This tests the full pipeline through run_full_refresh() indirectly
    # by calling the data layer functions directly with mixed input
    from data_fetcher import fetch_all_stock_info, fetch_all_options
    from calculations import compute_all_hv, enrich_options

    tickers = ["AAPL", "FAKE1", "TSLA", "FAKE2", "NVDA"]
    stock_df, stock_warnings = fetch_all_stock_info(tickers)
    assert not stock_df.empty

    valid = stock_df["ticker"].tolist()
    options_df, opt_warnings = fetch_all_options(valid)
    assert not options_df.empty

    enriched, enrich_warnings = enrich_options(options_df, stock_df, {}, {}, {})
    assert not enriched.empty

    total_warnings = stock_warnings + opt_warnings + enrich_warnings
    print(f"PASS: pipeline completed with {len(enriched)} rows, {len(total_warnings)} total warnings")
    for w in total_warnings[:10]:
        print(f"  - {w}")
```

### Test Summary Gate

Add these 4 tests to `test_app.py` as tests 4H–4K. The existing tests 4A–4F must still pass. The overall gate must show:

```
=== TEST SUMMARY ===
  4A: PASS
  4B: PASS
  4C: PASS
  4D: PASS
  4E: PASS (or SKIPPED)
  4F: PASS
  4H: PASS (partial stock failure)
  4I: PASS (partial options failure)
  4J: PASS (enrichment fault isolation)
  4K: PASS (full pipeline graceful degradation)

  OVERALL: PASS
```

---

## Output — Required Deliverables

1. **Complete rewritten `data_fetcher.py`** — with warnings tracking on every batch function. Do not abbreviate.
2. **Complete rewritten `calculations.py`** — with per-row try/except in `enrich_options()`. Do not abbreviate.
3. **Complete rewritten `app.py` `run_full_refresh()` function** — with graceful degradation, warning aggregation, and data completeness indicator. Only output the changed function and any new helper functions, not the entire file.
4. **Updated `test_app.py`** — with tests 4H–4K added.
5. **Test output** — actual console output from `python test_app.py` showing OVERALL: PASS.
6. **Git commands** to commit and push.

Do NOT declare the task complete until OVERALL is PASS with all 10 tests green.
