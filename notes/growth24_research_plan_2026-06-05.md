# Growth24 / DL Research Plan - 2026-06-05

Status: Phase 1 proposal. No experiments in this plan may start until the user approves Phase 2.

## 1. Objective and Decision Boundary

The primary research question is whether the fixed Growth24 post-prediction
abstention filter is robust enough to be flagged for a live-policy review. The
research branch will not implement a live-policy change. A result that clears
all pre-stated thresholds will be reported to the user for a separate decision.

The default decision is **no live-policy change**. Historical replays on the
same 36 cycles used to discover or validate a threshold cannot, by themselves,
justify promotion. Untouched temporal evidence and matured paper evidence are
required.

Secondary questions are:

1. Does the fixed filter survive historical stress windows without reducing
   coverage to a meaningless level?
2. Is its apparent benefit robust to ticker concentration, single-cycle
   outliers, and member/seed weakness?
3. Is a conservative filter-only form preferable to the weakly validated
   ticker-replacement overlay?
4. Does the provisional stress-weight-3 challenger deserve one full historical
   confirmation, or should it be rejected without spending 8-epoch compute?

## 2. Non-Negotiable Workspace and Git Rules

- Work only in `D:\fund_monitor_research` on
  `growth24/research-salvage`.
- Never enter, checkout, switch, commit, or edit in `D:\fund_monitor`. It is
  the live scheduled pipeline tree.
