"""
test_treadmill_processor.py — Tests for treadmill processor and accumulator
"""

from config.treadmill_config import TreadmillGaitConfig
from engine.modes.treadmill_accumulator import TreadmillAccumulator


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
