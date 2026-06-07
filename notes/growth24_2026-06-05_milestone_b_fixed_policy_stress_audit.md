# Growth24 Milestone B - Fixed-Policy Stress Audit

- Run date: 2026-06-05
- Plan: `notes/growth24_research_plan_2026-06-05.md`
- Branch: `growth24/research-salvage`
- Milestone status: `PASS`
- Paper only: `True`
- Live policy changed: `False`
- Paper plan changed: `False`

## Objective

Apply the frozen P0 and S0 post-prediction filters to the four already-trained
stress shadow logs. This is a replay-only stress audit, not stress retraining
and not threshold tuning.

Baseline stress note:

`notes\final4_growth24_earnings_stress_weight_8e2seed_regime_gate.md`

That note recorded the ungated top2/bottom2 stress baseline as passing, with
9.90% mean spread and -4.54% worst per-window drawdown. The aggregation below
uses the replay ledgers to compare the filtered allowed decisions against the
same underlying top2/bottom2 decisions.

## Exact Commands

```powershell
Set-Location D:\fund_monitor_research
$py = "D:\fund_monitor\.venv\Scripts\python.exe"
$run = "data\experiment\growth24_research_plan_20260605"

$stressLogs = @{
  "current_2026" = "data\experiment\final4_growth24_earnings_stress_weight_8e2seed_probe\current_2026\current_2026_3c_8e_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
  "gfc_2008" = "data\experiment\final4_growth24_earnings_stress_weight_8e2seed_probe\gfc_2008\gfc_2008_3c_8e_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
  "q4_2018_drawdown" = "data\experiment\final4_growth24_earnings_stress_weight_8e2seed_probe\q4_2018_drawdown\q4_2018_drawdown_3c_8e_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
  "rate_bear_2022" = "data\experiment\final4_growth24_earnings_stress_weight_8e2seed_probe\rate_bear_2022\rate_bear_2022_3c_8e_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
}

foreach ($name in $stressLogs.Keys) {
  & $py .\dl_growth24_shadow_policy_replay.py `
    --shadow-log $stressLogs[$name] --long-n 2 --short-n 2 `
    --expected-universe-count 24 `
    --max-universe-score-std 0.085 --max-forecast-gap 4 `
    --max-consecutive 0 `
    --output "$run\stress_${name}_p0.csv" `
    --summary-output "$run\stress_${name}_p0.json" `
    --markdown-output "notes\growth24_2026-06-05_stress_${name}_p0.md"

  & $py .\dl_growth24_shadow_policy_replay.py `
    --shadow-log $stressLogs[$name] --long-n 2 --short-n 2 `
    --expected-universe-count 24 `
    --max-universe-score-std 0.080 --max-forecast-gap 3 `
    --max-consecutive 0 `
    --output "$run\stress_${name}_s0.csv" `
    --summary-output "$run\stress_${name}_s0.json" `
    --markdown-output "notes\growth24_2026-06-05_stress_${name}_s0.md"
}

& $py .\scripts\growth24_fixed_policy_stress_summary.py `
  --input-dir $run `
  --policy-prefix "stress_" `
  --baseline-note "notes\final4_growth24_earnings_stress_weight_8e2seed_regime_gate.md" `
  --output "$run\fixed_policy_stress_summary.json" `
  --markdown-output "notes\growth24_2026-06-05_fixed_policy_stress_summary.md"
```

## Aggregate Metrics

| Policy | Status | Allowed | Coverage | Allowed Mean LS | Allowed Hit | Allowed DD | Baseline DD |
|---|---|---:|---:|---:|---:|---:|---:|
| P0 practical filter only | pass | 5 / 12 | 41.67% | 4.85% | 80.00% | -6.53% | -6.53% |
| S0 strict filter only | pass | 4 / 12 | 33.33% | 2.51% | 75.00% | -6.53% | -6.53% |

Aggregate ungated baseline from the replay ledgers:

- Cycles: 12
- Mean long-short: 9.90%
- Hit rate: 75.00%
- Aggregate replay drawdown: -6.53%

The aggregate replay drawdown differs from the baseline note's per-window worst
drawdown because the helper evaluates one chronological aggregate sequence from
the replay ledgers. P0 does not worsen that aggregate drawdown.

## P0 Regime Detail

| Regime | Allowed | Abstained | Allowed Mean LS | Allowed Hit | Baseline Mean LS |
|---|---:|---:|---:|---:|---:|
| current_2026 | 2 | 1 | -0.27% | 50.00% | 23.75% |
| gfc_2008 | 0 | 3 | n/a | n/a | 5.50% |
| q4_2018_drawdown | 0 | 3 | n/a | n/a | 2.10% |
| rate_bear_2022 | 3 | 0 | 8.27% | 100.00% | 8.27% |

## Gate Review

| Pre-stated threshold | P0 result | Status |
|---|---:|---|
| At least 4 allowed stress decisions | 5 | PASS |
| Aggregate allowed mean LS > 0% | 4.85% | PASS |
| Aggregate allowed hit >= 50% | 80.00% | PASS |
| Aggregate allowed max DD no worse than -25% | -6.53% | PASS |
| No allowed stress window mean below -5% | worst current_2026 -0.27% | PASS |
| No drawdown worsening > 5 pp versus ungated baseline | 0.00 pp | PASS |

## Interpretation and Decision

Milestone B passes for P0. The fixed practical filter clears the pre-stated
stress thresholds using already-trained stress logs and without retuning.

This is a useful result but not a promotion result. P0 abstains from every GFC
and Q4-2018 stress decision, keeps two current-2026 decisions with a small
negative mean, and earns most of its allowed stress return from rate-bear-2022.
Those facts make Milestone C's concentration/outlier audit necessary before
spending model-challenger compute.

S0 also passes this stress replay but remains descriptive only. It cannot be
selected from this old stress sample and still needs untouched future evidence
before any review.
