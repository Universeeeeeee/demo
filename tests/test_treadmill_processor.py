"""
test_treadmill_processor.py — Tests for treadmill processor and accumulator
"""

import pytest
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from config.treadmill_report import TreadmillRunningReport, TreadmillStepResult
from engine.contact_tracker import ContactState, GaitStepEvent
from engine.modes.treadmill_accumulator import TreadmillAccumulator
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from engine.modes.treadmill_processor import TreadmillProcessor
from engine.modes.treadmill_running_accumulator import (
    RUNNING_OVERLAP_TOLERANCE_S,
    TreadmillRunningAccumulator,
)
from engine.modes.treadmill_v2 import (
    TreadmillContactSnapshot,
    TreadmillCoordinateSystem,
    TreadmillFootResolver,
    TreadmillLengthCalculator,
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


def test_treadmill_length_calculator_uses_belt_plus_device_delta():
    result = TreadmillLengthCalculator.step_length(
        prev_ref_x_cm=0.0,
        curr_ref_x_cm=20.0,
        step_time_s=0.5,
        belt_speed_cm_s=100.0,
        direction="Opposite side",
    )

    assert result.method == "belt_plus_device_delta"
    assert result.quality == "ok"
    assert result.belt_distance_cm == pytest.approx(50.0)
    assert result.device_delta_cm == pytest.approx(20.0)
    assert result.length_cm == pytest.approx(70.0)


def test_treadmill_length_calculator_reverses_device_delta_by_direction():
    result = TreadmillLengthCalculator.step_length(
        prev_ref_x_cm=0.0,
        curr_ref_x_cm=20.0,
        step_time_s=0.5,
        belt_speed_cm_s=100.0,
        direction="Interface side",
    )

    assert result.direction_sign == -1
    assert result.length_cm == pytest.approx(30.0)


def test_treadmill_snapshot_semantics_gate_device_delta():
    safe = TreadmillContactSnapshot(
        contact_id=1,
        foot_side="left",
        time_s=1.0,
        reference_x_cm=10.0,
        heel_cm=0.0,
        toe_cm=10.0,
        source="stable_touch_window",
        reference_projected_to_event=True,
    )
    unsafe = TreadmillContactSnapshot(
        contact_id=2,
        foot_side="right",
        time_s=1.5,
        reference_x_cm=30.0,
        heel_cm=20.0,
        toe_cm=30.0,
        source="stable_touch_window",
        reference_projected_to_event=False,
    )
    confirmed = TreadmillContactSnapshot(
        contact_id=3,
        foot_side="right",
        time_s=2.0,
        reference_x_cm=99.0,
        heel_cm=80.0,
        toe_cm=99.0,
        source="confirmed_frame",
    )

    assert safe.is_semantically_safe_for_device_delta() is True
    assert unsafe.is_semantically_safe_for_device_delta() is False
    assert confirmed.is_semantically_safe_for_device_delta() is False


def test_heel_toe_from_cluster_prefers_observed_cluster_boundaries():
    ref = TreadmillCoordinateSystem.heel_toe_from_cluster(
        direction="Opposite side",
        cluster_start_cm=10.0,
        cluster_end_cm=30.0,
        centroid_cm=20.0,
        foot_length_cm=100.0,
    )

    assert ref.heel_cm == 30.0
    assert ref.toe_cm == 10.0
    assert ref.source == "touch_boundary"


def test_foot_resolver_uses_active_contact_side_mapping_for_double_support():
    resolver = TreadmillFootResolver()
    diagnostics: dict[str, object] = {}

    first = resolver.resolve_touch(
        contact_id=1,
        active_sides_by_contact_id={},
        previous_touch_side=None,
        manual_starting_foot=None,
        diagnostics=diagnostics,
    )
    second = resolver.resolve_touch(
        contact_id=2,
        active_sides_by_contact_id={1: first},
        previous_touch_side=first,
        manual_starting_foot=None,
        diagnostics=diagnostics,
    )

    assert first == "left"
    assert second == "right"


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


def test_gait_accumulator_uses_safe_touch_references_for_step_length():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Opposite side",
    )
    acc = TreadmillGaitAccumulator(config)

    left = TreadmillContactSnapshot(
        contact_id=1,
        foot_side="left",
        time_s=0.0,
        reference_x_cm=0.0,
        heel_cm=0.0,
        toe_cm=0.0,
        source="touch_boundary",
    )
    right = TreadmillContactSnapshot(
        contact_id=2,
        foot_side="right",
        time_s=0.5,
        reference_x_cm=20.0,
        heel_cm=20.0,
        toe_cm=20.0,
        source="touch_boundary",
    )

    acc.record_touch(0.0, "left", 0.0, 0.0, snapshot=left)
    acc.record_lift(0.2, "left")
    acc.record_touch(0.5, "right", 20.0, 20.0, snapshot=right)
    acc.record_lift(0.8, "right")

    row = acc.rows[1]
    assert row.step_length_cm == pytest.approx(70.0)
    assert row.belt_distance_cm == pytest.approx(50.0)
    assert row.device_delta_cm == pytest.approx(20.0)
    assert row.step_length_method == "belt_plus_device_delta"
    assert row.length_quality == "ok"


