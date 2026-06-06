# Growth24 Milestone A - Frozen-Policy Reproducibility Audit

- Run date: 2026-06-05
- Plan: `notes/growth24_research_plan_2026-06-05.md`
- Branch: `growth24/research-salvage`
- Milestone status: `PASS`
- Paper only: `True`
- Live policy changed: `False`
- Paper plan changed: `False`

## Objective

Reproduce the fixed Growth24 candidate contract and the three pre-registered
policy forms against the unchanged 36-cycle champion shadow log before spending
compute on later research milestones.

Champion input:

`data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`

## Exact Commands

```powershell
Set-Location D:\fund_monitor_research
$py = "D:\fund_monitor\.venv\Scripts\python.exe"
$run = "data\experiment\growth24_research_plan_20260605"
$champion = "data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"

& $py .\dl_growth24_candidate_contract_eval.py `
  --shadow-log $champion `
  --long-n 2 --short-n 2 --expected-universe-count 24 `
  --practical-max-universe-score-std 0.085 `
  --practical-max-forecast-gap 4 `
  --research-max-consecutive 3 `
  --max-score-gaps "none,0.36,0.32" `
  --grid-max-forecast-gaps "none,3,4,5" `
  --grid-max-universe-score-stds "none,0.08,0.085,0.09" `
  --grid-max-consecutive "0,3" `
  --splits "18,24" --min-train-cycles 12 --min-test-cycles 8 `
  --score-start-dates "2024-10-11,2025-04-15" `
  --min-holdout-cycles-for-reporting 4 `
  --min-cycles-for-sensitivity 20 `
  --sensitivity-max-universe-score-stds "0.08,0.085,0.09" `
  --sensitivity-max-forecast-gaps "3,4,5" `
  --sensitivity-max-consecutive "0,3" `
  --min-holdout-allowed-cycles 4 `
  --min-holdout-filter-uplift 0 `
  --gate-min-mean-ls 0 --gate-min-hit 0.50 `
  --gate-max-drawdown -0.25 --gate-min-coverage 0.25 `
  --output "$run\champion_contract_recheck.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_contract_recheck.md"

& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log $champion --long-n 2 --short-n 2 `
  --expected-universe-count 24 `
  --max-universe-score-std 0.085 --max-forecast-gap 4 `
  --max-consecutive 0 `
  --output "$run\champion_p0_replay.csv" `
  --summary-output "$run\champion_p0_replay.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_p0_replay.md"

& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log $champion --long-n 2 --short-n 2 `
  --expected-universe-count 24 `
  --max-universe-score-std 0.085 --max-forecast-gap 4 `
  --max-consecutive 3 `
  --output "$run\champion_p3_replay.csv" `
  --summary-output "$run\champion_p3_replay.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_p3_replay.md"

& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log $champion --long-n 2 --short-n 2 `
  --expected-universe-count 24 `
  --max-universe-score-std 0.080 --max-forecast-gap 3 `
  --max-consecutive 0 `
  --output "$run\champion_s0_replay.csv" `
  --summary-output "$run\champion_s0_replay.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_s0_replay.md"
```

## Candidate Contract Result

- Status: `pass`
- Failures: none
- Skipped checks: none
- Cycles: 36
- Gate-grid passing configs: 93
- Walk-forward passing splits: 2 / 2
- Threshold-sensitivity passing configs: 17 / 18
- Minimum holdout uplift: 3.34%
- Minimum holdout mean long-short: 13.28%

The result matches `notes/growth24_36c_8e_candidate_contract_eval.md` at the
recorded precision.

## Fixed-Policy Replays

| Policy | Allowed | Coverage | Mean LS | Hit | Max DD | Replacements | Abstained Mean LS |
|---|---:|---:|---:|---:|---:|---:|---:|
| P0 practical filter only | 17 / 36 | 47.22% | 13.56% | 88.24% | -4.02% | 0 | 3.52% |
| P3 practical filter + replacement | 17 / 36 | 47.22% | 14.32% | 88.24% | -4.02% | 1 | 3.52% |
| S0 strict filter only | 13 / 36 | 36.11% | 14.73% | 92.31% | 0.00% | 0 | 4.60% |

Baseline all-cycle mean long-short was 8.26%.

P3's only replacement remains the previously documented 2024-02-12
`PLTR,NFLX` to `NFLX,NVDA` replacement, with a +13.00 percentage-point
replacement delta. One example is insufficient to validate replacement
behavior.

## Regression Comparison

| Check | Prior | Recheck | Delta | Threshold | Result |
|---|---:|---:|---:|---:|---|
| P0 allowed cycles | 17 | 17 | 0 | exact count | PASS |
| P0 mean LS | 13.56% | 13.56% | 0.00 pp | <= 0.10 pp | PASS |
| P0 hit | 88.24% | 88.24% | 0.00 pp | <= 0.10 pp | PASS |
| P0 max DD | -4.02% | -4.02% | 0.00 pp | <= 0.10 pp | PASS |
| P3 allowed cycles | 17 | 17 | 0 | exact count | PASS |
| P3 mean LS | 14.32% | 14.32% | 0.00 pp | <= 0.10 pp | PASS |
| P3 hit | 88.24% | 88.24% | 0.00 pp | <= 0.10 pp | PASS |
| P3 max DD | -4.02% | -4.02% | 0.00 pp | <= 0.10 pp | PASS |
| P3 replacement cycles | 1 | 1 | 0 | exact count | PASS |

## Interpretation and Decision

Milestone A passes. The current research branch reproduces the fixed champion
contract and policy-replay evidence without observed drift. This clears the
dependency for the cheap historical-stress and concentration/seed audits.

P0 remains the primary policy candidate. P3 remains exploratory because its
apparent improvement depends on one historical replacement. S0 remains a
pre-registered challenger and is not selected or promoted using this old
sample.

This milestone supplies regression evidence only. It does not provide new
independent temporal or matured paper evidence and does not justify a live or
paper-policy change.
