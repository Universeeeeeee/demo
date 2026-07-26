# Adaptive Report and Treadmill Stride Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct treadmill stride length from authoritative same-side gait cycles and redesign the report overview/details so each mode shows a balanced, non-scrolling set of meaningful metrics.

**Architecture:** `GaitCycleRecord` becomes the authoritative owner of treadmill stride length. `TreadmillProcessor` records touch reference positions, enriches completed cycles during report construction, and builds overall/side summaries; the UI only formats already-computed report values. The report overview uses a three-column priority-driven card grid, while treadmill details use three internal tabs with one principal table per tab.

**Tech Stack:** Python 3, dataclasses, pytest, Qt via qtpy/dayu_widgets, openpyxl.

## Global Constraints

- Preserve test business flow and all existing Excel/raw-data traceability.
- Do not calculate stride as `step_length_cm * 2` or belt speed alone.
- Compute stride as belt travel plus direction-adjusted same-side touch displacement.
- Display only available metrics; valid numeric zero is not missing.
- Overview uses at most 12 cards in three columns and has no card scroll area.
- Treadmill details contain `统计汇总`, `周期明细`, and `逐步数据`.
- Do not modify unrelated dirty files: `AGENTS.md`, `README.md`, `.agents/`, or `docs/步态参数相关/步态周期定义.md`.

---

### Task 1: Make complete gait cycles the authoritative stride source

**Files:**
- Modify: `config/treadmill_report.py`
- Modify: `engine/modes/treadmill_processor.py`
- Modify: `engine/modes/treadmill_gait_accumulator.py`
- Modify: `engine/modes/treadmill_running_accumulator.py`
- Modify: `engine/modes/treadmill_accumulator.py`
- Test: `tests/test_treadmill_processor.py`

**Interfaces:**
- Produces: `GaitCycleRecord.stride_length_cm: float | None`
- Produces: `TreadmillProcessor._touch_reference_cm: dict[tuple[FootSide, float], float | None]`
- Produces: `TreadmillProcessor._cycles_with_stride(cycles) -> tuple[GaitCycleRecord, ...]`
- Preserves: `TreadmillStepResult.stride_length_cm`, populated only when an exact completed-cycle endpoint row exists.

- [ ] **Step 1: Write failing cycle-stride tests**

Add a helper and tests to `tests/test_treadmill_processor.py`:

```python
def _emit_contact(
    processor, *, kind, contact_id, label, time_s, centroid_cm
):
    contact = ContactState(
        contact_id=contact_id,
        foot_label=label,
        touch_time=time_s if kind == "touch" else None,
        lift_time=time_s if kind == "lift" else None,
        centroid_at_touch=centroid_cm,
        latest_centroid=centroid_cm,
    )
    processor._handle_step_event(GaitStepEvent(kind, contact), time_s)


@pytest.mark.parametrize(
    ("direction", "start_centroid", "end_centroid", "expected_cm"),
    [
        ("Interface side", 40.0, 45.0, 105.0),
        ("Opposite side", 40.0, 35.0, 105.0),
    ],
)
def test_treadmill_stride_uses_belt_travel_and_same_side_displacement(
    direction, start_centroid, end_centroid, expected_cm
):
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction=direction,
        starting_foot_override="left",
        step_length_calculation="Heel-to-Heel",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _emit_contact(
        processor, kind="touch", contact_id=1, label="A",
        time_s=0.0, centroid_cm=start_centroid,
    )
    _emit_contact(
        processor, kind="lift", contact_id=1, label="A",
        time_s=0.4, centroid_cm=start_centroid,
    )
    _emit_contact(
        processor, kind="touch", contact_id=2, label="A",
        time_s=1.0, centroid_cm=end_centroid,
    )

    report = processor.build_report("manual", (), ())

    assert report.gait_cycles[0].stride_length_cm == pytest.approx(expected_cm)


def test_treadmill_stride_does_not_require_endpoint_lift():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    _emit_contact(
        processor, kind="touch", contact_id=1, label="A",
        time_s=0.0, centroid_cm=40.0,
    )
    _emit_contact(
        processor, kind="lift", contact_id=1, label="A",
        time_s=0.25, centroid_cm=40.0,
    )
    _emit_contact(
        processor, kind="touch", contact_id=2, label="A",
        time_s=0.8, centroid_cm=43.0,
    )

    report = processor.build_report("manual", (), ())

    assert report.gait_cycles[0].stride_length_cm == pytest.approx(83.0)
    assert len(report.per_step_results) == 1
    assert report.per_step_results[0].stride_length_cm is None


def test_non_positive_stride_is_omitted_and_flagged():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _emit_contact(
        processor, kind="touch", contact_id=1, label="A",
        time_s=0.0, centroid_cm=200.0,
    )
    _emit_contact(
        processor, kind="lift", contact_id=1, label="A",
        time_s=0.3, centroid_cm=200.0,
    )
    _emit_contact(
        processor, kind="touch", contact_id=2, label="A",
        time_s=1.0, centroid_cm=90.0,
    )

    cycle = processor.build_report("manual", (), ()).gait_cycles[0]

    assert cycle.stride_length_cm is None
    assert "non_positive_stride_length" in cycle.quality_flags
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
pytest -q \
  tests/test_treadmill_processor.py::test_treadmill_stride_uses_belt_travel_and_same_side_displacement \
  tests/test_treadmill_processor.py::test_treadmill_stride_does_not_require_endpoint_lift \
  tests/test_treadmill_processor.py::test_non_positive_stride_is_omitted_and_flagged
```

