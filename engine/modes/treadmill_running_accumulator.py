"""
treadmill_running_accumulator.py — running-specific treadmill row accumulator

Running rows are built around contact and airborne phases.  A short overlap is
allowed because low-speed running can briefly include double contact, but longer
overlap is excluded from statistics.
"""

from __future__ import annotations

from config.treadmill_config import FootSide, TreadmillRunningConfig
from config.treadmill_report import CorrectionSource, RowStatus, TreadmillStepResult
from engine.modes.treadmill_accumulator import (
    TreadmillAccumulator,
    _PartialRow,
    belt_speed_cm_s,
    belt_speed_m_s,
    normalize_foot_side,
    step_reference_cm,
    step_length_result,
    stride_length_result,
)
from engine.modes.treadmill_v2 import TreadmillContactSnapshot


RUNNING_OVERLAP_TOLERANCE_S = 0.05


class TreadmillRunningAccumulator(TreadmillAccumulator):
    """Accumulates treadmill running contacts with airborne phase detection."""

    def __init__(self, config: TreadmillRunningConfig) -> None:
        super().__init__(config)
        self._config: TreadmillRunningConfig = config
        self._active: dict[FootSide, _PartialRow] = {}
        self._completed_intervals: list[tuple[FootSide, float, float]] = []
        self._last_lift_time_s: float | None = None
        self._last_touch_reference_cm: float | None = None

    def record_touch(
        self,
        time_s: float,
        side: str,
        heel_cm: float,
        toe_cm: float,
        snapshot: TreadmillContactSnapshot | None = None,
    ) -> None:
        """Record a foot-down event and compute inter-touch running metrics."""
        if not self._first_contact_resolved:
            self._resolve_starting_foot_from_contact(side)
            self._first_contact_resolved = True

        foot_side = normalize_foot_side(side)
        if foot_side in self._active:
            self._finalize_partial(self._active[foot_side], time_s, "no_step")

        step_time_s: float | None = None
        if self._last_touch_time_s is not None:
            step_time_s = time_s - self._last_touch_time_s

        previous_snapshot = self._last_touch_snapshot
        previous_same_side = self._last_touch_snapshot_by_side.get(foot_side)
        gait_cycle_s: float | None = None
        if previous_same_side is not None:
            gait_cycle_s = time_s - previous_same_side.time_s

        flight_time_s: float | None = None
        if self._last_lift_time_s is not None:
            gap_s = time_s - self._last_lift_time_s
            if gap_s > 0:
                flight_time_s = gap_s

        reference_cm = (
            snapshot.reference_x_cm
            if snapshot is not None
            else step_reference_cm(self._config, heel_cm, toe_cm)
        )
        gap_between_feet_cm: float | None = None
        if self._last_touch_reference_cm is not None and reference_cm is not None:
            gap_between_feet_cm = abs(reference_cm - self._last_touch_reference_cm)

        step_result = step_length_result(
            self._config,
            previous_snapshot,
            snapshot,
            step_time_s,
        )
        stride_result = stride_length_result(
            self._config,
            previous_same_side,
            snapshot,
            gait_cycle_s,
        )

        partial = _PartialRow(
            side=foot_side,
            touch_time_s=time_s,
            heel_cm=heel_cm,
            toe_cm=toe_cm,
            step_time_s=step_time_s,
            flight_time_s=flight_time_s,
            step_length_cm=step_result.length_cm,
            step_reference_cm=reference_cm,
            gait_cycle_s=gait_cycle_s,
            snapshot=snapshot,
            step_length_result=step_result,
            stride_length_result=stride_result,
            step_prev_reference_cm=(
                previous_snapshot.reference_x_cm
                if previous_snapshot is not None
                else None
            ),
            gap_between_feet_cm=gap_between_feet_cm,
        )
        self._active[foot_side] = partial
        self._last_touch_time_s = time_s
        self._last_touch_reference_cm = reference_cm
        self._last_touch_snapshot = snapshot
        if snapshot is not None and foot_side in ("left", "right"):
            self._last_touch_snapshot_by_side[foot_side] = snapshot

    def record_lift(self, time_s: float, side: str) -> None:
        """Record a foot-up event and finalize that foot's running row."""
        foot_side = normalize_foot_side(side)
        partial = self._active.get(foot_side)
        if partial is None and len(self._active) == 1:
            foot_side, partial = next(iter(self._active.items()))
        if partial is None:
            return

        partial.lift_time_s = time_s
        self._finalize_partial(partial, time_s, "valid")

    def _finalize_partial(
        self, partial: _PartialRow, time_s: float, row_status: RowStatus
    ) -> None:
        contact_time_s = (
            partial.lift_time_s - partial.touch_time_s
            if partial.lift_time_s is not None
            else None
        )

        is_event_valid = row_status == "valid"
        is_included_in_statistics = is_event_valid
        correction_source: CorrectionSource = "none"
        event_invalid_reason: str | None = None
        statistics_exclusion_reason: str | None = None

        if row_status == "no_step":
            is_event_valid = False
            is_included_in_statistics = False
            event_invalid_reason = "Touch was replaced before lift"
            statistics_exclusion_reason = "Touch was replaced before lift"
        elif (
            contact_time_s is not None
            and self._config.min_contact_time > 0
            and contact_time_s < self._config.min_contact_time / 1000.0
        ):
            row_status = "tc_not_valid"
            is_event_valid = False
            is_included_in_statistics = False
            correction_source = "threshold_filter"
            event_invalid_reason = "Contact time below minimum threshold"
            statistics_exclusion_reason = "Contact time below minimum threshold"

        if row_status == "valid" and partial.flight_time_s is not None:
            ft_ms = partial.flight_time_s * 1000.0
            min_ft = self._config.min_flight_time
            max_ft = self._config.max_flight_time
            if (min_ft > 0 and ft_ms < min_ft) or (max_ft > 0 and ft_ms > max_ft):
                row_status = "tf_not_valid"
                is_event_valid = False
                is_included_in_statistics = False
                correction_source = "threshold_filter"
                event_invalid_reason = "Flight time outside acceptable range"
                statistics_exclusion_reason = "Flight time outside acceptable range"

        overlap_s = self._prior_overlap_duration(partial, time_s)
        if (
            row_status == "valid"
            and overlap_s > RUNNING_OVERLAP_TOLERANCE_S
        ):
            is_event_valid = True
            is_included_in_statistics = False
            correction_source = "threshold_filter"
            statistics_exclusion_reason = "Running overlap above tolerance"

        if (
            row_status == "valid"
            and is_included_in_statistics
            and partial.gap_between_feet_cm is not None
            and partial.gap_between_feet_cm < self._config.min_gap_between_feet
        ):
            is_event_valid = True
            is_included_in_statistics = False
            correction_source = "threshold_filter"
            statistics_exclusion_reason = "Gap between feet below minimum threshold"

        speed_m_s = belt_speed_m_s(self._config) if row_status != "no_step" else None
        distance_cm = speed_m_s * time_s * 100.0 if speed_m_s is not None else None
        cadence_steps_per_s = (
            1.0 / partial.step_time_s
            if partial.step_time_s is not None and partial.step_time_s > 0
            else None
        )
        stride_length_cm = (
            partial.stride_length_result.length_cm
            if partial.stride_length_result is not None
            else None
        )
        length = partial.step_length_result

        result = TreadmillStepResult(
            index=self._next_index,
            side=partial.side,
            row_status=row_status,
            is_event_valid=is_event_valid,
            is_included_in_statistics=is_included_in_statistics,
            correction_source=correction_source,
            event_invalid_reason=event_invalid_reason,
            statistics_exclusion_reason=statistics_exclusion_reason,
            time_s=time_s,
            distance_cm=distance_cm,
            contact_time_s=contact_time_s,
            flight_time_s=partial.flight_time_s,
            step_time_s=partial.step_time_s,
            gait_cycle_s=partial.gait_cycle_s,
            step_length_cm=partial.step_length_cm,
            step_reference_cm=partial.step_reference_cm,
            stride_length_cm=stride_length_cm,
            belt_speed_cm_s=belt_speed_cm_s(self._config),
            belt_distance_cm=length.belt_distance_cm if length is not None else None,
            foot_ref_x_prev_cm=partial.step_prev_reference_cm,
            foot_ref_x_curr_cm=(
                partial.snapshot.reference_x_cm
                if partial.snapshot is not None
                else partial.step_reference_cm
            ),
            device_delta_cm=length.device_delta_cm if length is not None else None,
            direction_sign=length.direction_sign if length is not None else None,
            step_length_method=length.method if length is not None else None,
            foot_ref_source=(
                partial.snapshot.source if partial.snapshot is not None else None
            ),
            length_quality=length.quality if length is not None else None,
            speed_m_s=speed_m_s,
            cadence_steps_per_s=cadence_steps_per_s,
            double_support_s=overlap_s if overlap_s > 0 else None,
            stance_phase_s=contact_time_s,
        )
        self._rows.append(result)
        self._next_index += 1

        self._active.pop(partial.side, None)
        if partial.lift_time_s is not None:
            self._completed_intervals.append(
                (partial.side, partial.touch_time_s, partial.lift_time_s)
            )
            self._last_lift_time_s = partial.lift_time_s

    def _prior_overlap_duration(self, partial: _PartialRow, end_time_s: float) -> float:
        if partial.lift_time_s is None:
            return 0.0

        start = partial.touch_time_s
        end = partial.lift_time_s
        overlap_s = 0.0

        for side, other_start, other_end in self._completed_intervals:
            if side == partial.side or other_start >= start:
                continue
            overlap_s += _overlap_duration(start, end, other_start, other_end)

        for side, other in self._active.items():
            if side == partial.side or other.touch_time_s >= start:
                continue
            overlap_s += _overlap_duration(
                start,
                end,
                other.touch_time_s,
                other.lift_time_s if other.lift_time_s is not None else end_time_s,
            )

        return overlap_s


def _overlap_duration(
    start_a: float, end_a: float, start_b: float, end_b: float
) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


__all__ = ["RUNNING_OVERLAP_TOLERANCE_S", "TreadmillRunningAccumulator"]