- Use only `D:\fund_monitor\.venv\Scripts\python.exe` as the interpreter.
- Treat `data\` and `models\experiment\` as approved shared junctions. Do not
  delete, recreate, or replace either junction.
- Write experiment outputs only below `data\experiment\` and
  `models\experiment\`.
- Keep commits research-only: `dl_growth24_*.py`, `dl_rank_head_*.py` only when
  required for research, `scripts\` research helpers, `tests\test_growth24_*`,
  and `notes\growth24_*`.
- Never modify pipeline modules, `providers\`, or `models\*.pkl`.
- Do not bypass the shared pre-commit hook.
- Do not apply the two repo-global recovery stashes unless a specific recovery
  need is identified and reviewed.
- Stay on one research branch. Do not create side branches or merge commits for
  these milestones.
- Rebase a clean worktree onto `origin/main` before each substantial milestone.
  Never start a rebase with uncommitted milestone work.
- Stage explicit files only. Do not use `git add -A`.
- Each milestone ends with tests, branch hygiene, GitNexus change detection, an
  atomic commit, a normal push, and a GitNexus refresh.

The existing runners `scripts\run_growth24_research_ladder.ps1`,
`scripts\run_growth24_stress_weight_36c.ps1`, and the related legacy PowerShell
runners are **prohibited as-is** because they hard-code
`Set-Location "D:\fund_monitor"` and the live-tree interpreter. Phase 2 must
use the direct research-worktree commands below or a new research-only helper
whose root and interpreter are explicit.

## 3. Planning Snapshot

At the Phase 1 planning snapshot on 2026-06-05:

- The research branch was clean and rebased on `origin/main`.
- Branch hygiene passed against `origin/main`.
- The GitNexus research index was current and had zero embeddings.
- The latest paper status was generated on 2026-06-03.
- No Phase 2 experiment was executed while preparing this plan.

## 4. Evidence Already Settled

The following evidence is treated as settled. These experiments must not be
repeated unless a code-regression audit first shows that the original result is
no longer reproducible.

| Topic | Existing evidence | Decision |
|---|---|---|
| Research champion | `notes/growth24_dl_champion_card.md` records the 36-cycle/8-epoch RSI/MA/volume/earnings rank-head champion. Historical blind mean long-short was 11.57%, spread hit 72.22%, and max drawdown -31.70%. It remains shadow-only. | Keep the model fixed while testing policy controls. |
| Two-member ensemble | `notes/growth24_36c_8e_two_member_baseline.md` shows the two-member ensemble underperformed the validated single member on mean spread, median spread, hit rate, and Sharpe. | Do not add members or repeat the 36c/8e two-member baseline. |
| Failure concentration | `notes/growth24_36c_8e_feature_probe_failure_analysis.md` shows 10/36 losing cycles, PLTR in 9 losses, and one AMD/SNPS loss of -31.70%. Losses occurred in quiet bear and quiet bull regimes. | Audit concentration and outlier dependence; do not assume a simple stress label explains losses. |
| Simple HMM skip | The champion card records that HMM stress skipping removed profitable decisions: only three days were skipped, non-stress mean excess was 9.08%, and stress-only mean excess was 14.61%. | Do not repeat simple HMM-stress skipping. |
| Old abstention grid | `notes/final4_growth24_earnings_abstention_gate.md` and `notes/final4_growth24_earnings_abstention_gate_refresh_narrow.md` found zero passing configs. | Do not repeat the validation-metric abstention grid. |
| Ticker cooldown | `notes/final4_growth24_earnings_conditional_cooldown_regime_gate.md` failed the regime gate and produced no top2/top3 decisions. | Do not promote or retune the old cooldown challenger. |
| Stress-weight-2 model | `notes/final4_growth24_earnings_stress_weight_8e2seed_regime_gate.md` passed top2/bottom2 across four stress windows, with mean spread 9.90% and worst drawdown -4.54%; top1 and top3 failed. | Treat top2/bottom2 as the fixed research basket. Do not repeat this training run. |
| Fixed dispersion gate | `notes/growth24_36c_8e_stress_dispersion_gate_backtest.md` shows `UniverseScoreStd <= 0.085` improved mean spread from 8.26% to 13.10%, hit from 75.00% to 90.91%, and drawdown from -19.86% to -4.02% at 61.11% coverage. | This is promising historical evidence, not independent promotion evidence. |
| Fixed practical policy | `notes/growth24_36c_8e_post_prediction_fixed_policy.md` and its walk-forward notes show the fixed `forecast_gap_max=4`, `universe_score_std_max=0.085`, `max_consecutive=3` policy passed both 18- and 24-cycle splits. | Freeze thresholds. Do not tune them again on the same 36 cycles. |
| Filter-only control | `notes/growth24_36c_8e_post_prediction_fixed_policy_no_consecutive_walk_forward.md` shows the same practical gate with `max_consecutive=0` passed both splits. | Treat filter-only behavior separately from replacement behavior. |
| Threshold sensitivity | `notes/growth24_36c_8e_policy_threshold_sensitivity.md` shows 17/18 nearby configs passed; the robust strict config was std 0.08, forecast gap 3, and no replacement. | Pre-register the strict config as a challenger; do not select it using the same old data. |
| Candidate contract | `notes/growth24_36c_8e_candidate_contract_eval.md` passed the existing contract, walk-forward, sensitivity, and both historical holdouts. | Use it as a regression baseline only. |
| Replacement overlay | `notes/growth24_36c_8e_paper_policy_replay.md` and holdout notes show only one historical replacement at `max_consecutive=3`; `max_consecutive=0` produced none. | Replacement is not validated and cannot ride on the abstention filter's evidence. |
| Foundation sidecar | `notes/growth24_36c_3e_foundation_sidecar_candidate_contract_eval.md` failed walk-forward and sensitivity, with negative minimum holdout uplift. | Reject the 36c/3e foundation-sidecar challenger. Do not repeat or escalate it. |
| Stress-weight-3 screen | `notes/growth24_12c_3e_stressw3_candidate_contract_eval.md` is provisional: 12 cycles, practical overlay mean spread 12.72%, but walk-forward and sensitivity were skipped. | Eligible for one conditional 36c/3e confirmation only. |
| Current paper evidence | As of 2026-06-03, `growth24_paper_outcome_summary.json` had 2 matured trades and 11 pending; the control-overlay summary had 0 overlay-matured plans and one matured abstained gain. | Paper evidence is insufficient. No promotion is possible now. |

## 5. Pre-Registered Policies

These definitions are frozen before new evidence is scored:

### P0 - Practical Filter Only

- Basket: top2/bottom2.
- Expected universe: 24.
- Allow only when `UniverseScoreStd <= 0.085`.
- Allow only when `ForecastGap <= 4.0`.
- `max_consecutive=0`, which disables replacement behavior.
- Role: primary policy candidate because its logic has historical support and
  does not depend on the under-validated replacement mechanism.

### P3 - Practical Filter Plus Replacement

- Same thresholds as P0.
- `max_consecutive=3`.
- Role: exploratory replacement overlay only.
- P3 cannot be recommended with P0's evidence. It must clear separate
  replacement thresholds.

### S0 - Strict Filter-Only Challenger

- Basket: top2/bottom2.
- Expected universe: 24.
- Allow only when `UniverseScoreStd <= 0.080`.
- Allow only when `ForecastGap <= 3.0`.
- `max_consecutive=0`.
- Role: conservative challenger. Selecting S0 over P0 on a new block consumes
  that block as selection data; S0 would then require another untouched block
  before a live-policy review.

No additional threshold grid will be searched. The nearby-grid sensitivity
result is already settled.

## 6. Promotion, Rejection, and No-Change Thresholds

### 6.1 Minimum Thresholds to Flag P0 for Live-Policy Review

Every item below must pass. Passing means "flag for user review", not "edit the
pipeline."

1. **Regression baseline**
   - Existing candidate contract remains `pass`.
   - P0 replay matches prior fixed-policy results within 0.10 percentage point
     for coverage, mean spread, hit rate, and max drawdown.
2. **Historical stress**
   - At least 4 of the 12 existing stress-window decisions are allowed.
   - Aggregate allowed mean long-short return is greater than 0%.
   - Aggregate allowed hit rate is at least 50%.
   - Aggregate allowed max drawdown is no worse than -25%.
   - No stress window with an allowed decision has mean spread below -5%.
   - P0 does not worsen aggregate drawdown by more than 5 percentage points
     versus the ungated top2/bottom2 stress baseline.
3. **Untouched temporal evidence after 2026-04-17**
   - Early checkpoint after 6 new matured cycles: no hard failure, at least 2
     allowed cycles, allowed mean spread above 0%, hit at least 50%, and max
     drawdown no worse than -15%. This checkpoint cannot promote.
   - Review checkpoint after at least 12 new matured cycles: at least 5 allowed
     cycles, coverage between 30% and 70%, allowed mean spread at least 10%,
     allowed mean spread at least 3 percentage points above all-cycle baseline,
     allowed hit at least 60%, max drawdown no worse than -10%, and no allowed
     cycle at or below -20%.
   - Allowed mean spread must be at least as high as abstained mean spread.
4. **Matured paper evidence**
   - At least 12 matured base plans and at least 6 matured P0-allowed plans.
   - P0 coverage between 30% and 70%.
   - P0-allowed mean benchmark-excess return above 0%.
   - P0-allowed median benchmark-excess return at least 0%.
   - P0-allowed excess hit rate at least 60%.
   - P0-allowed mean excess at least 3 percentage points above the abstained
     bucket.
   - No single matured plan contributes more than 50% of cumulative allowed
     excess.
5. **Concentration and robustness**
   - No ticker exceeds 50% of historical P0 allowed long slots.
   - No ticker contributes more than 50% of cumulative historical P0 spread.
   - Leave-one-cycle-out P0 uplift remains non-negative for every removed
     historical cycle.
   - Stored seed/member diagnostics show no member with negative aggregate
     validation spread or catastrophic gate failure. If stored artifacts are
     insufficient, the result is `inconclusive`, which blocks promotion rather
     than triggering immediate retraining.
6. **Operational quality**
   - All Growth24 tests and branch hygiene pass.
   - GitNexus change detection shows only expected research symbols and flows.
   - No live module or live policy file is modified.

### 6.2 P3 Replacement Thresholds

P3 remains exploratory unless all P0 thresholds pass and replacement has:

- At least 5 matured replacement opportunities.
- Positive mean replacement delta versus the original selection.
- Non-negative median replacement delta.
- Replacement-delta hit rate at least 60%.
- Worst replacement delta greater than -10%.
- No reduction in allowed-plan performance or stress performance versus P0.

Until then, replacement cannot be included in a live-policy review.

### 6.3 Hard Rejection / Stop Conditions

Stop a candidate or workstream without retuning when any of the following
occurs:

- Any new temporal checkpoint has allowed mean spread at or below 0%, hit below
  50%, or drawdown below -25%.
- A candidate contract returns `fail` on walk-forward or sensitivity.
- Any proposed model challenger has negative uplift on either fixed historical
  holdout.
- Paper P0 allowed outcomes underperform abstained outcomes after the minimum
  matured counts are reached.
- A result depends on one ticker or one cycle beyond the concentration limits.
- A research change requires touching a prohibited pipeline module.

Failing or inconclusive evidence means keep the paper/live rules unchanged.

## 7. Shared Phase 2 Command Preamble

Run every command from PowerShell in the research worktree:

```powershell
Set-Location D:\fund_monitor_research
$py = "D:\fund_monitor\.venv\Scripts\python.exe"
$run = "data\experiment\growth24_research_plan_20260605"
$panel = "data\experiment\dl_research_panels\research_growth_24_price_earnings_av_panel.parquet"
$champion = "data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet"
New-Item -ItemType Directory -Force -Path $run | Out-Null
```

The frozen champion extra-feature set is:

```powershell
$features = @(
  "momentum_12_1","momentum_6_1","momentum_3_1",
  "overnight_return_5d","intraday_return_5d",
  "overnight_return_20d","intraday_return_20d",
  "atr_percentile","hv_percentile","vol_regime",
  "gap_magnitude_5d","gap_5d_count",
  "Market_Ret_5D","Market_Ret_21D","Market_Ret_63D",
  "Market_Vol_21D","Market_Vol_63D",
  "Market_Drawdown_63D","Market_Drawdown_252D",
  "Market_Stress_Regime",
  "Rel_Ret_5D","Rel_Ret_21D","Rel_Ret_63D",
  "RSI_14","MA_20","MA_50","MA_200","Volume",
  "earnings_surprise_last","earnings_beat_rate_4q",
  "days_since_earnings","post_earnings_window_active",
  "earnings_surprise_direction","earnings_abs_surprise",
  "post_earnings_positive_drift_window",
  "post_earnings_negative_drift_window",
  "earnings_surprise_x_atr_regime",
  "earnings_surprise_x_gap_count"
) -join ","
```

Before each milestone:

```powershell
git status --short --branch
git fetch origin --prune
git rebase origin/main
& $py .\scripts\check_branch_hygiene.py --base origin/main
```

Do not continue if the worktree is dirty before the rebase, if the branch is
diverged unexpectedly, or if hygiene fails.

## 8. Milestone A - Reproducibility and Frozen-Policy Audit

### Question

Can the existing champion contract and the three pre-registered policy forms be
reproduced from the current research branch without changing thresholds?

### Exact Commands

Candidate-contract regression:

```powershell
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
```

P0 replay:

```powershell
& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log $champion --long-n 2 --short-n 2 `
  --expected-universe-count 24 `
  --max-universe-score-std 0.085 --max-forecast-gap 4 `
  --max-consecutive 0 `
  --output "$run\champion_p0_replay.csv" `
  --summary-output "$run\champion_p0_replay.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_p0_replay.md"
```

