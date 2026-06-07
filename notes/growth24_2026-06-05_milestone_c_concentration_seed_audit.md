# Growth24 Milestone C - Concentration and Seed Audit

- Run date: 2026-06-05
- Plan: `notes/growth24_research_plan_2026-06-05.md`
- Branch: `growth24/research-salvage`
- Milestone status: `FAIL`
- Paper only: `True`
- Live policy changed: `False`
- Paper plan changed: `False`

## Objective

Check whether P0's historical improvement depends too heavily on one ticker or
one cycle, and whether both stored champion seeds are present and independently
viable. This milestone is a pre-stated promotion blocker.

## Exact Commands

```powershell
Set-Location D:\fund_monitor_research
$py = "D:\fund_monitor\.venv\Scripts\python.exe"
$run = "data\experiment\growth24_research_plan_20260605"
$champion = "data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"

& $py .\scripts\growth24_policy_concentration_audit.py `
  --shadow-log $champion `
  --long-n 2 --short-n 2 --expected-universe-count 24 `
  --policy "p0:0.085:4:0" `
  --output "$run\champion_p0_concentration.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_p0_concentration.md"

& $py .\scripts\growth24_seed_stability_audit.py `
  --results-glob "data\experiment\historical_blind_rank_head\results\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_chunk*\*_results.json" `
  --expected-seeds "20260506,20260507" `
  --output "$run\champion_seed_stability.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_seed_stability.md"
```

## Concentration Result

- Status: `fail`
- P0 allowed cycles: 17 / 36
- P0 mean long-short: 13.56%
- Baseline all-cycle mean long-short: 8.26%
- Max long-slot share: 44.12% for PLTR
- Max realized spread contribution share: 59.36% for PLTR
- Minimum leave-one-cycle-out uplift: 4.12%, excluding 2024-10-11

| Ticker | Slots | Slot Share | Spread Contribution | Contribution Share |
|---|---:|---:|---:|---:|
| PLTR | 15 | 44.12% | 136.82% | 59.36% |
| TSLA | 6 | 17.65% | 38.46% | 16.69% |
| AMD | 2 | 5.88% | 28.88% | 12.53% |
| INTC | 4 | 11.76% | 11.57% | 5.02% |
| NVDA | 4 | 11.76% | 6.49% | 2.82% |
| NFLX | 1 | 2.94% | 4.93% | 2.14% |
| MU | 2 | 5.88% | 3.33% | 1.45% |

## Concentration Gate Review

| Pre-stated threshold | Result | Status |
|---|---:|---|
| No ticker exceeds 50% of P0 allowed long slots | PLTR 44.12% | PASS |
| No ticker contributes more than 50% of cumulative P0 spread | PLTR 59.36% | FAIL |
| Leave-one-cycle-out uplift remains non-negative | minimum 4.12% | PASS |

The slot-count gate passes, but the realized contribution gate fails. P0's
historical spread improvement remains too dependent on PLTR's realized spread
contribution.

## Seed Stability Result

- Status: `pass`
- Result JSON files: 36
- Result rows: 72
- Unexpected seeds: none

| Seed | Cycles Present | Aggregate Selection Spread | Minimum Cycle Spread | Positive Spread Rate | Aggregate Daily IC |
|---|---:|---:|---:|---:|---:|
| 20260506 | 36 / 36 | 6.41% | -0.47% | 94.44% | 17.21% |
| 20260507 | 36 / 36 | 6.35% | -0.88% | 94.44% | 16.36% |

Both stored seeds are present in all 36 cycles, have positive aggregate
selection spread, and have no missing model/scaler paths in the stored result
metadata.

## Interpretation and Decision

Milestone C fails because the P0 contribution concentration threshold does not
clear. This is a pre-stated blocker for live-policy review and for conditional
stress-weight-3 model-challenger compute.

The positive seed audit and positive leave-one-cycle-out uplift are useful, but
they do not offset the contribution-concentration failure. Under the approved
plan, the correct decision is no live-policy change, no paper-plan change, and
no escalation to Milestone F model-challenger training from this evidence set.

Future work can continue only in passive evidence lanes that do not retune the
historical threshold: paper-maturity checkpoints on real due dates and untouched
future holdout cycles after their labels mature.