Expected: fail because `GaitCycleRecord` has no `stride_length_cm` and current accumulators still use `step_length_cm * 2.0`.

- [ ] **Step 3: Add the cycle field and touch-reference state**

In `config/treadmill_report.py`, add the backward-compatible default field immediately before the existing inclusion fields:

```python
    total_flight_time_s: float | None
    stride_length_cm: float | None = None
    is_included_in_statistics: bool = True
```

In `TreadmillProcessor.__init__` and `reset`:

```python
        self._touch_reference_cm: dict[tuple[str, float], float | None] = {}
```

In `_handle_step_event`, after resolving `heel_cm`/`toe_cm` and before calling `record_touch` on the cycle builder:

```python
        if ev.kind == "touch":
            reference_cm = step_reference_cm(
                self._config, heel_cm=heel_cm, toe_cm=toe_cm
            )
            self._touch_reference_cm[(side, round(event_time, 9))] = reference_cm
```

Import `step_reference_cm` from `engine.modes.treadmill_accumulator`.

- [ ] **Step 4: Enrich authoritative cycles and synchronize completed endpoint rows**

Add to `TreadmillProcessor`:

```python
    def _cycles_with_stride(
        self, cycles: tuple[GaitCycleRecord, ...]
    ) -> tuple[GaitCycleRecord, ...]:
        direction_sign = -1 if self._config.direction == "Opposite side" else 1
        speed_cm_s = belt_speed_m_s(self._config) * 100.0
        enriched = []
        for cycle in cycles:
            start_ref = self._touch_reference_cm.get(
                (cycle.side, round(cycle.start_time_s, 9))
            )
            end_ref = self._touch_reference_cm.get(
                (cycle.side, round(cycle.end_time_s, 9))
            )
            stride_cm = None
            quality_flags = cycle.quality_flags
            if (
                cycle.side in ("left", "right")
                and cycle.gait_cycle_s > 0
                and start_ref is not None
                and end_ref is not None
            ):
                candidate = (
                    speed_cm_s * cycle.gait_cycle_s
                    + direction_sign * (end_ref - start_ref)
                )
                if candidate > 0:
                    stride_cm = candidate
                else:
                    quality_flags = tuple(dict.fromkeys((
                        *quality_flags, "non_positive_stride_length"
                    )))
            enriched.append(replace(
                cycle,
                stride_length_cm=stride_cm,
                quality_flags=quality_flags,
            ))
        return tuple(enriched)
```

Call it after `_cycles_with_row_inclusion(rows)` and before cycle summaries:

```python
        gait_cycles = self._cycles_with_stride(
            self._cycles_with_row_inclusion(rows)
        )
```

Add:

