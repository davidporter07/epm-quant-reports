# Growth24 Current Control Overlay Gate

- Status: `paper_control_abstain`
- Paper only: True
- Live policy changed: False
- Paper plan changed: False
- Forecast: `data\experiment\growth24_shadow_paper\growth24_current_shadow_forecast.csv`
- Paper plan: `data\experiment\growth24_shadow_paper\growth24_current_paper_plan.csv`
- AsOfDate: 2026-05-28
- Current paper selection: `INTC,MU`
- Gate longs: `INTC,MU`
- Gate shorts: `MSFT,META`

## Paper Plan Overlay

- Overlay status: `paper_overlay_abstain`
- Plan status: `selected`
- Plan longs: `INTC,MU`
- Gate status: `paper_control_abstain`
- Paper plan changed: False
- Action: Control gate would abstain from the selected paper plan; keep the base paper plan unchanged and score both paths at maturity.

## Metrics

| Metric | Value | Threshold |
|---|---:|---:|
| Universe count | 24 | 24 |
| Universe score std | 0.087727 | 0.085000 max |
| Long-short score gap | 0.314454 | n/a |
| Long-short forecast gap | -1.974865 | n/a |

## Failures

- universe score std 0.087727 > 0.085000

## Recommendation

Track as paper-control abstain only; keep existing paper plan unchanged.
