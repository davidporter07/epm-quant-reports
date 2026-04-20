# Handoff: DL Model — Quant Strategy Research & Backtesting Framework
Created: 2026-04-17
Updated: 2026-04-20

## Status: FRAMEWORK COMPLETE — First tournament run done, 3 bugs to fix, AV cache refill pending

---

## Mission
Build a backtesting framework ("Quant Model Cup") that stress-tests individual mathematical
trading concepts as standalone models against S&P500 from 2006-2025. Identify which strategies
produce genuine alpha. Winning signal concepts graduate as candidate features for the EPM DL model.

---

## What Was Built (Session 2026-04-20)

### Session goal: First end-to-end tournament run
All 8 models ran for the first time on the full 2006-2025 universe. Several data quality bugs
were found and fixed before getting clean numbers.

### Bug Fix 1 ✅ — Return overflow (`backtest_engine.py`)
Delisted tickers with stale yfinance data (e.g., CBE returning 3.4M% in a single day) caused
`cumprod()` to overflow to infinity. Fix: clip daily returns symmetrically to ±50% before
computing portfolio returns:
```python
daily_returns = daily_returns.clip(-0.5, 0.5)
```
Also added a minimum 252-day valid data filter so tickers with <1 year of data are dropped.
SPY is always preserved despite the filter.

### Bug Fix 2 ✅ — AV earnings cache (`earnings_av.py`)
460 of 503 AV ticker files were empty `[]` — they got cached when the API returned a rate-limit
response instead of real data. The old `_is_cached()` accepted any file that existed.

Fix: `_is_cached()` now requires `st_size > 4` (rejects empty `[]`):
```python
return p.stat().st_size > 4
```

Also added `_DailyLimitExhausted` exception class — when AV returns a "Note" or "Information"
rate-limit message, `_fetch_ticker` raises this immediately so `download_earnings` can bail
rather than sleeping forever:
```python
class _DailyLimitExhausted(Exception): pass
```
The download loop catches this and stops with a clear message: "AV daily limit exhausted at
ticker N/M — Re-run tomorrow."

### Bug Fix 3 ✅ — Tournament blocks on AV downloads (`tournament.py`)
`run_tournament` was calling `load_earnings_av` with a live API key, which triggered a download
loop mid-run. When the daily limit was already exhausted this would hang.

Fix: `tournament.py` now passes `api_key=None` to `load_earnings_av`, loading from cache only.
The download step is now a separate explicit operation (see next-session instructions below).

---

## First Tournament Results (round1.json)

Run date: 2026-04-20, universe: ~503 tickers (survivorship-bias-free via SP500Composition), 2006-2025

| Rank | Model | CAGR | Sharpe | Notes |
|------|-------|------|--------|-------|
| 1 | PEAD | 32.76% | 1.02 | Only 43 AV-cached tickers — inflated |
| 2 | VOL_COMPRESSION | NaN | -0.31 | Bug in signal (no long signals generated) |
| 3 | OVERNIGHT | 91.36% | 2.65 | Suspicious — needs investigation (see below) |
| 4 | PAIRS_Z | 5.99% | 0.76 | Reasonable |
| 5 | GAP_CONTINUATION | NaN | -1.07 | Bug in signal (similar to VOL_COMPRESSION) |
| 6 | MEAN_REVERT | 23.54% | 0.65 | Plausible but low vol-adjusted return |
| 7 | PAIRS_DIVERGE | 7.38% | 0.85 | Reasonable |
| 8 | MOMENTUM | -32.46% | -0.74 | Likely implementation issue |

SPY CAGR baseline: ~10.9%

**Important caveats on these numbers:**
- No transaction costs, slippage, or market impact — all returns are overstated
- Short selling is unconstrained — borrow costs not modeled
- Survivorship bias minimized (SP500Composition) but yfinance delisted data is noisy
- These are gross pre-cost returns; real-world numbers will be materially lower

---

## Open Bugs (Next Session — Priority Order)

### Bug A — HIGH: OVERNIGHT 91% CAGR is suspicious
The overnight model buys every stock at close and sells at open every day. 91% CAGR implies
gross returns that no real trading implementation achieves. Likely causes:
1. **Look-ahead bias in open prices** — yfinance may not store open prices correctly for historical
   intraday data. The `open[t] / close[t-1]` formula may use adjusted opens that embed forward
   information.
2. **Transaction costs / bid-ask spread** — buying/selling 500 stocks every single day at NBBO
   would eat most of this edge.
3. **Possible signal construction error** — the overnight signal always holds all stocks (+1), so
   any systematic upward drift in open prices vs prior close gets compounded 252x per year.

**Verify by:**
- Running OVERNIGHT on SPY only (single stock, known data) and checking if CAGR matches
  the documented ~0.05% daily overnight edge (≈ 12% annual) from the academic literature
- If SPY-only gives ~12%, the 91% is mostly survivorship/selection bias from holding all stocks

### Bug B — HIGH: VOL_COMPRESSION and GAP_CONTINUATION return NaN CAGR
Both models generate no long/short signals (all zeros), causing the equity curve to be flat
and CAGR computation to fail. Likely the threshold conditions are never satisfied:

- **VOL_COMPRESSION**: Check that the ATR percentile calculation produces values < 20th percentile.
  The rolling rank normalization may be wrong — `rank(pct=True)` on a window that starts empty
  returns NaN, which may propagate.
- **GAP_CONTINUATION**: Check that the volume ratio filter (`volume / volume.rolling(20).mean() > 1.3`)
  is passing. If volume data is missing or zero-filled the ratio will be NaN everywhere.

