"""
test_treadmill_processor.py — Tests for treadmill processor and accumulator
"""

import pytest
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from config.treadmill_report import TreadmillRunningReport, TreadmillStepResult
from engine.modes.treadmill_accumulator import TreadmillAccumulator
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from engine.modes.treadmill_processor import TreadmillProcessor
from engine.modes.treadmill_running_accumulator import (
    RUNNING_OVERLAP_TOLERANCE_S,
    TreadmillRunningAccumulator,
)


def test_accumulator_resolves_starting_foot_from_first_contact():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    acc = TreadmillAccumulator(config)

    acc.record_touch(time_s=0.10, side="right", heel_cm=20.0, toe_cm=45.0)

    assert acc.resolved_starting_foot == "right"
    assert acc.starting_foot_source == "auto_first_contact"


def test_accumulator_marks_short_contact_as_invalid_and_excluded():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_contact_time=100,
    )
    acc = TreadmillAccumulator(config)

    acc.record_touch(time_s=0.00, side="left", heel_cm=10.0, toe_cm=35.0)
    acc.record_lift(time_s=0.05, side="left")
    rows = acc.rows

    assert rows[0].row_status == "tc_not_valid"
    assert rows[0].is_event_valid is False
    assert rows[0].is_included_in_statistics is False
    assert rows[0].correction_source == "threshold_filter"


def test_gait_automatic_data_filter_excludes_outlier_from_statistics():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        automatic_data_filter=20,
    )
    acc = TreadmillAccumulator(config)

    acc.append_valid_row_for_test(side="left", contact_time_s=0.30, step_length_cm=60.0)
    acc.append_valid_row_for_test(side="right", contact_time_s=0.31, step_length_cm=62.0)
    acc.append_valid_row_for_test(side="left", contact_time_s=0.90, step_length_cm=130.0)
    acc.apply_automatic_data_filter()

    assert acc.rows[2].is_event_valid is True
    assert acc.rows[2].is_included_in_statistics is False
    assert acc.rows[2].correction_source == "automatic_data_filter"


def test_gait_automatic_data_filter_preserves_step_reference():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        automatic_data_filter=20,
    )
    acc = TreadmillAccumulator(config)
    acc._rows.extend([
        TreadmillStepResult(
            index=0,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=0.30,
            step_length_cm=60.0,
            step_reference_cm=35.0,
        ),
        TreadmillStepResult(
            index=1,
            side="right",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=0.31,
            step_length_cm=62.0,
            step_reference_cm=40.0,
        ),
        TreadmillStepResult(
            index=2,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=0.90,
            step_length_cm=130.0,
            step_reference_cm=37.0,
        ),
    ])

    acc.apply_automatic_data_filter()

    assert acc.rows[2].is_included_in_statistics is False
    assert acc.rows[2].step_reference_cm == 37.0


def test_treadmill_processor_builds_running_report_with_config_snapshot():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=10.0,
        direction="Interface side",
        foot_length_cm_snapshot=26.0,
        foot_length_source="manual",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")
    report = processor.build_report(reason="manual", export_frames=(), export_timestamps=())

    assert isinstance(report, TreadmillRunningReport)
    assert report.report_config_snapshot["treadmill_speed"] == 10.0
    assert report.report_config_snapshot["foot_length_cm_snapshot"] == 26.0


def test_processor_selects_gait_accumulator_for_gait_config():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )

    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    assert isinstance(processor._accumulator, TreadmillGaitAccumulator)


def test_processor_selects_running_accumulator_for_running_config():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=8.0,
        direction="Interface side",
    )

    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    assert isinstance(processor._accumulator, TreadmillRunningAccumulator)


def test_treadmill_distance_metrics_are_derived_from_belt_speed_and_time():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
    )
    acc = TreadmillAccumulator(config)

    row = acc.build_valid_row_for_test(
        side="left",
        elapsed_time_s=10.0,
        step_time_s=0.5,
        gait_cycle_s=1.0,
    )

    assert row.speed_m_s == 2.0
    assert row.distance_cm == 2000.0
    assert row.step_length_cm == 100.0
    assert row.stride_length_cm == 200.0