```python
    @staticmethod
    def _rows_with_cycle_stride(
        rows: tuple[TreadmillStepResult, ...],
        cycles: tuple[GaitCycleRecord, ...],
    ) -> tuple[TreadmillStepResult, ...]:
        stride_by_endpoint = {
            (cycle.side, round(cycle.end_time_s, 9)): cycle.stride_length_cm
            for cycle in cycles
            if cycle.stride_length_cm is not None
        }
        enriched = []
        for row in rows:
            if row.time_s is None or row.contact_time_s is None:
                enriched.append(row)
                continue
            touch_time_s = row.time_s - row.contact_time_s
            stride_cm = stride_by_endpoint.get(
                (row.side, round(touch_time_s, 9))
            )
            enriched.append(
                replace(row, stride_length_cm=stride_cm)
                if stride_cm is not None
                else row
            )
        return tuple(enriched)
```

Use this exact report-build order:

```python
        rows = self._accumulator.rows
        gait_cycles = self._cycles_with_stride(
            self._cycles_with_row_inclusion(rows)
        )
        rows = self._rows_with_cycle_stride(rows, gait_cycles)
```

Use the returned rows for `per_step_results`. If no endpoint row exists, the rows remain unchanged.

- [ ] **Step 5: Remove both `step_length_cm * 2.0` approximations**

In `treadmill_gait_accumulator.py` and `treadmill_running_accumulator.py`, replace:

```python
        stride_length_cm = (
            partial.step_length_cm * 2.0
            if partial.step_length_cm is not None
            else None
        )
```

with:

```python
        stride_length_cm = None
```

In `TreadmillAccumulator.build_valid_row_for_test`, stop deriving a stride from belt speed:

```python
        stride_length_cm = None
```

Update the old test `test_treadmill_distance_metrics_are_derived_from_belt_speed_and_time` to assert:

```python
    assert row.stride_length_cm is None
```

- [ ] **Step 6: Run Task 1 tests and verify GREEN**

Run:

```bash
pytest -q tests/test_treadmill_processor.py
```

Expected: all treadmill processor tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  config/treadmill_report.py \
  engine/modes/treadmill_processor.py \
  engine/modes/treadmill_accumulator.py \
  engine/modes/treadmill_gait_accumulator.py \
  engine/modes/treadmill_running_accumulator.py \
  tests/test_treadmill_processor.py
git commit -m "fix: compute treadmill stride from complete cycles"
```

---

### Task 2: Aggregate mode metrics with explicit side and sample semantics

**Files:**
- Modify: `engine/modes/treadmill_processor.py`
- Test: `tests/test_treadmill_processor.py`

**Interfaces:**
- Produces: `metric_summaries["cadence_steps_per_min"]`
- Produces: `left_right_results["left_<metric>"]` and `left_right_results["right_<metric>"]`
- Produces: `cycle_metric_summaries["stride_length_cm"]`
- Enforces: asymmetry only when both side summaries contain at least three values.

- [ ] **Step 1: Write failing aggregation tests**

Add to `tests/test_treadmill_processor.py`:

```python
def test_report_aggregates_stride_cadence_and_side_metrics():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    for index, (time_s, label, centroid) in enumerate([
        (0.0, "A", 40.0),
        (0.5, "B", 42.0),
        (1.0, "A", 45.0),
        (1.5, "B", 47.0),
    ]):
        _emit_contact(
            processor, kind="touch", contact_id=index, label=label,
            time_s=time_s, centroid_cm=centroid,
        )
        _emit_contact(
            processor, kind="lift", contact_id=index, label=label,
            time_s=time_s + 0.3, centroid_cm=centroid,
        )

    report = processor.build_report("manual", (), ())

    assert report.cycle_metric_summaries["stride_length_cm"].mean == pytest.approx(105.0)
    assert report.metric_summaries["cadence_steps_per_min"].mean == pytest.approx(120.0)
    assert report.left_right_results["left_step_length_cm"].count > 0
    assert report.left_right_results["right_contact_time_s"].count > 0