P3 replay:

```powershell
& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log $champion --long-n 2 --short-n 2 `
  --expected-universe-count 24 `
  --max-universe-score-std 0.085 --max-forecast-gap 4 `
  --max-consecutive 3 `
  --output "$run\champion_p3_replay.csv" `
  --summary-output "$run\champion_p3_replay.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_p3_replay.md"
```

S0 replay:

```powershell
& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log $champion --long-n 2 --short-n 2 `
  --expected-universe-count 24 `
  --max-universe-score-std 0.080 --max-forecast-gap 3 `
  --max-consecutive 0 `
  --output "$run\champion_s0_replay.csv" `
  --summary-output "$run\champion_s0_replay.json" `
  --markdown-output "notes\growth24_2026-06-05_champion_s0_replay.md"
```

### Success / Stop Rule

- PASS only if the contract remains `pass` and P0/P3 reproduce the prior fixed
  results within the stated 0.10 percentage-point tolerance.
- Any mismatch stops later experiments until the cause is explained.
- S0 is recorded but not selected using this old sample.

### Cost

- Compute: CPU only, no training.
- Estimated runtime: less than 10 minutes total.

## 9. Milestone B - Fixed-Policy Historical Stress Replay

### Hypothesis

P0's score-dispersion and forecast-gap filter removes or reduces weak
top2/bottom2 stress decisions while retaining meaningful coverage.

This is not a repeat of stress model training. It applies the already-frozen
policy to the four existing stress shadow logs.

### Exact Commands

```powershell
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
```

Before aggregation, add the research-only helper
`scripts\growth24_fixed_policy_stress_summary.py` and focused test
`tests\test_growth24_fixed_policy_stress_summary.py`. Its fixed interface will
be:

```powershell
& $py .\scripts\growth24_fixed_policy_stress_summary.py `
  --input-dir $run `
  --policy-prefix "stress_" `
  --baseline-note "notes\final4_growth24_earnings_stress_weight_8e2seed_regime_gate.md" `
  --output "$run\fixed_policy_stress_summary.json" `
  --markdown-output "notes\growth24_2026-06-05_fixed_policy_stress_summary.md"
```