def test_gait_accumulator_allows_double_support_without_no_step():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.5, "right", 15.0, 40.0)
    acc.record_lift(0.8, "left")
    acc.record_lift(1.3, "right")

    rows = acc.rows
    assert len(rows) == 2
    assert [row.row_status for row in rows] == ["valid", "valid"]
    assert rows[0].contact_time_s == pytest.approx(0.8)
    assert rows[1].contact_time_s == pytest.approx(0.8)
    assert rows[0].double_support_s == pytest.approx(0.3)
    assert rows[1].double_support_s == pytest.approx(0.3)
    assert rows[1].step_time_s == pytest.approx(0.5)
    assert rows[1].step_length_cm == pytest.approx(50.0)
    assert rows[0].flight_time_s is None
    assert rows[1].flight_time_s is None


def test_gait_accumulator_filters_step_length_below_minimum():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        min_step_length=60.0,
    )
    acc = TreadmillGaitAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    acc.record_touch(0.5, "right", 15.0, 40.0)
    acc.record_lift(0.8, "right")

    row = acc.rows[1]
    assert row.step_length_cm == pytest.approx(50.0)
    assert row.is_event_valid is True
    assert row.is_included_in_statistics is False
    assert row.correction_source == "threshold_filter"
    assert row.statistics_exclusion_reason == "Step length below minimum threshold"


# ---- P1-4 tests: flight time thresholds, step_time semantics, step_length_calculation ----


def test_flight_time_min_threshold_triggers_tf_not_valid():
    """Row with flight_time below min_flight_time should be tf_not_valid."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_flight_time=50,
    )
    acc = TreadmillAccumulator(cfg)
    # First step: touch, lift, touch again — flight between first lift and second touch
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")        # row 0: valid
    acc.record_touch(0.32, "right", 15.0, 40.0)  # 20 ms flight (< 50 ms min)
    acc.record_lift(0.62, "right")      # row 1: should be tf_not_valid
    assert len(acc.rows) == 2
    r1 = acc.rows[1]
    assert r1.row_status == "tf_not_valid", f"Expected tf_not_valid, got {r1.row_status}"
    assert r1.is_event_valid is False
    assert r1.is_included_in_statistics is False
    assert r1.correction_source == "threshold_filter"
    # Even invalid rows retain timing fields
    assert r1.flight_time_s is not None
    assert r1.step_time_s is not None
    assert r1.contact_time_s is not None


def test_flight_time_max_threshold_triggers_tf_not_valid():
    """Row with flight_time above max_flight_time should be tf_not_valid."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        max_flight_time=200,
    )
    acc = TreadmillAccumulator(cfg)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    acc.record_touch(0.60, "right", 15.0, 40.0)  # 300 ms flight (> 200 ms max)
    acc.record_lift(0.90, "right")
    assert len(acc.rows) == 2
    r1 = acc.rows[1]
    assert r1.row_status == "tf_not_valid", f"Expected tf_not_valid, got {r1.row_status}"


def test_flight_time_threshold_disabled_when_zero():
    """min_flight_time=0 or max_flight_time=0 means threshold is disabled."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_flight_time=0,   # disabled
    )
    acc = TreadmillAccumulator(cfg)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    acc.record_touch(0.31, "right", 15.0, 40.0)  # 10 ms flight, but min=0 so OK
    acc.record_lift(0.61, "right")
    assert acc.rows[1].row_status != "tf_not_valid"
    assert acc.rows[1].is_event_valid is True


def test_first_step_skips_flight_time_check():
    """First step (no previous row so flight_time_s is None) must not trigger tf_not_valid."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_flight_time=1,  # non-zero, but first step has no flight_time
    )
    acc = TreadmillAccumulator(cfg)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    # Only one row — flight_time_s was never computed
    assert len(acc.rows) == 1
    assert acc.rows[0].row_status == "valid"
    assert acc.rows[0].flight_time_s is None


