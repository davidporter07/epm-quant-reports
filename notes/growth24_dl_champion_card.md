# Growth24 DL Champion Card

- Champion: Growth24 rank-head RSI/MA/volume/earnings
- Artifact stem: `growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed`
- Status: `research_champion_shadow_only`
- Production ready: False
- Promotion blocker: Needs stress/abstention/paper validation before forecasting-page integration.

## Historical Blind Replay

- Cycles: 36
- Mean long-short: 11.57%
- Spread hit rate: 72.22%
- Max drawdown: -31.70%
- Long hit rate: 66.67%

## Gates

- Cap-aware gate: `pass`
- Cap-aware mean excess: 12.83%
- Cap-aware coverage: 69.44%
- Cap-aware max ticker slot share: 44.00%
- Long-only gate: `pass`
- Long-only mean excess: 12.42%
- Long-only max ticker share: 85.71%
- Regime stress gate: `fail`
- Abstention gate: `fail`
- Abstention passing configs: 0
- Best abstention stress spread: 9.98%
- Best abstention stress coverage: 8.33%
- Best abstention worst stress drawdown: 0.00%
- HMM skip-stress test: `scored`
- HMM skipped stress days: 3
- HMM non-stress mean excess: 9.08%
- HMM stress-only mean excess: 14.61%
- Loss cycles: 10 (27.78%)
- Mean loss spread: -8.86%
- Worst cycle: 2025-11-13 AMD vs SNPS (-31.70%)
- Best cooldown challenger: top1, max_share=50.00%, cooldown=0, max_consecutive=3
- Best cooldown mean excess: 11.65%
- Best cooldown excess hit rate: 75.00%
- Best cooldown max slot share: 41.67%
- Cooldown stress gate: `fail`

## Live Shadow Paper

- Matured trades: 2
- Pending trades: 5
- Mean forward 21D: 33.18%
- Mean excess 21D: 28.26%
- Excess hit rate: 100.00%

## Next Required Work

- Do not run 36-cycle PEAD/HMM raw-feature replay; 12-cycle filter failed.
- Do not use simple HMM-stress skipping as the next abstention rule; it skipped too few dates and removed profitable stress decisions.
- Do not promote the ticker cooldown challenger yet; it improved 36-cycle average but failed the stress gate.
- Keep the champion fixed while testing one challenger at a time.
- Treat regime stress and abstention as the active blocker before forecasting-page integration.
- Continue Growth24 paper outcome scoring until more plans mature.
- Only consider forecasting-page integration after stress, abstention, and matured paper evidence pass.