def test_confirmed_frame_reference_forces_speed_only_fallback():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Opposite side",
    )
    acc = TreadmillGaitAccumulator(config)

    left = TreadmillContactSnapshot(
        contact_id=1,
        foot_side="left",
        time_s=0.0,
        reference_x_cm=0.0,
        heel_cm=0.0,
        toe_cm=0.0,
        source="touch_boundary",
    )
    right = TreadmillContactSnapshot(
        contact_id=2,
        foot_side="right",
        time_s=0.5,
        reference_x_cm=99.0,
        heel_cm=99.0,
        toe_cm=99.0,
        source="confirmed_frame",
    )

    acc.record_touch(0.0, "left", 0.0, 0.0, snapshot=left)
    acc.record_lift(0.2, "left")
    acc.record_touch(0.5, "right", 99.0, 99.0, snapshot=right)
    acc.record_lift(0.8, "right")

    row = acc.rows[1]
    assert row.step_length_cm == pytest.approx(50.0)
    assert row.step_length_method == "speed_only"
    assert row.foot_ref_source == "confirmed_frame"
    assert row.length_quality == "fallback_speed_only"


def test_stride_length_uses_same_side_touch_references_not_step_times_two():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Opposite side",
    )
    acc = TreadmillGaitAccumulator(config)

    l1 = TreadmillContactSnapshot(
        contact_id=1,
        foot_side="left",
        time_s=0.0,
        reference_x_cm=0.0,
        heel_cm=0.0,
        toe_cm=0.0,
        source="touch_boundary",
    )
    r1 = TreadmillContactSnapshot(
        contact_id=2,
        foot_side="right",
        time_s=0.5,
        reference_x_cm=0.0,
        heel_cm=0.0,
        toe_cm=0.0,
        source="touch_boundary",
    )
    l2 = TreadmillContactSnapshot(
        contact_id=3,
        foot_side="left",
        time_s=1.1,
        reference_x_cm=20.0,
        heel_cm=20.0,
        toe_cm=20.0,
        source="touch_boundary",
    )

    acc.record_touch(0.0, "left", 0.0, 0.0, snapshot=l1)
    acc.record_lift(0.2, "left")
    acc.record_touch(0.5, "right", 0.0, 0.0, snapshot=r1)
    acc.record_lift(0.7, "right")
    acc.record_touch(1.1, "left", 20.0, 20.0, snapshot=l2)
    acc.record_lift(1.3, "left")

    row = acc.rows[2]
    assert row.step_length_cm == pytest.approx(80.0)
    assert row.stride_length_cm == pytest.approx(130.0)
    assert row.stride_length_cm != pytest.approx(row.step_length_cm * 2.0)


def test_processor_uses_contact_boundary_times_not_confirmed_frame_time():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Opposite side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    contact = ContactState(
        contact_id=1,
        touch_time=1.0,
        lift_time=1.4,
        centroid_at_touch=10.0,
        latest_centroid=20.0,
        cluster_start_cm_at_touch=5.0,
        cluster_end_cm_at_touch=15.0,
        latest_cluster_start_cm=15.0,
        latest_cluster_end_cm=25.0,
    )

    processor._handle_step_event(
        GaitStepEvent(kind="touch", contact=contact),
        rel_time=1.03,
    )
    processor._handle_step_event(
        GaitStepEvent(kind="lift", contact=contact),
        rel_time=1.43,
    )

    row = processor._accumulator.rows[0]
    assert row.contact_time_s == pytest.approx(0.4)
    assert row.foot_ref_source == "touch_boundary"
    assert row.foot_ref_x_curr_cm == pytest.approx(5.0)


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