def test_cycle_asymmetry_requires_three_values_per_side():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    def cycle(index, side, gait_cycle_s):
        return GaitCycleRecord(
            index=index,
            side=side,
            start_time_s=float(index),
            end_time_s=float(index) + gait_cycle_s,
            gait_cycle_s=gait_cycle_s,
            stance_phase_s=0.6,
            stance_phase_percent=60.0,
            swing_phase_s=gait_cycle_s - 0.6,
            swing_phase_percent=40.0,
            step_time_s=0.5,
            single_support_s=0.4,
            single_support_percent=40.0,
            total_double_support_s=0.2,
            total_double_support_percent=20.0,
            load_response_s=0.1,
            load_response_percent=10.0,
            pre_swing_s=0.1,
            pre_swing_percent=10.0,
            total_flight_time_s=0.0,
            stride_length_cm=100.0,
        )

    cycles = (
        cycle(0, "left", 1.0),
        cycle(1, "right", 1.1),
    )

    overall, by_side, asymmetry = processor._build_cycle_summaries(cycles)

    assert overall["gait_cycle_s"].count == 2
    assert by_side["left"]["gait_cycle_s"].count == 1
    assert "gait_cycle_s" not in asymmetry


def test_cycle_asymmetry_is_computed_with_three_values_per_side():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    cycles = tuple(
        GaitCycleRecord(
            index=index,
            side=side,
            start_time_s=float(index),
            end_time_s=float(index) + duration,
            gait_cycle_s=duration,
            stance_phase_s=duration * 0.6,
            stance_phase_percent=60.0,
            swing_phase_s=duration * 0.4,
            swing_phase_percent=40.0,
            step_time_s=duration / 2.0,
            single_support_s=duration * 0.4,
            single_support_percent=40.0,
            total_double_support_s=duration * 0.2,
            total_double_support_percent=20.0,
            load_response_s=duration * 0.1,
            load_response_percent=10.0,
            pre_swing_s=duration * 0.1,
            pre_swing_percent=10.0,
            total_flight_time_s=0.0,
            stride_length_cm=100.0,
        )
        for index, (side, duration) in enumerate([
            ("left", 1.0), ("right", 1.1),
            ("left", 1.0), ("right", 1.1),
            ("left", 1.0), ("right", 1.1),
        ])
    )

    _, _, asymmetry = processor._build_cycle_summaries(cycles)

    assert asymmetry["gait_cycle_s"] == pytest.approx(
        0.1 / 1.05 * 100.0
    )
```

- [ ] **Step 2: Run aggregation tests and verify RED**

Run:

```bash
pytest -q \
  tests/test_treadmill_processor.py::test_report_aggregates_stride_cadence_and_side_metrics \
  tests/test_treadmill_processor.py::test_cycle_asymmetry_requires_three_values_per_side \
  tests/test_treadmill_processor.py::test_cycle_asymmetry_is_computed_with_three_values_per_side
```

Expected: missing summary keys and current one-per-side asymmetry behavior fail.

- [ ] **Step 3: Expand summary fields and standardize step side keys**

Add `"stride_length_cm"` to `_CYCLE_SUMMARY_FIELDS`.

Change the shared row selection to:

```python
        valid_included = [
            row for row in rows
            if row.is_event_valid and row.is_included_in_statistics
        ]
```

Remove the current shared `contact_time_s is not None` condition; every metric filters its own missing values.

Build per-step values with this exact map:

```python
        step_metric_values = {
            "contact_time_s": lambda row: row.contact_time_s,
            "step_length_cm": lambda row: row.step_length_cm,
            "flight_time_s": lambda row: row.flight_time_s,
            "cadence_steps_per_min": lambda row: (
                60.0 / row.step_time_s
                if row.step_time_s is not None and row.step_time_s > 0
                else None
            ),
        }
```

For each metric, summarize non-`None` values from valid included rows. Build side keys as:

```python
left_right[f"{side}_{metric_name}"] = summarize(side_values)
```

Do not emit an overall or side summary when every value is missing.

- [ ] **Step 4: Enforce the minimum sample rule**

In `_build_cycle_summaries`, calculate an asymmetry only when:

```python
            left_summary.count >= 3 and right_summary.count >= 3