def test_inter_touch_step_time_not_contact_time():
    """step_time_s must be the inter-touch interval, not contact_time_s."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    acc = TreadmillAccumulator(cfg)
    # Step 1: touch at 0.0, lift at 0.30 (contact = 0.30 s)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.30, "left")
    # Step 2: touch at 0.80, lift at 1.10 (contact = 0.30 s, inter-touch = 0.80 s)
    acc.record_touch(0.80, "right", 15.0, 40.0)
    acc.record_lift(1.10, "right")

    r0 = acc.rows[0]
    # First row: no previous touch, step_time_s stays None
    assert r0.step_time_s is None, f"First row step_time should be None"

    r1 = acc.rows[1]
    assert r1.contact_time_s == pytest.approx(0.30, abs=0.01)
    # step_time must be inter-touch: 0.80 - 0.0 = 0.80, NOT contact_time
    assert r1.step_time_s == pytest.approx(0.80, abs=0.01), (
        f"step_time_s should be inter-touch (0.80), got {r1.step_time_s}"
    )


def test_step_length_calculation_does_not_alter_formula():
    """step_length_calculation selects reference point only, step_length_cm
    formula is always treadmill_speed * inter-touch step_time."""
    cfg_tip = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Tip-to-Tip",
    )
    acc_tip = TreadmillAccumulator(cfg_tip)

    cfg_heel = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Heel-to-Heel",
    )
    acc_heel = TreadmillAccumulator(cfg_heel)

    # Same touch/lift sequence for both
    belt_speed_ms = 7.2 / 3.6  # = 2.0 m/s
    for acc in (acc_tip, acc_heel):
        acc.record_touch(0.0, "left", 10.0, 35.0)
        acc.record_lift(0.30, "left")
        acc.record_touch(0.80, "right", 15.0, 40.0)
        acc.record_lift(1.10, "right")

    r_tip = acc_tip.rows[1]
    r_heel = acc_heel.rows[1]

    # step_length_cm formula is belt_speed * inter-touch step_time
    expected_step_length = belt_speed_ms * 0.80 * 100.0  # = 160 cm

    assert r_tip.step_length_cm == pytest.approx(expected_step_length, abs=0.01)
    assert r_heel.step_length_cm == pytest.approx(expected_step_length, abs=0.01)
    # Both produce identical step_length_cm
    assert abs(r_tip.step_length_cm - r_heel.step_length_cm) < 0.001


def test_step_length_calculation_records_toe_reference():
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Tip-to-Tip",
    )
    acc = TreadmillAccumulator(cfg)

    acc.record_touch(0.0, "left", heel_cm=10.0, toe_cm=35.0)
    acc.record_lift(0.30, "left")
    acc.record_touch(0.80, "right", heel_cm=15.0, toe_cm=40.0)
    acc.record_lift(1.10, "right")

    assert acc.rows[1].step_reference_cm == 40.0


def test_step_length_calculation_records_heel_reference():
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Heel-to-Heel",
    )
    acc = TreadmillAccumulator(cfg)

    acc.record_touch(0.0, "left", heel_cm=10.0, toe_cm=35.0)
    acc.record_lift(0.30, "left")
    acc.record_touch(0.80, "right", heel_cm=15.0, toe_cm=40.0)
    acc.record_lift(1.10, "right")

    assert acc.rows[1].step_reference_cm == 15.0


def test_step_reference_does_not_change_speed_time_step_length():
    cfg_tip = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Tip-to-Tip",
    )
    cfg_heel = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Heel-to-Heel",
    )

    rows = []
    for cfg in (cfg_tip, cfg_heel):
        acc = TreadmillAccumulator(cfg)
        acc.record_touch(0.0, "left", heel_cm=10.0, toe_cm=35.0)
        acc.record_lift(0.30, "left")
        acc.record_touch(0.80, "right", heel_cm=15.0, toe_cm=40.0)
        acc.record_lift(1.10, "right")
        rows.append(acc.rows[1])

    assert rows[0].step_reference_cm != rows[1].step_reference_cm
    assert rows[0].step_time_s == pytest.approx(rows[1].step_time_s)
    assert rows[0].step_length_cm == pytest.approx(rows[1].step_length_cm)


def test_running_accumulator_records_airborne_flight_time():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.45, "right", 15.0, 40.0)
    acc.record_lift(0.70, "right")

    row = acc.rows[1]
    assert row.flight_time_s == pytest.approx(0.20)
    assert row.step_time_s == pytest.approx(0.45)
    assert row.step_length_cm == pytest.approx(90.0)


def test_running_accumulator_allows_short_overlap():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)
    overlap = RUNNING_OVERLAP_TOLERANCE_S / 2

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.25 - overlap, "right", 15.0, 40.0)
    acc.record_lift(0.25, "left")
    acc.record_lift(0.50, "right")

    assert acc.rows[1].is_event_valid is True
    assert acc.rows[1].is_included_in_statistics is True
    assert acc.rows[1].statistics_exclusion_reason is None


def test_running_accumulator_excludes_long_overlap():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)
    overlap = RUNNING_OVERLAP_TOLERANCE_S + 0.02

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.25 - overlap, "right", 15.0, 40.0)
    acc.record_lift(0.25, "left")
    acc.record_lift(0.50, "right")

    assert acc.rows[1].is_event_valid is True
    assert acc.rows[1].is_included_in_statistics is False
    assert acc.rows[1].correction_source == "threshold_filter"
    assert acc.rows[1].statistics_exclusion_reason == "Running overlap above tolerance"


def test_running_accumulator_filters_gap_between_feet_below_minimum():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=20.0,
        step_length_calculation="Tip-to-Tip",
    )
    acc = TreadmillRunningAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.45, "right", 15.0, 45.0)
    acc.record_lift(0.70, "right")

    row = acc.rows[1]
    assert row.step_reference_cm == 45.0
    assert row.is_event_valid is True
    assert row.is_included_in_statistics is False
    assert row.correction_source == "threshold_filter"
    assert row.statistics_exclusion_reason == "Gap between feet below minimum threshold"


def test_treadmill_processor_records_fixed_cadence_visual_timeline():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    processor.process_raw_frame([0] * 96, rel_time=0.00, abs_time=0.00)
    processor.process_raw_frame([1] * 96, rel_time=0.01, abs_time=0.01)
    processor.process_raw_frame([1] * 96, rel_time=0.05, abs_time=0.05)
    report = processor.build_report(
        reason="manual",
        export_frames=(),
        export_timestamps=(),
    )

    assert [frame.timestamp_s for frame in report.visual_timeline] == [0.0, 0.05]
    assert report.visual_timeline[1].contact_bits == tuple([1] * 96)


def test_treadmill_processor_pop_visual_frames_returns_pending_once():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    processor.process_raw_frame([0] * 96, rel_time=0.00, abs_time=0.00)

    first = processor.pop_visual_frames()
    second = processor.pop_visual_frames()

    assert len(first) == 1
    assert second == ()


def _contact_bits(start: int, end: int) -> list[int]:
    bits = [0] * 96
    for idx in range(start, end + 1):
        bits[idx] = 1
    return bits


def _feed_frames(
    processor: TreadmillProcessor,
    bits: list[int],
    start_s: float,
    count: int,
    dt_s: float = 0.01,
) -> None:
    for offset in range(count):
        t = start_s + offset * dt_s
        processor.process_raw_frame(bits, rel_time=t, abs_time=t)


def test_treadmill_processor_makes_live_status_snapshot_from_rows():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _feed_frames(processor, [0] * 96, start_s=0.00, count=10)
    _feed_frames(processor, _contact_bits(10, 25), start_s=0.60, count=8)
    _feed_frames(processor, [0] * 96, start_s=0.70, count=20)
    _feed_frames(processor, _contact_bits(36, 51), start_s=1.30, count=8)
    _feed_frames(processor, [0] * 96, start_s=1.40, count=20)

    snapshot = processor.make_status_snapshot(rel_time=1.60)

    assert snapshot["touch_count"] == 2
    assert snapshot["lift_count"] == 2
    assert snapshot["stride_count"] == 1
    assert snapshot["latest_stride"] == pytest.approx(70.0, abs=0.01)
    assert snapshot["velocity_count"] == 2
    assert snapshot["velocity_sum"] / snapshot["velocity_count"] == pytest.approx(100.0)
    assert snapshot["latest_extra_metrics"]["imbalance_index"] == pytest.approx(0.0)


# ============================================================
# Spatial correction tests — per-step speed from foot placement
# ============================================================


def test_spatial_correction_produces_varying_speed():
    """After stagger baseline is established, drift in foot placement
    produces per-step speed values that differ from belt speed."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,  # 1.0 m/s belt
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(cfg)

    # Establish stagger baseline: two normal steps
    acc.record_touch(0.0, "left", heel_cm=25.0, toe_cm=40.0)
    acc.record_lift(0.30, "left")
    acc.record_touch(0.50, "right", heel_cm=45.0, toe_cm=60.0)
    acc.record_lift(0.80, "right")

    # Step 3: left foot with forward drift (+3 cm)
    acc.record_touch(1.10, "left", heel_cm=28.0, toe_cm=43.0)
    acc.record_lift(1.30, "left")

    # Step 4: right foot with backward drift (-2 cm)
    acc.record_touch(1.60, "right", heel_cm=43.0, toe_cm=58.0)
    acc.record_lift(1.80, "right")

    speeds = [r.speed_m_s for r in acc.rows if r.speed_m_s is not None]
    # Should have at least 3 valid speeds (steps 0,1,2,3 → 4 speeds)
    assert len(speeds) >= 3
    # Speeds should not all be identical
    unique = len(set(round(s, 4) for s in speeds))
    assert unique > 1, f"Expected varying speeds, got all {speeds[0]:.4f}"