**Quick diagnostic:**
```python
# In tournament.py or a scratch script:
signals = gap_continuation_signal(prices)
print(signals.abs().sum().sum())  # Should be >> 0
```

### Bug C — MEDIUM: MOMENTUM -32.46% CAGR
12-1 month momentum should be broadly positive (academic consensus). Negative CAGR over 2006-2025
suggests either:
1. Long/short implementation is inverted (shorting winners, longing losers)
2. Formation period lookback is wrong — check `prices.shift(skip) / prices.shift(formation)` is
   computing the right direction
3. The monthly rebalance may not be working correctly — signal could be computed on daily data
   but rebalanced monthly in a way that introduces a one-day lag error

---

## AV Earnings Refill (Do This First Next Session)

460 of 503 tickers have empty cache files. The AV daily limit resets at midnight UTC.
Run the download script first thing next session:

```python
from dotenv import load_dotenv; load_dotenv()
from quant_cup.earnings_av import download_earnings
from quant_cup.data_loader import get_sp500_tickers
import os
download_earnings(get_sp500_tickers(), os.environ['AV_API_KEY'])
```

At 500/day free tier: 460 tickers ≈ 1 day. Then re-run tournament for accurate PEAD numbers.

After refilling, re-run full tournament:
```bash
python quant_cup/tournament.py --start 2006-01-01 --end 2025-12-31 --output round1.json
```

---

## Feature Extraction Status (`feature_candidates.csv`)

`quant_cup/results/feature_candidates.csv` was generated after the first run. Its contents reflect
the buggy first run and should be regenerated after fixing the three bugs above.

Feature candidates that remain valid regardless of bug fixes:
- `overnight_return_20d` — from OVERNIGHT strategy (even if CAGR is inflated, the signal itself is valid)
- `earnings_surprise_last` / `earnings_beat_rate_4q` — from PEAD (academically strong)
- `momentum_12_1` / `momentum_6_1` — from MOMENTUM (fix the bug first, then re-evaluate)

Feature candidates to wait on:
- VOL_COMPRESSION features (`atr_percentile`, `vol_regime`) — wait for Bug B fix
- GAP_CONTINUATION features — wait for Bug B fix

---

## Complete File Structure

```
quant_cup/
  __init__.py
  backtest_engine.py          ✅ COMPLETE — returns clipped ±50%, min 252-day filter
  data_loader.py              ✅ COMPLETE — OHLCV + earnings from yfinance
  earnings_av.py              ✅ FIXED — rejects empty cache files, bails on daily limit
  earnings_fmp.py             ✅ COMPLETE — FMP earnings loader (fallback to AV)
  sp500_composition.py        ✅ COMPLETE — point-in-time SP500 for survivorship-bias-free universe
  tournament.py               ✅ FIXED — cache-only earnings, no inline downloads
  feature_candidates.py       ✅ GENERATED (stale — regenerate after bug fixes)
  models/
    momentum.py               ⚠️  BUG — returns negative CAGR
    pead.py                   ✅ WORKING — needs full AV cache for accurate results
    vol_compression.py        ⚠️  BUG — generates no signals
    overnight.py              ⚠️  SUSPICIOUS — 91% CAGR needs investigation
    pairs_z.py                ✅ WORKING
    gap_continuation.py       ⚠️  BUG — generates no signals
    mean_revert.py            ✅ WORKING
    pairs_diverge.py          ✅ WORKING
  results/
    round1.json               STALE — first buggy run
    round1_dev2.json          STALE — dev run
    feature_candidates.csv    STALE — regenerate after fixes
```

---

## Key Files

- `D:\fund_monitor\quant_cup\backtest_engine.py` — core engine
- `D:\fund_monitor\quant_cup\tournament.py` — runner + ranker
- `D:\fund_monitor\quant_cup\earnings_av.py` — AV earnings cache
- `D:\fund_monitor\quant_cup\models\` — all 8 signal functions
- `D:\fund_monitor\HANDOFF_dl_model_strategies.md` — this file

## Context: The EPM DL Model

**What exists today:**
- `models/ml_panel.pkl` — the trained DL model (sklearn-compatible, panel data)
- `feature_registry.py` — gated feature lifecycle: register → test → promote → retire
- `dl_feature_gate.py` — DL model reads only APPROVED features
- `feature_tester.py` — A/B test new features vs baseline
- `feature_promoter.py` — promotes features that pass gate criteria
- `models/ml_panel_meta.json` — model metadata (feature list, version, etc.)
- Current feature set (~10 approved features, finalised 2026-04-02)
- Daily pipeline: YCharts scrape → feature engineering → model train → forecast

**Integration path for quant_cup winners:**
Use existing `feature_tester.py` workflow — register → A/B test → promote.
Do NOT add to production model without running through the gate.

---

## Academic References

| Strategy | Primary Source |
|----------|---------------|
| Momentum | Jegadeesh & Titman (1993, 2001), JF |
| Momentum crashes | Daniel & Moskowitz (2016), JFE 122(2) |
| PEAD | Bernard & Thomas (1989, 1990), JAR/JAE |
| Volatility | Bollerslev (1986) ARCH; Yang-Zhang (2000) |
| Overnight | Lou, Polk & Skouras (2019) JFE |
| Pairs | Gatev, Goetzmann & Rouwenhorst (2006), RFS 19(3) |
| RSI Reversion | De Bondt & Thaler (1985); Poterba & Summers (1988) |
| Factor zoo / decay | Harvey, Liu & Zhu (2016), RFS 29(1) |