```

Apply the same rule to step-level asymmetry entries. Store step asymmetry keys as `<metric>_percent`.

- [ ] **Step 5: Run Task 2 tests and verify GREEN**

Run:

```bash
pytest -q tests/test_treadmill_processor.py
```

Expected: all processor tests pass, with older asymmetry expectations updated to use three values per side.

- [ ] **Step 6: Commit Task 2**

```bash
git add engine/modes/treadmill_processor.py tests/test_treadmill_processor.py
git commit -m "feat: aggregate mode-specific treadmill metrics"
```

---

### Task 3: Preserve exact stride in persistence and Excel export

**Files:**
- Modify: `ui/views/report_view.py`
- Modify: `tests/test_treadmill_report.py`
- Modify: `tests/test_subject_store.py`

**Interfaces:**
- Adds: `stride_length_cm` to `GAIT_CYCLE_EXPORT_FIELDS` and `GAIT_CYCLE_EXPORT_HEADERS`
- Preserves: backward restoration of reports whose cycle dictionaries lack the new field.

- [ ] **Step 1: Write failing export and persistence tests**

In `tests/test_treadmill_report.py`, extend the cycle fixture with:

```python
        stride_length_cm=103.5,
```

and assert:

```python
    values = dict(zip(GAIT_CYCLE_EXPORT_HEADERS, _gait_cycle_rows(report)[0]))
    assert values["步幅(cm)"] == 103.5
```

In `tests/test_subject_store.py`, import `json`, add a complete `GaitCycleRecord` with `stride_length_cm=103.5` to `test_session_reconstructs_saved_jump_and_treadmill_reports`, and assert after restore:

```python
        restored = self.store.get_session(treadmill_id).report
        self.assertEqual(restored.gait_cycles[0].stride_length_cm, 103.5)
```

In the same test, remove the field from the stored JSON through the test database, then restore again:

```python
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT report_detail_json FROM test_sessions WHERE id = ?",
                (treadmill_id,),
            ).fetchone()
            detail = json.loads(row["report_detail_json"])
            detail["gait_cycles"][0].pop("stride_length_cm")
            conn.execute(
                "UPDATE test_sessions SET report_detail_json = ? WHERE id = ?",
                (json.dumps(detail, ensure_ascii=False), treadmill_id),
            )

        legacy_restored = self.store.get_session(treadmill_id).report
        self.assertIsNone(
            legacy_restored.gait_cycles[0].stride_length_cm
        )
```

- [ ] **Step 2: Run export/persistence tests and verify RED**

Run:

```bash
pytest -q tests/test_treadmill_report.py tests/test_subject_store.py
```

Expected: cycle export lacks the field; persistence may need default-aware restoration.

- [ ] **Step 3: Extend cycle export and quality labels**

In `ui/views/report_view.py`, insert `"stride_length_cm"` after `"gait_cycle_s"` in `GAIT_CYCLE_EXPORT_FIELDS` and `"步幅(cm)"` at the matching location in `GAIT_CYCLE_EXPORT_HEADERS`.

Add:

```python
    "stride_length_cm": "步幅 (cm)",
```

to `GAIT_CYCLE_METRIC_LABELS`, and:

```python
    "non_positive_stride_length": "步幅计算结果非正值",
```

to `_QUALITY_FLAG_LABELS`.

Keep the existing dataclass default path for old report dictionaries; do not synthesize stride from step length.

- [ ] **Step 4: Run Task 3 tests and verify GREEN**

Run:

```bash
pytest -q tests/test_treadmill_report.py tests/test_subject_store.py
```

Expected: all export and persistence tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add ui/views/report_view.py tests/test_treadmill_report.py tests/test_subject_store.py
git commit -m "feat: export and persist exact cycle stride"
```

---

### Task 4: Replace the scrolling overview with adaptive three-column cards

**Files:**
- Modify: `ui/views/report_view.py`
- Test: `tests/test_report_view_footprint.py`

**Interfaces:**
- Produces: `_treadmill_overview_stats(report) -> list[tuple[str, str, str]]`
- Produces: `_report_duration_s(report) -> float | None`
- Changes: `_fill_stat_cards` accepts `(label, value, tooltip)` and caps at 12.

- [ ] **Step 1: Write failing overview layout and metric tests**

Add to `tests/test_report_view_footprint.py`:

