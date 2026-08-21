## Walk-forward threshold validation (2026-08-20)

TRAIN = 2020-01-02 to 2023-01-01, TEST = 2023-01-02 to 2026-06-30 (non-overlapping, 2023-01-02 strictly after TRAIN_END). Signal = TightBase(t-1) AND BreakoutVolumeConfirmed AND RS_rank>=0.8, 90d forward return. Script: `walkforward_thresholds.py`.

### TRAIN grid search (9 combos, ranked by mean 90d return)

| tightness_max | volume_mult | n | mean_90d | winrate_90d |
|---|---|---|---|---|
| 0.15 | 3.0 | 1519 | 9.59% | 50.9% |
| 0.2 | 3.0 | 2243 | 9.40% | 49.6% |
| 0.15 | 2.0 | 2237 | 8.52% | 50.5% |
| 0.2 | 2.0 | 3302 | 8.52% | 49.7% |
| 0.1 | 3.0 | 737 | 8.34% | 49.4% |
| 0.2 | 1.5 | 4042 | 8.30% | 49.9% |
| 0.15 | 1.5 | 2772 | 8.15% | 50.6% |
| 0.1 | 2.0 | 1090 | 7.58% | 50.3% |
| 0.1 | 1.5 | 1369 | 7.24% | 50.5% |

### In-sample-best vs production default, TRAIN vs TEST

| | tightness/mult | TRAIN n | TRAIN mean | TRAIN win% | TEST n | TEST mean | TEST win% |
|---|---|---|---|---|---|---|---|
| In-sample best | 0.15/3.0 | 1519 | 9.59% | 50.9% | 2423 | -0.77% | 42.2% |
| Production default | 0.15/1.5 | 2772 | 8.15% | 50.6% | 5261 | 0.18% | 45.1% |

**Interpretation:** the in-sample-best combo (0.15/3.0) scored 9.59% mean 90d return on TRAIN vs the production default's 8.15% — looked meaningfully better in-sample. Out-of-sample on TEST it produced -0.77%, a drop of 10.36pp from TRAIN, versus the production default's own TRAIN→TEST drop of 7.98pp. The in-sample winner does NOT beat the production default out-of-sample (-0.77% vs 0.18%). This is the classic overfitting tell (Pardo): the grid-search winner degraded harder than the untouched default and lost its edge out-of-sample — do not swap the production thresholds to the in-sample-best combo. Sample sizes per cell are in the thousands, so this isn't a small-n noise artifact either way.