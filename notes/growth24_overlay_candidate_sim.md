# Growth24 Overlay Candidate Simulation

- Paper only: True
- Live policy changed: False
- Paper plan changed: False
- Plans: 6
- Overlay allowed plans: 1
- Overlay abstained plans: 5
- Replacement plans: 0
- Overlay matured plans: 0
- Overlay matured mean forward 21D: n/a

## Thresholds

- Expected universe count: 24
- Max universe score std: 0.085
- Max forecast gap: 4.0
- Max consecutive selections: 3

## Ledger

| AsOfDate | Base Longs | Candidate Longs | Overlay Status | Overlay Longs | Replacements | Failures | Overlay Outcome |
|---|---|---|---|---|---|---|---|
| 2025-12-30 | MU,INTC | MU,INTC | paper_overlay_abstain |  |  | universe score std 0.123992 > 0.085000; long-short forecast gap 6.806863 > 4.000000 | abstained |
| 2026-05-12 | LRCX,NOW | MU,INTC | paper_overlay_abstain |  |  | universe score std 0.112902 > 0.085000 | abstained |
| 2026-05-12 | MU,INTC,LRCX | MU,INTC,LRCX | paper_overlay_abstain |  |  | universe score std 0.112902 > 0.085000 | abstained |
| 2026-05-14 | INTC,MU | INTC,MU | paper_overlay_allowed | INTC,MU |  |  | pending |
| 2026-05-27 | INTC,MU | INTC,MU | paper_overlay_abstain |  |  | universe count 19 < 24 | abstained |
| 2026-05-28 | INTC,MU | INTC,MU | paper_overlay_abstain |  |  | universe score std 0.087727 > 0.085000 | abstained |
