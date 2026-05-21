# DL Research Post-Quant Cup Next Steps

Date: 2026-05-20

Current position:

- PEAD remains the Quant Cup benchmark/champion: strong CAGR, Sharpe, and drawdown profile versus SPY.
- Growth24 DL is not production-ready yet. It has promising 36-cycle feature-panel results, but it failed the harder regime stress gates.
- The DL path should stay in offline research and paper/shadow lanes until it passes stress, abstention, and out-of-sample validation.

Completed research infrastructure:

- Distillation training now checks teacher coverage before training and no longer silently zero-imputes missing teacher ranks.
- `run_distill_sweep.bat` and `summarize_distill_sweep.py` are ready to test distillation weights `0.0, 0.3, 0.5, 0.7`.
- HMM regime detection now uses Viterbi `decode()` instead of full-sequence `predict()`.
- `get_regime_series()` is available for joining HMM regime labels to research panels.
- BIC sweep supports keeping the current 4-state HMM for now.
- Abstention gate reports now include HMM-stress diagnostics alongside the existing named stress buckets.

Near-term run order:

1. Run the distillation weight sweep.
2. Compare every distillation weight against the `0.0` no-distillation baseline.
3. If no distillation weight improves validation IC and selection score, pause distillation and focus on feature quality and gating.
4. If a distillation weight wins, replay it through the same 12-cycle, 36-cycle, regime-stress, and abstention-gate path before considering paper promotion.

LoRA / QLoRA position:

- LoRA and QLoRA are not the next best step for the current tabular rank-head model.
- They are mainly useful for large transformer models where memory-efficient fine-tuning matters.
- The current DL stack is small enough to train directly, so LoRA would add complexity without solving the current failure mode.
- The current bottleneck is not parameter-efficient fine-tuning; it is stress robustness, feature quality, leakage control, abstention reliability, and true out-of-sample behavior.

Better opportunities before LoRA / QLoRA:

- Run the distillation sweep and require it to beat the no-distillation baseline.
- Add HMM regime labels or stress flags as panel features, while keeping the regime computation honest and date-causal.
- Test PEAD-informed teacher targets or auxiliary labels, since Quant Cup showed PEAD is currently the strongest non-DL strategy.
- Expand feature validation around earnings timing, sector-relative behavior, RSI/MA/volume features, and stress-period abstention.
- Build harder final-four style DL stress tests before any production promotion.

Next opportunity implemented:

- Added `build_growth24_pead_hmm_panel.py`.
- It is an offline research helper that reads the current Growth24 price/earnings/sector panel and adds:
  - PEAD signal state derived from already-causal earnings drift fields.
  - PEAD interaction features with relative return, sector-relative return, and market stress.
  - HMM regime labels and numeric HMM stress/dummy columns from `regime_detector.get_regime_series()`.
  - HMM stress interactions with PEAD signal, 21-day return, and 21-day volatility.
- It also writes a comma-separated suggested extra-feature list for the historical blind DL loop.

When ready to run, use:

```powershell
python build_growth24_pead_hmm_panel.py
```

Then use the emitted feature list with the historical blind loop:

```powershell
python dl_rank_head_historical_blind_loop.py --panel data/experiment/dl_research_panels/research_growth_24_price_earnings_av_sector_pead_hmm_panel.parquet --extra-features "<contents of data/experiment/dl_research_panels/research_growth_24_pead_hmm_features.txt>"
```

Result update: 2026-05-21

- Broad PEAD/HMM 3-cycle smoke:
  - Mean long-short return: 3.43%
  - Spread hit rate: 66.67%
- Narrow PEAD/HMM 3-cycle smoke:
  - Mean long-short return: 10.71%
  - Spread hit rate: 66.67%
- Narrow PEAD/HMM 12-cycle seed-robust replay:
  - Mean long-short return: 1.92%
  - Spread hit rate: 41.67%

Interpretation:

- PEAD/HMM as direct rank-head input features did not survive the 12-cycle filter.
- Do not spend a 36-cycle run on this feature set.
- Keep PEAD/HMM available for gating, teacher logic, or post-prediction abstention, not as a promoted raw input bundle.

Decision rule:

- Do not promote DL because it learns well in normal windows.
- Promote only after it survives hard stress windows, abstention coverage thresholds, and a paper cycle with matured outcomes.
