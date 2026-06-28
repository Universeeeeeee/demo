"""
test_treadmill_processor.py — Tests for treadmill processor and accumulator
"""

import pytest
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from config.treadmill_report import TreadmillRunningReport
from engine.modes.treadmill_accumulator import TreadmillAccumulator
from engine.modes.treadmill_processor import TreadmillProcessor


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