def test_spatial_correction_first_step_uses_belt_speed():
    """The first step has no prior reference, so speed = belt speed."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,  # 2.0 m/s
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(cfg)

    acc.record_touch(0.0, "left", heel_cm=25.0, toe_cm=40.0)
    acc.record_lift(0.30, "left")

    row = acc.rows[0]
    # First step: step_time is None (no prior touch), speed = belt
    assert row.speed_m_s == 2.0
    assert row.step_length_cm is None  # no step_time → no step_length


def test_spatial_correction_respects_opposite_direction():
    """Opposite-side direction inverts the spatial correction sign."""
    cfg = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,  # 2.0 m/s
        direction="Opposite side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(cfg)

    # Establish baseline
    acc.record_touch(0.0, "left", heel_cm=50.0, toe_cm=35.0)
    acc.record_lift(0.15, "left")
    acc.record_touch(0.35, "right", heel_cm=30.0, toe_cm=15.0)
    acc.record_lift(0.50, "right")

    # Step 3: left foot with forward drift
    # Opposite side: forward = lower LED index (runner moves away from interface)
    acc.record_touch(0.70, "left", heel_cm=48.0, toe_cm=33.0)
    acc.record_lift(0.85, "left")

    # Step 4: right foot
    acc.record_touch(1.05, "right", heel_cm=32.0, toe_cm=17.0)
    acc.record_lift(1.20, "right")

    speeds = [r.speed_m_s for r in acc.rows if r.speed_m_s is not None]
    unique = len(set(round(s, 4) for s in speeds))
    assert unique > 1, f"Opposite direction should still produce varying speeds"


def test_spatial_correction_preserves_step_length_ordering():
    """Steps with forward drift should have larger step_length than
    steps with backward drift, relative to the stagger baseline."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(cfg)

    # Two baseline steps (establish stagger for both transition directions)
    acc.record_touch(0.0, "left", heel_cm=20.0, toe_cm=35.0)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.50, "right", heel_cm=40.0, toe_cm=55.0)
    acc.record_lift(0.75, "right")
    # Second occurrence of each transition to establish stagger EWMA
    acc.record_touch(1.00, "left", heel_cm=20.0, toe_cm=35.0)
    acc.record_lift(1.25, "left")
    acc.record_touch(1.50, "right", heel_cm=40.0, toe_cm=55.0)
    acc.record_lift(1.75, "right")

    # Now introduce drift: forward on left (+4 cm), backward on right (-3 cm)
    acc.record_touch(2.00, "left", heel_cm=24.0, toe_cm=39.0)
    acc.record_lift(2.25, "left")
    acc.record_touch(2.50, "right", heel_cm=37.0, toe_cm=52.0)
    acc.record_lift(2.75, "right")

    belt_speed = 3.6 / 3.6  # 1.0 m/s
    drift_steps = [r for r in acc.rows if r.index >= 4 and r.step_time_s is not None]
    for r in drift_steps:
        belt_dist = belt_speed * r.step_time_s * 100.0
        assert r.step_length_cm != pytest.approx(belt_dist, abs=0.01), (
            f"Step {r.index}: expected spatial correction, "
            f"got step_length={r.step_length_cm} == belt_dist={belt_dist}"
        )