### Success / Stop Rule

- P0 must clear all historical-stress thresholds in Section 6.1.
- S0 is descriptive only. It cannot replace P0 based on these same stress
  windows.
- Coverage below 4/12 is `inconclusive`, not a pass.
- Failure blocks promotion but does not trigger threshold retuning.

### Cost

- Compute: CPU only, no training.
- Estimated implementation/test time: 1-2 hours.
- Estimated replay runtime: less than 10 minutes.

## 10. Milestone C - Concentration, Outlier, and Stored-Seed Audit

### Hypotheses

1. P0's historical uplift is not explained by one ticker or one removed loss.
2. The two stored champion members are both viable; the ensemble is not hiding
   a collapsed member.

This milestone does not retune ticker cooldowns and does not train a new
ensemble.

### Exact Commands

Add research-only helpers and focused tests:

- `scripts\growth24_policy_concentration_audit.py`
- `tests\test_growth24_policy_concentration_audit.py`
- `scripts\growth24_seed_stability_audit.py`
- `tests\test_growth24_seed_stability_audit.py`

Fixed interfaces:

```powershell
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

### Success / Stop Rule

- Concentration must clear Section 6.1 limits.
- Leave-one-cycle-out uplift must remain non-negative.
- Each expected seed must be present in every cycle and must have positive
  aggregate validation spread with no repeated hard-gate collapse.
- If stored results cannot support a valid seed-level conclusion, record
  `inconclusive` and block promotion. Do not immediately spend compute on
  retraining.

### Cost

- Compute: CPU only, no training.
- Estimated implementation/test time: 2-4 hours.
- Estimated runtime: less than 10 minutes.

## 11. Milestone D - Paper Maturity and Replacement Evidence

### Hypothesis

P0 permits plans with better realized 21-trading-day benchmark-excess outcomes
than the plans it abstains from. P3 replacement behavior is tested separately.

### Current Blocker

As of 2026-06-03:

- Base paper evidence had only 2 matured trades.
- The control overlay had 0 matured allowed plans.
- The one matured abstained plan was a skipped gain.
- Next due dates were 2026-06-11, 2026-06-15, 2026-06-26, and 2026-06-29.

Therefore this milestone is necessarily incremental and cannot pass at its
first checkpoint.

### Exact Commands

Run on or after each actual due date. Do not fake future evidence with a future
`--today` value.

```powershell
& $py .\dl_growth24_paper_maturity_check.py `
  --refresh-data --refresh-earnings --strict `
  --control-gate-long-n 2 --control-gate-short-n 2 `
  --control-gate-expected-universe-count 24 `
  --control-gate-max-universe-score-std 0.085 `
  --control-gate-max-score-gap 4
```