```python
def _visible_card_data(view):
    return [
        (card._label.text(), card._value.text(), card.toolTip())
        for card in view._stat_cards
        if not card.isHidden()
    ]


def test_report_overview_uses_three_columns_without_scroll(qtbot):
    view = ReportView()
    qtbot.addWidget(view)

    assert not hasattr(view, "_stats_scroll")
    assert view._stats_layout.columnCount() == 3
    assert len(view._stat_cards) == 12


def test_gait_overview_prioritizes_available_biomechanics(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=10,
        lift_count=10,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=tuple(_step(i, "left" if i % 2 == 0 else "right") for i in range(10)),
        metric_summaries={
            "step_length_cm": summarize((60.0, 62.0)),
            "contact_time_s": summarize((0.25, 0.27)),
            "cadence_steps_per_min": summarize((110.0, 114.0)),
            "flight_time_s": summarize((0.04, 0.05)),
        },
        cycle_metric_summaries={
            "stride_length_cm": summarize((122.0, 124.0)),
            "gait_cycle_s": summarize((1.0, 1.1)),
            "stance_phase_percent": summarize((61.0, 62.0)),
            "swing_phase_percent": summarize((39.0, 38.0)),
            "total_double_support_s": summarize((0.12, 0.13)),
        },
        report_config_snapshot={"treadmill_speed": 5.0, "direction": "Interface side"},
        export_timestamps=(2.0, 12.0),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)
    cards = _visible_card_data(view)
    labels = [label for label, _, _ in cards]

    assert labels[:8] == [
        "平均步长", "平均步幅", "平均步频", "平均步态周期",
        "平均触地时间", "平均支撑相", "平均摆动相", "平均双支撑时间",
    ]
    assert "平均腾空时间" not in labels
    assert "有效步数" in labels
    assert len(cards) <= 12
    assert dict((label, value) for label, value, _ in cards)["实际测试时长"] == "10.0 s"


def test_running_overview_includes_flight_time(qtbot):
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=2,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        metric_summaries={"flight_time_s": summarize((0.08, 0.09))},
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert "平均腾空时间" in [
        label for label, _, _ in _visible_card_data(view)
    ]
```

- [ ] **Step 2: Run overview tests and verify RED**

Run:

```bash
pytest -q \
  tests/test_report_view_footprint.py::test_report_overview_uses_three_columns_without_scroll \
  tests/test_report_view_footprint.py::test_gait_overview_prioritizes_available_biomechanics \
  tests/test_report_view_footprint.py::test_running_overview_includes_flight_time
```

Expected: current layout has `_stats_scroll`, uses two columns, and lacks the new dynamic labels.

- [ ] **Step 3: Build a direct three-column card container**

In `_build_ui`:

- Create 12 cards instead of 16.
- Place each card with `row, col = divmod(i, 3)`.
- Add `_stats_content` directly to `content_layout` with stretch factor 3.
- Remove `_stats_scroll`, its QSS, and the `content_layout.addStretch(1)` between metrics and replay.
- Add the replay container with stretch factor 2 and keep its minimum width.

Update `StatCard` to accept tooltips via normal `setToolTip` and slightly reduce its minimum height only if four rows do not fit the existing report viewport.

- [ ] **Step 4: Implement mode-priority formatting helpers**

Add:

```python
def _summary_mean(mapping, key):
    summary = mapping.get(key)
    return summary.mean if summary and summary.mean is not None else None


def _report_duration_s(report):
    if len(report.export_timestamps) >= 2:
        return max(report.export_timestamps) - min(report.export_timestamps)
    if len(getattr(report, "raw_gait_events", ())) >= 2:
        times = [event.time_s for event in report.raw_gait_events]
        return max(times) - min(times)
    return None
```

Implement `_treadmill_overview_stats` with the exact gait/running priority lists from the design spec. Format:

- length: `"{value:.1f} cm"`
- cadence: `"{value:.1f} steps/min"`
- cycle: `"{value:.3f} s"`
- contact/flight/double support: `"{value * 1000:.0f} ms"`
- phase: `"{value:.1f}%"`
- count: `f"{included} / {len(report.per_step_results)}"`
- speed: `"{speed:g} km/h"`
- duration: `"{duration:.1f} s"`

Use stride asymmetry first, then gait-cycle asymmetry, only when both side counts are at least three. Append context values only after core metrics, truncate to 12, and never append missing values.

Update jump stats to the exact nine-item priority list in the spec; do not display minimum/std cards.

Update the legacy `_load_gait_report` list to `(label, value, tooltip)` triples so it uses the same three-column grid without adding unsupported metrics.

- [ ] **Step 5: Extend `_fill_stat_cards` for tooltips and hard cap**

Implement:

