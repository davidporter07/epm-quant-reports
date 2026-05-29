# Growth24 Dispersion Gate Backtest

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Gate: `UniverseScoreStd <= 0.085000`
- Available cycles: 36

## Summary

| Book | Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 36 | 100.00% | 8.26% | 5.45% | 75.00% | -19.86% | 9.000 |
| Dispersion-gated | 22 | 61.11% | 13.10% | 8.82% | 90.91% | -4.02% | 14.149 |
| Abstained only | 14 | 38.89% | 0.65% | 0.27% | 50.00% | -31.73% | 0.936 |

## Abstention Quality

- Abstained cycles: 14
- Negative cycles avoided: 7
- Positive cycles skipped: 7

## Worst Baseline Cycles

| AsOf | Longs | Shorts | LS | Score Std | Gate Allowed |
|---|---|---|---:|---:|---:|
| 2025-02-13 | PLTR,TSLA | CRM,LRCX | -19.23% | 0.141189 | False |
| 2025-11-13 | AMD,PLTR | CRM,SNPS | -15.57% | 0.090911 | False |
| 2023-09-12 | PLTR,NFLX | GOOG,META | -6.84% | 0.128881 | False |
| 2023-11-09 | PLTR,NVDA | MSFT,META | -4.02% | 0.042121 | True |
| 2025-04-15 | PLTR,ADBE | MU,ORCL | -3.83% | 0.085026 | False |
| 2024-04-12 | PLTR,NVDA | ADBE,SNPS | -3.53% | 0.107017 | False |
| 2024-12-11 | PLTR,INTC | CRM,TXN | -2.95% | 0.086183 | False |
| 2024-06-12 | PLTR,NVDA | SNPS,ADBE | -2.03% | 0.056566 | True |
| 2023-07-13 | PLTR,NFLX | META,CRM | -0.58% | 0.114590 | False |
| 2025-05-15 | PLTR,INTC | AVGO,TSLA | 1.12% | 0.085324 | False |

## Abstained Cycles

| AsOf | Longs | Shorts | LS | Score Std | Reason |
|---|---|---|---:|---:|---|
| 2023-06-12 | PLTR,NVDA | MSFT,AMAT | 9.14% | 0.090283 | universe_score_std 0.090283 > 0.085000 |
| 2023-07-13 | PLTR,NFLX | META,CRM | -0.58% | 0.114590 | universe_score_std 0.114590 > 0.085000 |
| 2023-08-11 | PLTR,NVDA | META,ADBE | 2.18% | 0.138718 | universe_score_std 0.138718 > 0.085000 |
| 2023-09-12 | PLTR,NFLX | GOOG,META | -6.84% | 0.128881 | universe_score_std 0.128881 > 0.085000 |
| 2023-10-11 | PLTR,NVDA | GOOG,META | 5.77% | 0.091908 | universe_score_std 0.091908 > 0.085000 |
| 2024-04-12 | PLTR,NVDA | ADBE,SNPS | -3.53% | 0.107017 | universe_score_std 0.107017 > 0.085000 |
| 2024-05-13 | PLTR,NVDA | AAPL,SNPS | 15.82% | 0.123859 | universe_score_std 0.123859 > 0.085000 |
| 2024-12-11 | PLTR,INTC | CRM,TXN | -2.95% | 0.086183 | universe_score_std 0.086183 > 0.085000 |
| 2025-02-13 | PLTR,TSLA | CRM,LRCX | -19.23% | 0.141189 | universe_score_std 0.141189 > 0.085000 |
| 2025-04-15 | PLTR,ADBE | MU,ORCL | -3.83% | 0.085026 | universe_score_std 0.085026 > 0.085000 |
| 2025-05-15 | PLTR,INTC | AVGO,TSLA | 1.12% | 0.085324 | universe_score_std 0.085324 > 0.085000 |
| 2025-06-16 | INTC,PLTR | MSFT,META | 6.07% | 0.091042 | universe_score_std 0.091042 > 0.085000 |
| 2025-11-13 | AMD,PLTR | CRM,SNPS | -15.57% | 0.090911 | universe_score_std 0.090911 > 0.085000 |
| 2026-01-15 | INTC,MU | AMZN,MSFT | 21.49% | 0.097320 | universe_score_std 0.097320 > 0.085000 |