Then simulate and score P3 separately:

```powershell
& $py .\dl_growth24_overlay_candidate_sim.py `
  --paper-plan-log "data\experiment\growth24_shadow_paper\growth24_paper_plan_log.csv" `
  --forecast-log "data\experiment\growth24_shadow_paper\growth24_shadow_forecast_log.parquet" `
  --panel $panel `
  --long-n 2 --short-n 2 --expected-universe-count 24 `
  --max-universe-score-std 0.085 --max-forecast-gap 4 `
  --max-consecutive 3 `
  --output "$run\paper_p3_candidate_ledger.csv" `
  --summary-output "$run\paper_p3_candidate_summary.json" `
  --markdown-output "notes\growth24_2026-06-05_paper_p3_candidate.md"
```

For each due-date checkpoint, write a scoped note named
`notes\growth24_paper_maturity_<YYYY-MM-DD>.md` containing the exact command,
base and overlay counts, allowed/abstained metrics, skipped gains, avoided
losses, and the decision against Section 6.

### Success / Stop Rule

- P0 cannot pass until all matured-paper thresholds in Section 6.1 pass.
- P3 cannot pass until all replacement thresholds in Section 6.2 pass.
- A skipped gain is not automatically a failure, but repeated skipped gains or
  an abstained bucket that beats the allowed bucket is a hard blocker.
- No result changes the paper plan or live rules.

### Cost

- Compute: CPU and data/API refresh.
- Estimated runtime per checkpoint: 5-30 minutes, depending on refreshes.
- Calendar duration: likely several months before minimum sample counts exist.

## 12. Milestone E - Untouched Temporal Holdout Extension

### Hypothesis

P0 generalizes to decision cycles strictly after 2026-04-17, the latest cycle
used by the recent research-candidate screens.

### Leakage Rule

Only fully matured cycles with decision dates after 2026-04-17 count. The
decision date, config, and policy thresholds must be recorded before the
forward label is scored. Never backfill a threshold change into an already
observed cycle.

The first pre-registered decision date is `2026-05-18`. Do not run it until the
panel contains its full 21-trading-day forward label. Subsequent decisions use
the same 21-trading-day cadence and the same frozen config.

### Exact One-Cycle Command

Set `$decisionDate` only to the next pre-registered, fully matured date:

```powershell
$decisionDate = "2026-05-18"
$dateToken = $decisionDate.Replace("-", "")
$stem = "growth24_holdout_${dateToken}_champion_8e_2seed"