```python
    def _fill_stat_cards(self, stats: list[tuple[str, str, str]]):
        for i, card in enumerate(self._stat_cards):
            if i < min(len(stats), 12):
                label, value, tooltip = stats[i]
                card._label.setText(label)
                card.set_value(value)
                card.set_color("#f0f0f0")
                card.setToolTip(tooltip)
                card.show()
            else:
                card.setToolTip("")
                card.hide()
```

Use a non-empty definition tooltip for “平均步长” and “平均步幅”.

- [ ] **Step 6: Run Task 4 tests and verify GREEN**

Run:

```bash
pytest -q tests/test_report_view_footprint.py
```

Expected: all report view footprint tests pass after updating obsolete assertions that expected the old stats scrollbar.

- [ ] **Step 7: Commit Task 4**

```bash
git add ui/views/report_view.py tests/test_report_view_footprint.py
git commit -m "feat: add adaptive report overview metrics"
```

---

### Task 5: Consolidate treadmill details into three filtered views

**Files:**
- Modify: `ui/views/report_view.py`
- Test: `tests/test_report_view_footprint.py`

**Interfaces:**
- Produces: `ReportView._detail_tabs: QTabWidget`
- Produces tabs: `统计汇总`, `周期明细`, `逐步数据`
- Produces filters: values `included`, `excluded`, `all`, default `included`.

- [ ] **Step 1: Write failing detail-structure and filtering tests**

Add:

```python
def test_treadmill_details_use_three_internal_tabs(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
    ))

    assert [view._detail_tabs.tabText(i) for i in range(3)] == [
        "统计汇总", "周期明细", "逐步数据",
    ]
    assert not isinstance(view._details_page, QScrollArea)


def test_non_treadmill_report_hides_empty_details_tab(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(JumpTestReport(
        touch_count=1,
        lift_count=1,
        air_times=(0.4,),
        contact_times=(0.2,),
        cycle_times=(0.6,),
        avg_jump_height=0.1962,
        max_jump_height=0.1962,
        avg_air_time=0.4,
        max_air_time=0.4,
        avg_contact_time=0.2,
        avg_cadence=100.0,
        finish_reason="manual",
        jump_heights=(0.1962,),
    ))

    assert not view._tabs.isTabVisible(1)


def test_detail_filters_default_to_included_and_preserve_report(qtbot):
    included = _cycle(index=0, is_included_in_statistics=True)
    excluded = _cycle(
        index=1,
        side="right",
        is_included_in_statistics=False,
        statistics_exclusion_reason="Contact time below minimum threshold",
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=2,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        gait_cycles=(included, excluded),
        per_step_results=(
            _step(0, "left"),
            replace(
                _step(1, "right"),
                is_included_in_statistics=False,
                statistics_exclusion_reason="Contact time below minimum threshold",
            ),
        ),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert view._cycle_filter.currentData() == "included"
    assert view._cycle_detail_table.rowCount() == 1
    view._cycle_filter.setCurrentIndex(
        view._cycle_filter.findData("excluded")
    )
    assert view._cycle_detail_table.rowCount() == 1
    assert report.gait_cycles == (included, excluded)
```

Import `replace` from `dataclasses` and `QScrollArea` for the test.

- [ ] **Step 2: Run detail tests and verify RED**

Run:

```bash
pytest -q \
  tests/test_report_view_footprint.py::test_treadmill_details_use_three_internal_tabs \
  tests/test_report_view_footprint.py::test_non_treadmill_report_hides_empty_details_tab \
  tests/test_report_view_footprint.py::test_detail_filters_default_to_included_and_preserve_report
```

Expected: current details page is a `QScrollArea`, has no internal tabs or filters, and stacks multiple tables.

- [ ] **Step 3: Replace the outer details scroll area**

In `_build_ui`:

- Create `self._details_page = QWidget()`.
- Add a `QVBoxLayout`.
- Add `self._detail_tabs = QTabWidget()`.
- Create one page/layout for each internal tab.
- Add a `QComboBox` above the cycle and step tables with items:

```python
("已纳入", "included")
("已排除", "excluded")
("全部", "all")
```

