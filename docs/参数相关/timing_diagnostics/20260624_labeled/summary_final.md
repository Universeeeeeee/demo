# 20260624 Labeled Jump Timing Comparison - Final

Primary comparison starts at the first plausible jump row. Leading algorithm rows with missing air time or `air_time < 0.10s` are treated as standing/dropout artifacts and skipped.
The contact time of manual jump 10 is excluded because the athlete had already left the device after the last jump. Air time for jump 10 remains eligible when an algorithm row exists.

## Final Summary

| session | variant | skip | matched both | contact n | air n | contact MAE (ms) | air MAE (ms) | combined MAE (ms) | backwards | fallback |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20260624_1_10次纵跳 | current | 0 | 9 | 9 | 10 | 70.8 | 75.7 | 71.8 | 0 | 0 |
| 20260624_1_10次纵跳 | compensated | 0 | 9 | 9 | 10 | 71.1 | 75.8 | 72.0 | 0 | 0 |
| 20260624_1_10次纵跳 | touch_associated | 0 | 9 | 9 | 10 | 44.6 | 38.0 | 38.1 | 0 | 0 |
| 20260624_1_10次纵跳 | lift_associated | 0 | 9 | 9 | 10 | 70.2 | 74.9 | 71.1 | 0 | 0 |
| 20260624_1_10次纵跳 | associated | 0 | 9 | 9 | 10 | 43.6 | 37.0 | 37.2 | 0 | 0 |
| 20260624_1_10次纵跳 | onset | 0 | 9 | 9 | 10 | 45.1 | 32.3 | 38.9 | 0 | 0 |
| 20260624_2_10次纵跳 | current | 1 | 9 | 9 | 9 | 62.6 | 67.1 | 64.8 | 0 | 0 |
| 20260624_2_10次纵跳 | compensated | 1 | 9 | 9 | 9 | 62.7 | 67.1 | 64.9 | 0 | 0 |
| 20260624_2_10次纵跳 | touch_associated | 0 | 9 | 9 | 9 | 74.7 | 35.5 | 55.1 | 1 | 0 |
| 20260624_2_10次纵跳 | lift_associated | 1 | 9 | 9 | 9 | 61.2 | 65.8 | 63.5 | 0 | 0 |
| 20260624_2_10次纵跳 | associated | 0 | 9 | 9 | 9 | 73.6 | 34.2 | 53.9 | 1 | 0 |
| 20260624_2_10次纵跳 | onset | 1 | 9 | 9 | 9 | 31.5 | 34.9 | 33.2 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | current | 0 | 9 | 9 | 10 | 149.9 | 151.6 | 151.7 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | compensated | 0 | 9 | 9 | 10 | 150.1 | 151.8 | 151.9 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | touch_associated | 0 | 9 | 9 | 10 | 55.1 | 55.5 | 56.9 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | lift_associated | 0 | 9 | 9 | 10 | 149.0 | 150.7 | 150.8 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | associated | 0 | 9 | 9 | 10 | 54.0 | 54.4 | 55.8 | 0 | 0 |
| 20260624_3_垂直方向10次纵跳 | onset | 0 | 9 | 9 | 10 | 103.5 | 109.2 | 105.3 | 0 | 0 |

## Per-session Best Variant by Combined MAE

| session | best variant | skip | matched both | contact MAE (ms) | air MAE (ms) | combined MAE (ms) |
|---|---|---:|---:|---:|---:|---:|
| 20260624_1_10次纵跳 | associated | 0 | 9 | 43.6 | 37.0 | 37.2 |
| 20260624_2_10次纵跳 | onset | 1 | 9 | 31.5 | 34.9 | 33.2 |
| 20260624_3_垂直方向10次纵跳 | associated | 0 | 9 | 54.0 | 54.4 | 55.8 |

## Aggregate by Variant

| variant | matched both | contact n | air n | contact MAE (ms) | air MAE (ms) | combined MAE (ms) | skipped rows | backwards | fallback |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| current | 27 | 27 | 29 | 94.4 | 99.2 | 96.1 | 1 | 0 | 0 |
| compensated | 27 | 27 | 29 | 94.6 | 99.3 | 96.3 | 1 | 0 | 0 |
| touch_associated | 27 | 27 | 29 | 58.1 | 43.2 | 50.0 | 0 | 1 | 0 |
| lift_associated | 27 | 27 | 29 | 93.5 | 98.2 | 95.1 | 1 | 0 | 0 |
| associated | 27 | 27 | 29 | 57.1 | 42.1 | 49.0 | 0 | 1 | 0 |
| onset | 27 | 27 | 29 | 60.0 | 59.6 | 59.1 | 1 | 0 | 0 |

## Output Files

- `manual_labels_final.csv`
- `comparison_summary_final.csv`
- `comparison_detail_final.csv`
- `trim_audit_final.csv`