& $py .\dl_rank_head_historical_blind_loop.py `
  --panel $panel --extra-features $features `
  --start-date $decisionDate --end-date $decisionDate `
  --cycles 1 --step-days 21 `
  --epochs 8 --seeds "20260506,20260507" --val-days 126 `
  --top-n 1 --paper-long-n 2 --paper-short-n 2 `
  --device cpu `
  --date-grouped-batches --dates-per-batch 64 `
  --top-excess-weight 0.5 --top-excess-temperature 0.05 `
  --monotonic-weight 0.05 --monotonic-quantiles 5 `
  --stress-loss-weight 2.0 --stress-feature-min 2.0 `
  --stress-drawdown-threshold -0.20 `
  --target-mode date_excess `
  --output-stem $stem `
  --output "$run\${stem}_shadow_log.parquet" `
  --csv-output "$run\${stem}_shadow_log.csv" `
  --summary-output "$run\${stem}_summary.json"
```

Add the research-only append/validation helper
`scripts\growth24_holdout_ledger.py` and
`tests\test_growth24_holdout_ledger.py`. It must reject duplicate dates,
non-monotonic dates, missing 21-day labels, changed configs, or dates at/before
2026-04-17.

```powershell
& $py .\scripts\growth24_holdout_ledger.py `
  --input-glob "$run\growth24_holdout_*_champion_8e_2seed_shadow_log.parquet" `
  --minimum-decision-date "2026-04-18" `
  --output "$run\champion_untouched_holdout.parquet" `
  --summary-output "$run\champion_untouched_holdout_summary.json" `
  --markdown-output "notes\growth24_untouched_holdout_status.md"

& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log "$run\champion_untouched_holdout.parquet" `
  --long-n 2 --short-n 2 --expected-universe-count 24 `
  --max-universe-score-std 0.085 --max-forecast-gap 4 `
  --max-consecutive 0 `
  --output "$run\untouched_holdout_p0.csv" `
  --summary-output "$run\untouched_holdout_p0.json" `
  --markdown-output "notes\growth24_untouched_holdout_p0.md"

& $py .\dl_growth24_shadow_policy_replay.py `
  --shadow-log "$run\champion_untouched_holdout.parquet" `
  --long-n 2 --short-n 2 --expected-universe-count 24 `
  --max-universe-score-std 0.080 --max-forecast-gap 3 `
  --max-consecutive 0 `
  --output "$run\untouched_holdout_s0.csv" `
  --summary-output "$run\untouched_holdout_s0.json" `
  --markdown-output "notes\growth24_untouched_holdout_s0.md"
