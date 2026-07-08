# 20260624 Labeled Jump Timing Comparison

Manual labels contain duration-only values. Because the subject started standing in the device, the primary comparison uses `best_offset`, which skips early algorithm jump rows when that improves full-sequence alignment. `index` rows are still exported for audit.

## Best-offset Summary

| session | variant | skip | matched | contact MAE (ms) | air MAE (ms) | combined MAE (ms) | backwards | fallback |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 20260624_1_10次纵跳 | current | 0 | 9 | 70.8 | 75.7 | 71.8 | 0 | 0 |
| 20260624_1_10次纵跳 | compensated | 0 | 9 | 71.1 | 75.8 | 72.0 | 0 | 0 |
| 20260624_1_10次纵跳 | touch_associated | 0 | 9 | 44.6 | 38.0 | 38.1 | 0 | 0 |
| 20260624_1_10次纵跳 | lift_associated | 0 | 9 | 70.2 | 74.9 | 71.1 | 0 | 0 |
| 20260624_1_10次纵跳 | associated | 0 | 9 | 43.6 | 37.0 | 37.2 | 0 | 0 |
| 20260624_1_10次纵跳 | onset | 0 | 9 | 45.1 | 32.3 | 38.9 | 0 | 0 |
| 20260624_2_10次纵跳 | current | 0 | 10 | 69.8 | 84.2 | 77.0 | 0 | 0 |
| 20260624_2_10次纵跳 | compensated | 0 | 10 | 70.1 | 84.4 | 77.2 | 0 | 0 |
| 20260624_2_10次纵跳 | touch_associated | 0 | 9 | 86.7 | 35.5 | 55.1 | 1 | 0 |
| 20260624_2_10次纵跳 | lift_associated | 0 | 10 | 68.8 | 83.6 | 76.2 | 0 | 0 |
| 20260624_2_10次纵跳 | associated | 0 | 9 | 85.5 | 34.2 | 53.9 | 1 | 0 |
| 20260624_2_10次纵跳 | onset | 0 | 10 | 41.9 | 62.0 | 51.9 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | current | 0 | 9 | 149.9 | 151.6 | 151.7 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | compensated | 0 | 9 | 150.1 | 151.8 | 151.9 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | touch_associated | 0 | 9 | 55.1 | 55.5 | 56.9 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | lift_associated | 0 | 9 | 149.0 | 150.7 | 150.8 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | associated | 0 | 9 | 54.0 | 54.4 | 55.8 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | onset | 0 | 9 | 103.5 | 109.2 | 105.3 | 0 | 0 |

## Per-session Best Variant by Combined MAE

| session | best variant | skip | matched | contact MAE (ms) | air MAE (ms) | combined MAE (ms) |
|---|---|---:|---:|---:|---:|---:|
| 20260624_1_10次纵跳 | associated | 0 | 9 | 43.6 | 37.0 | 37.2 |
| 20260624_2_10次纵跳 | onset | 0 | 10 | 41.9 | 62.0 | 51.9 |
| 20260624_3_垂直方向10次纵跳 | associated | 0 | 9 | 54.0 | 54.4 | 55.8 |

## Aggregate by Variant (best_offset)

| variant | matched | contact MAE (ms) | air MAE (ms) | combined MAE (ms) | sessions with skip | backwards | fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| current | 28 | 95.9 | 103.1 | 99.3 | 0 | 0 | 0 |
| compensated | 28 | 96.1 | 103.3 | 99.6 | 0 | 0 | 0 |
| touch_associated | 27 | 62.1 | 43.0 | 50.0 | 0 | 1 | 0 |
| lift_associated | 28 | 95.0 | 102.4 | 98.6 | 0 | 0 | 0 |
| associated | 27 | 61.0 | 41.9 | 49.0 | 0 | 1 | 0 |
| onset | 28 | 62.7 | 67.6 | 64.9 | 0 | 0 | 0 |

## Output Files

- `manual_labels.csv`
- `comparison_summary.csv`
- `comparison_detail.csv`