- Set both filters to `included` whenever a new report loads.
- Call `self._tabs.setTabVisible(1, True)` for treadmill reports and `False` for `JumpTestReport`/legacy `GaitTestReport`.
- Change `_add_detail_widget` to accept the destination layout explicitly; `_clear_dynamic_widgets` continues deleting only rebuilt controls/tables.

Remove `ReportDetailsScroll` QSS and retain dark table scrollbar rules.

- [ ] **Step 4: Build one merged summary table**

Replace `_build_cycle_summary_table`, `_build_treadmill_metric_summary`, and `_build_treadmill_left_right` calls with one `_build_treadmill_summary_table(report)`.

The table default columns are:

```python
["指标", "有效样本数", "总体均值", "左脚均值", "右脚均值", "不对称性"]
```

Add hidden expansion columns:

```python
["最小值", "最大值", "标准差", "CV(%)"]
```

Add a checkable `QToolButton("更多统计")` that toggles only those four columns.

Rows follow the exact mode-specific summary whitelists in the spec. Pull step rows from `metric_summaries`/`left_right_results` and cycle rows from `cycle_metric_summaries`/`cycle_side_summaries`. If side counts are below three, render the asymmetry cell as `"样本不足"`.

- [ ] **Step 5: Merge cycle timeline and cycle detail**

Change `_build_cycle_detail_table` to accept a filtered tuple and use columns:

```python
[
    "序号", "脚", "周期阶段图", "步态周期(s)",
    "支撑相(%)", "摆动相(%)", "步幅(cm)",
    "纳入统计", "统计说明",
]
```

Use `CyclePhaseBar` in column 2 and `cycle.stride_length_cm` for the stride column.

Rebuild this table from the immutable report tuple whenever the filter changes; do not mutate the report or only hide old rows.

- [ ] **Step 6: Simplify per-step tables by mode**

Gait columns:

```python
["序号", "脚", "步长(cm)", "触地时间(ms)", "纳入统计", "统计说明"]
```

Running columns insert `"腾空时间(ms)"` after contact time.

Do not display reference point, correction source, gap, or technical speed columns in the UI. Rebuild from filtered source rows when the filter changes. Keep all fields in Excel helpers.

- [ ] **Step 7: Run Task 5 tests and verify GREEN**

Run:

```bash
pytest -q tests/test_report_view_footprint.py tests/test_treadmill_report.py
```

Expected: report UI and export tests pass; only UI presentation is reduced.

- [ ] **Step 8: Commit Task 5**

```bash
git add ui/views/report_view.py tests/test_report_view_footprint.py tests/test_treadmill_report.py
git commit -m "feat: simplify treadmill report details"
```

---

### Task 6: Full regression and delivery verification

**Files:**
- Review only: all files changed in Tasks 1–5

**Interfaces:**
- Verifies the complete accepted design and preserves unrelated working-tree changes.

- [ ] **Step 1: Run focused report and algorithm tests**

```bash
pytest -q \
  tests/test_treadmill_processor.py \
  tests/test_treadmill_report.py \
  tests/test_report_view_footprint.py \
  tests/test_subject_store.py
```

Expected: zero failures.

- [ ] **Step 2: Run the full suite**

```bash
pytest -q
```

Expected: zero new failures. If the two previously observed unrelated failures remain, record their exact names and confirm they fail unchanged:

- report visibility assertion executed before showing its parent;
- TinySE `QMessageBox` test using a `SimpleNamespace` parent.

- [ ] **Step 3: Check source syntax and diff hygiene**

```bash
python -m compileall -q config engine ui
git diff --check
git status --short
git diff --stat HEAD~5..HEAD
```

Expected: compile succeeds; no whitespace errors; unrelated dirty files remain unstaged and unchanged by this implementation.

- [ ] **Step 4: Review requirements line by line**

Confirm:

- no `step_length_cm * 2.0` treadmill stride assignment remains;
- cycle stride uses belt travel plus same-side position change;
- card layout has three columns and no stats scroll;
- at most 12 non-empty cards are shown;
- gait overview omits flight time and running overview may include it;
- asymmetry requires three samples per side;
- treadmill details have exactly three internal tabs;
- default row filter is `已纳入`;
- Excel retains technical fields and includes cycle stride.

- [ ] **Step 5: Use verification-before-completion before any completion claim**

Re-run the focused command from Step 1 after the final code change and cite the fresh result in the handoff.