```

### Success / Stop Rule

- Apply the 6-cycle early checkpoint and 12-cycle review checkpoint from
  Section 6.1.
- Do not tune P0 after seeing these cycles.
- S0 is tracked in parallel. If S0 is selected over P0 using this block, S0
  needs a later untouched block before review.
- A failed early checkpoint stops new model-challenger compute but continued
  passive paper/holdout collection is allowed.

### Cost

- Compute: fixed champion retraining, CPU, two seeds, 8 epochs.
- Rough runtime: 1-3 hours per new matured cycle.
- Calendar duration: approximately 6 months for the early checkpoint and
  approximately 12 months for the review checkpoint.

## 13. Milestone F - Conditional Stress-Weight-3 Full Confirmation

### Dependency

Run only if Milestones A-C pass and there is no hard failure in the latest
paper/untouched checkpoint. This is the only model challenger authorized by
this plan.

### Hypothesis

Increasing the stress-loss weight from 2.0 to 3.0 can improve weak-cycle and
stress behavior without degrading the champion's general historical or fixed
holdout behavior.

### Exact 36-Cycle / 3-Epoch Command

This extends the already-provisional 12c/3e screen. It does not repeat the
failed foundation sidecar or the two-member ensemble.

```powershell
$stem = "growth24_36c_3e_stressw3_confirm_20260605"

& $py .\dl_rank_head_historical_blind_loop.py `
  --panel $panel --extra-features $features `
  --start-date "2023-05-11" --end-date "2026-04-17" `
  --cycles 36 --step-days 21 `
  --epochs 3 --seeds "20260506,20260507" --val-days 126 `
  --top-n 2 --paper-long-n 2 --paper-short-n 2 `
  --device cuda --amp `
  --date-grouped-batches --dates-per-batch 64 `
  --top-excess-weight 0.5 --top-excess-temperature 0.05 `
  --monotonic-weight 0.05 --monotonic-quantiles 5 `
  --stress-loss-weight 3.0 --stress-feature-min 2.0 `
  --stress-drawdown-threshold -0.20 `
  --target-mode date_excess `
  --output-stem $stem `
  --output "$run\${stem}_shadow_log.parquet" `
  --csv-output "$run\${stem}_shadow_log.csv" `
  --summary-output "$run\${stem}_summary.json"

& $py .\dl_growth24_candidate_contract_eval.py `
  --shadow-log "$run\${stem}_shadow_log.parquet" `
  --long-n 2 --short-n 2 --expected-universe-count 24 `
  --practical-max-universe-score-std 0.085 `
  --practical-max-forecast-gap 4 `
  --research-max-consecutive 0 `
  --splits "18,24" --min-train-cycles 12 --min-test-cycles 8 `
  --score-start-dates "2024-10-11,2025-04-15" `
  --min-holdout-allowed-cycles 4 `
  --min-holdout-filter-uplift 0 `
  --gate-min-mean-ls 0 --gate-min-hit 0.50 `
  --gate-max-drawdown -0.25 --gate-min-coverage 0.25 `
  --output "$run\${stem}_candidate_contract.json" `
  --markdown-output "notes\growth24_36c_3e_stressw3_confirm_candidate_contract.md"
```

### Gate to an 8-Epoch Confirmation

Do not run 8 epochs unless all conditions pass:

- Candidate contract is `pass`, with no skipped walk-forward or sensitivity.
- Both walk-forward splits pass.
- At least 15/18 sensitivity configs pass.
- Minimum fixed-holdout uplift is non-negative.
- P0 overlay mean spread is within 1 percentage point of or better than the
  champion P0 replay.
- P0 max drawdown is no worse than -10%.
- Historical fixed-policy stress thresholds pass.
- Concentration thresholds pass.

If all pass, run the exact same command with:

```text
--epochs 8
$stem = "growth24_36c_8e_stressw3_confirm_20260605"
```

Then repeat the same candidate-contract, stress, concentration, and fixed-policy
evaluations. A successful challenger still cannot justify live review without
new untouched and matured paper evidence.

### Cost

- 36c/3e CUDA+AMP: roughly 2-8 hours.
- Conditional 36c/8e CUDA+AMP: roughly 6-20 hours.
- CPU fallback may take 12-36+ hours and requires a separate scheduling
  decision before execution.

## 14. Milestone G - Final Synthesis

At each meaningful checkpoint, write a scoped note with:

- Exact command and git commit.
- Input artifact paths and decision-date range.
- Frozen policy/config parameters.
- Baseline, allowed, abstained, and replacement counts.
- Mean/median spread or benchmark excess, hit rate, max drawdown, coverage, and
  concentration metrics.
- Every threshold marked PASS, FAIL, or INCONCLUSIVE.
- Interpretation and explicit policy decision.

The synthesis note will be
`notes\growth24_research_synthesis_<YYYY-MM-DD>.md`.

Possible final recommendations:

1. **No change / reject**: any hard failure or minimum evidence not reached.
2. **Continue paper-only**: promising but incomplete untouched or matured-paper
   evidence.
3. **Flag P0 for live-policy review**: every Section 6.1 threshold passes.
4. **Flag P3 separately**: P0 passes and every Section 6.2 threshold passes.
5. **Replace research champion**: stress-weight-3 clears all historical,
   untouched, paper, stress, and robustness thresholds. This still requires
   user review before any pipeline change.

## 15. Verification and Atomic-Commit Workflow

After every Phase 2 milestone:

```powershell
& $py -m pytest `
  .\tests\test_growth24_overlay_candidate_sim.py `
  .\tests\test_growth24_current_control_gate.py `
  .\tests\test_growth24_shadow_policy_replay.py `
  .\tests\test_growth24_candidate_contract_eval.py `
  .\tests\test_growth24_post_prediction_gate_grid.py `
  .\tests\test_growth24_policy_threshold_sensitivity.py `
  .\tests\test_growth24_overlay_outcomes.py `
  -q

& $py .\scripts\check_branch_hygiene.py --base origin/main
git status --short --branch
git diff --stat
```

Also run each new helper's focused test. Before editing any existing symbol,
run GitNexus upstream impact analysis and report the blast radius. Before every
commit, run GitNexus staged change detection:

```text
gitnexus_detect_changes({scope: "staged"})
```

If change detection reports an unexpected pipeline symbol or flow, unstage and
investigate before committing.

Commit one milestone at a time with explicit staging, for example:

```powershell
git add .\scripts\growth24_fixed_policy_stress_summary.py
git add .\tests\test_growth24_fixed_policy_stress_summary.py
git add .\notes\growth24_2026-06-05_fixed_policy_stress_summary.md
git commit -m "Evaluate Growth24 fixed policy under stress"
git push origin growth24/research-salvage
npx.cmd gitnexus analyze
```

After each push, the next milestone starts only after a clean status and a
fresh rebase on `origin/main`. If a rebase conflict touches a prohibited
pipeline module, stop and report it rather than carrying a research-side
pipeline edit.

## 16. Ordering and Dependencies

1. Milestone A: reproducibility and frozen-policy audit.
2. Milestone B: fixed-policy stress replay.
3. Milestone C: concentration, outlier, and stored-seed audit.
4. Milestone D: paper maturity checkpoints, repeated only on actual due dates.
5. Milestone E: untouched temporal cycles, repeated only after labels mature.
6. Milestone F: conditional stress-weight-3 confirmation.
7. Milestone G: synthesis after each decision checkpoint.

Milestones A-C are cheap and establish whether continued compute is justified.
Milestones D-E are the promotion-critical evidence and are calendar-bound.
Milestone F is conditional and cannot substitute for D-E.

## 17. Rough Runtime and Compute Budget

| Milestone | Training | Estimated runtime | Execute when |
|---|---:|---:|---|
| A - frozen-policy audit | None | <10 minutes | First after approval |
| B - fixed-policy stress | None | 1-2 hours implementation, <10 minutes replay | After A passes |
| C - concentration/seed audit | None | 2-4 hours implementation, <10 minutes run | After A passes |
| D - paper maturity | None | 5-30 minutes per due-date refresh | On/after actual due dates |
| E - untouched temporal extension | 8e, 2 seeds, CPU | 1-3 hours per matured cycle | Only after each label matures |
| F - stressw3 36c/3e | 3e, 2 seeds, CUDA+AMP | 2-8 hours | Only after A-C pass and no new hard failure |
| F - conditional stressw3 36c/8e | 8e, 2 seeds, CUDA+AMP | 6-20 hours | Only after the 3e gate passes |
| G - synthesis | None | 30-90 minutes per checkpoint | After each decision checkpoint |

Runtime estimates are rough. Record actual wall time and peak resource use in
the first note for each experiment class, then update later estimates without
changing decision thresholds.

## 18. Explicit Non-Goals

- No changes to the live scheduler, pipeline, email, report, provider, or
  production-model files.
- No repeat of the failed two-member ensemble.
- No repeat of the failed foundation sidecar.
- No repeat or retuning of the simple HMM skip, old abstention grid, or cooldown
  challenger.
- No broad feature sweep.
- No threshold search on untouched or paper evidence.
- No live-policy or paper-plan change without a separate user decision after a
  pre-stated threshold is cleared.
