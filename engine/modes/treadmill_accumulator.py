"""
treadmill_accumulator.py — TreadmillAccumulator for building per-step result rows

Accumulates touch/lift events into TreadmillStepResult rows, resolves
starting foot, applies threshold and automatic-data filters, and computes
distance/speed metrics derived from belt speed and timing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, List, Tuple

from config.treadmill_config import (
    FootSide,
    StartingFootSource,
    TreadmillBaseConfig,
    TreadmillGaitConfig,
)
from config.treadmill_report import (
    CorrectionSource,
    RowStatus,
    TreadmillStepResult,
)
from engine.modes.treadmill_v2 import (
    LengthResult,
    TreadmillContactSnapshot,
    TreadmillCoordinateSystem,
    TreadmillLengthCalculator,
)


def normalize_foot_side(side: str) -> FootSide:
    """Return a stable FootSide label from tracker output."""
    return side if side in ("left", "right") else "unknown"


def belt_speed_m_s(config: TreadmillBaseConfig) -> float:
    """Convert treadmill speed from km/h to m/s."""
    return config.treadmill_speed / 3.6


def belt_speed_cm_s(config: TreadmillBaseConfig) -> float:
    """Convert treadmill speed from km/h to cm/s."""
    return TreadmillCoordinateSystem.belt_speed_cm_s(config.treadmill_speed)


def step_reference_cm(
    config: TreadmillBaseConfig, heel_cm: float, toe_cm: float
) -> float | None:
    """Select the configured foot reference point for a step row."""
    if config.step_length_calculation == "Tip-to-Tip":
        return toe_cm
    if config.step_length_calculation == "Heel-to-Heel":
        return heel_cm
    return None


def step_length_from_time_cm(
    config: TreadmillBaseConfig, step_time_s: float | None
) -> float | None:
    """Compute treadmill step length from belt speed and inter-touch time."""
    if step_time_s is None or step_time_s <= 0:
        return None
    return belt_speed_m_s(config) * step_time_s * 100.0


def step_length_result(
    config: TreadmillBaseConfig,
    previous: TreadmillContactSnapshot | None,
    current: TreadmillContactSnapshot | None,
    step_time_s: float | None,
) -> LengthResult:
    """Compute V2 step length or a speed-only fallback."""
    speed_cm_s = belt_speed_cm_s(config)
    if current is None:
        return TreadmillLengthCalculator.speed_only(
            delta_time_s=step_time_s,
            belt_speed_cm_s=speed_cm_s,
            direction=config.direction,
            quality="fallback_speed_only",
        )
    return TreadmillLengthCalculator.step_length_from_snapshots(
        previous=previous,
        current=current,
        step_time_s=step_time_s,
        belt_speed_cm_s=speed_cm_s,
        direction=config.direction,
    )


def stride_length_result(
    config: TreadmillBaseConfig,
    previous_same_side: TreadmillContactSnapshot | None,
    current: TreadmillContactSnapshot | None,
    stride_time_s: float | None,
) -> LengthResult:
    """Compute V2 stride length or a speed-only fallback."""
    speed_cm_s = belt_speed_cm_s(config)
    if current is None:
        return TreadmillLengthCalculator.speed_only(
            delta_time_s=stride_time_s,
            belt_speed_cm_s=speed_cm_s,
            direction=config.direction,
            quality="fallback_speed_only",
        )
    return TreadmillLengthCalculator.stride_length_from_snapshots(
        previous_same_side=previous_same_side,
        current=current,
        stride_time_s=stride_time_s,
        belt_speed_cm_s=speed_cm_s,
        direction=config.direction,
    )


@dataclass
class _PartialRow:
    """Internal mutable state for an in-progress step row."""
    side: FootSide
    touch_time_s: float
    lift_time_s: float | None = None
    heel_cm: float = 0.0
    toe_cm: float = 0.0
    step_time_s: float | None = None
    flight_time_s: float | None = None
    step_length_cm: float | None = None
    step_reference_cm: float | None = None
    gait_cycle_s: float | None = None
    snapshot: TreadmillContactSnapshot | None = None
    step_length_result: LengthResult | None = None
    stride_length_result: LengthResult | None = None
    step_prev_reference_cm: float | None = None
    gap_between_feet_cm: float | None = None
    is_valid: bool = True
    invalid_reason: str | None = None


class TreadmillAccumulator:
    """Accumulates touch/lift events into TreadmillStepResult rows.

    Responsibilities:
      1. Maintain a list of TreadmillStepResult rows.
      2. Resolve starting foot from the first touch event.
      3. Mark row status based on config thresholds.
      4. Apply automatic data filter for gait mode.
      5. Compute distance/speed metrics from belt speed and timing.
      6. Generate metric summaries.
    """

    def __init__(self, config: TreadmillBaseConfig) -> None:
        self._config = config
        self._rows: List[TreadmillStepResult] = []
        self._pending: _PartialRow | None = None

        # Starting foot resolution
        self._starting_foot_override = config.starting_foot_override
        self._resolved_starting_foot: FootSide = "unknown"
        self._starting_foot_source: StartingFootSource = "unknown"
        self._first_contact_resolved = False

        # Counter for row indices
        self._next_index = 0

        # Track previous touch time for inter-touch step_time calculation
        self._last_touch_time_s: float | None = None
        self._last_touch_snapshot: TreadmillContactSnapshot | None = None
        self._last_touch_snapshot_by_side: dict[FootSide, TreadmillContactSnapshot] = {}

    # ---- Properties ----

    @property
    def rows(self) -> Tuple[TreadmillStepResult, ...]:
        return tuple(self._rows)

    @property
    def resolved_starting_foot(self) -> FootSide:
        return self._resolved_starting_foot

    @property
    def starting_foot_source(self) -> StartingFootSource:
        return self._starting_foot_source

    # ---- Event recording ----

    def record_touch(
        self,
        time_s: float,
        side: str,
        heel_cm: float,
        toe_cm: float,
        snapshot: TreadmillContactSnapshot | None = None,
    ) -> None:
        """Record a touch (foot-down) event and start a new partial row.

        Resolves starting foot on the first call if not already resolved.
        Stores the touch time for inter-touch step_time computation.
        """
        # Resolve starting foot from first contact
        if not self._first_contact_resolved:
            self._resolve_starting_foot_from_contact(side)
            self._first_contact_resolved = True

        # Flush any pending row that was never lifted (force lift at touch time)
        if self._pending is not None:
            self._finalize_row(self._pending.touch_time_s, "no_step")

        # Convert side to FootSide
        foot_side: FootSide = side if side in ("left", "right") else "unknown"

        self._pending = _PartialRow(
            side=foot_side,
            touch_time_s=time_s,
            heel_cm=heel_cm,
            toe_cm=toe_cm,
            snapshot=snapshot,
        )

    def record_lift(self, time_s: float, side: str) -> None:
        """Record a lift (foot-up) event and finalize the pending row."""
        if self._pending is None:
            return  # ignore lifts without a prior touch

        self._pending.lift_time_s = time_s
        min_contact_ms = self._config.min_contact_time
        contact_time_s = time_s - self._pending.touch_time_s

        # Apply threshold filter: min_contact_time (ms), min_flight_time (ms), max_flight_time (ms)
        if min_contact_ms > 0 and contact_time_s < min_contact_ms / 1000.0:
            self._finalize_row(time_s, "tc_not_valid")
        else:
            self._finalize_row(time_s, "valid")

    def _finalize_row(self, time_s: float, row_status: RowStatus) -> None:
        """Build a TreadmillStepResult from the pending row and append to rows."""
        if self._pending is None:
            return

        p = self._pending
        contact_time_s = p.lift_time_s - p.touch_time_s if p.lift_time_s is not None else None
        belt_speed_ms = self._config.treadmill_speed / 3.6
        flight_time_s: float | None = None
        step_time_s: float | None = None
        gait_cycle_s: float | None = None

        # Compute flight time from gap to previous row's lift time
        if self._rows and self._rows[-1].time_s is not None and row_status != "no_step":
            flight_time_s = p.touch_time_s - self._rows[-1].time_s  # type: ignore[operator]

        # P1-4b: Compute step_time as inter-touch interval
        if self._last_touch_time_s is not None and row_status != "no_step":
            step_time_s = p.touch_time_s - self._last_touch_time_s

        is_event_valid = row_status == "valid"
        is_included_in_statistics = is_event_valid

        correction_source: CorrectionSource
        event_invalid_reason: str | None = None
        statistics_exclusion_reason: str | None = None

        if row_status == "tc_not_valid":
            is_included_in_statistics = False
            correction_source = "threshold_filter"
            event_invalid_reason = "Contact time below minimum threshold"
            statistics_exclusion_reason = "Contact time below minimum threshold"
        else:
            correction_source = "none"

        # P1-4a: Flight time threshold validation
        if row_status == "valid" and flight_time_s is not None:
            min_ft = self._config.min_flight_time
            max_ft = self._config.max_flight_time
            ft_ms = flight_time_s * 1000.0
            if (min_ft > 0 and ft_ms < min_ft) or (max_ft > 0 and ft_ms > max_ft):
                row_status = "tf_not_valid"
                is_event_valid = False
                is_included_in_statistics = False
                correction_source = "threshold_filter"
                event_invalid_reason = "Flight time outside acceptable range"
                statistics_exclusion_reason = "Flight time outside acceptable range"

        # Compute derived metrics for valid rows
        time: float | None = time_s
        distance_cm: float | None = None
        step_length_cm: float | None = None
        stride_length_cm: float | None = None
        speed_m_s: float | None = None
        cadence_steps_per_s: float | None = None

        if is_event_valid:
            speed_m_s = belt_speed_ms
            # Use the current row time as elapsed time
            distance_cm = speed_m_s * time_s * 100.0
            if p.lift_time_s is not None:
                if step_time_s is not None and step_time_s > 0:
                    length = step_length_result(
                        self._config,
                        self._last_touch_snapshot,
                        p.snapshot,
                        step_time_s,
                    )
                    step_length_cm = length.length_cm
                    cadence_steps_per_s = 1.0 / step_time_s
                else:
                    length = step_length_result(
                        self._config,
                        self._last_touch_snapshot,
                        p.snapshot,
                        step_time_s,
                    )
            else:
                length = step_length_result(
                    self._config,
                    self._last_touch_snapshot,
                    p.snapshot,
                    step_time_s,
                )
        else:
            length = step_length_result(
                self._config,
                self._last_touch_snapshot,
                p.snapshot,
                step_time_s,
            )

        # P1-4c: step_length_calculation reference point — record toe or heel
        reference_cm: float | None = None
        if self._config.step_length_calculation == "Tip-to-Tip":
            reference_cm = p.toe_cm
        elif self._config.step_length_calculation == "Heel-to-Heel":
            reference_cm = p.heel_cm

        result = TreadmillStepResult(
            index=self._next_index,
            side=p.side,
            row_status=row_status,
            is_event_valid=is_event_valid,
            is_included_in_statistics=is_included_in_statistics,
            correction_source=correction_source,
            event_invalid_reason=event_invalid_reason,
            statistics_exclusion_reason=statistics_exclusion_reason,
            time_s=time,
            contact_time_s=contact_time_s,
            flight_time_s=flight_time_s,
            step_time_s=step_time_s,
            speed_m_s=speed_m_s,
            distance_cm=distance_cm,
            step_length_cm=step_length_cm,
            step_reference_cm=reference_cm,
            stride_length_cm=stride_length_cm,
            belt_speed_cm_s=belt_speed_cm_s(self._config),
            belt_distance_cm=length.belt_distance_cm,
            foot_ref_x_prev_cm=(
                self._last_touch_snapshot.reference_x_cm
                if self._last_touch_snapshot is not None
                else None
            ),
            foot_ref_x_curr_cm=(
                p.snapshot.reference_x_cm if p.snapshot is not None else reference_cm
            ),
            device_delta_cm=length.device_delta_cm,
            direction_sign=length.direction_sign,
            step_length_method=length.method,
            foot_ref_source=p.snapshot.source if p.snapshot is not None else None,
            length_quality=length.quality,
            cadence_steps_per_s=cadence_steps_per_s,
        )
        self._rows.append(result)
        self._next_index += 1
        self._pending = None
        # Record this row's touch time for inter-touch step_time on the NEXT row
        self._last_touch_time_s = p.touch_time_s
        self._last_touch_snapshot = p.snapshot
        if p.snapshot is not None and p.side in ("left", "right"):
            self._last_touch_snapshot_by_side[p.side] = p.snapshot

    def _resolve_starting_foot_from_contact(self, side: str) -> None:
        """Resolve starting foot from the first contact event."""
        if self._starting_foot_override is not None:
            self._resolved_starting_foot = self._starting_foot_override
            self._starting_foot_source = "manual_override"
            return

        foot_side: FootSide = side if side in ("left", "right") else "unknown"
        self._resolved_starting_foot = foot_side
        self._starting_foot_source = "auto_first_contact"

    # ---- Test helpers ----

    def append_valid_row_for_test(
        self, side: str, contact_time_s: float, step_length_cm: float
    ) -> None:
        """Append a pre-built valid row (for testing data filter behavior)."""
        foot_side: FootSide = side if side in ("left", "right") else "unknown"
        result = TreadmillStepResult(
            index=self._next_index,
            side=foot_side,
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=contact_time_s,
            step_length_cm=step_length_cm,
        )
        self._rows.append(result)
        self._next_index += 1

    def apply_automatic_data_filter(self) -> None:
        """Apply gait automatic data filter to exclude statistical outliers.

        For gait mode with automatic_data_filter > 0:
        Excludes rows from statistics where contact_time_s or step_length_cm
        deviate beyond the configured percentage from the mean.
        """
        if not isinstance(self._config, TreadmillGaitConfig):
            return

        threshold = self._config.automatic_data_filter
        if threshold <= 0:
            return

        # Gather valid rows that are currently included in statistics
        included_indices = [
            i for i, r in enumerate(self._rows)
            if r.is_event_valid and r.is_included_in_statistics
        ]
        if not included_indices:
            return

        included = [self._rows[i] for i in included_indices]

        # Filter to rows that have both contact_time_s and step_length_cm
        valid_rows = [r for r in included if r.contact_time_s is not None and r.step_length_cm is not None]
        if not valid_rows:
            return

        ct_mean = sum(r.contact_time_s for r in valid_rows) / len(valid_rows)  # type: ignore[arg-type]
        sl_mean = sum(r.step_length_cm for r in valid_rows) / len(valid_rows)  # type: ignore[arg-type]

        # Any row beyond threshold from mean in EITHER metric is excluded from statistics
        for idx in included_indices:
            row = self._rows[idx]
            if row.contact_time_s is None or row.step_length_cm is None:
                continue
            ct_dev = abs(row.contact_time_s - ct_mean) / ct_mean * 100 if ct_mean != 0 else 0.0
            sl_dev = abs(row.step_length_cm - sl_mean) / sl_mean * 100 if sl_mean != 0 else 0.0
            if ct_dev > threshold or sl_dev > threshold:
                self._rows[idx] = replace(
                    row,
                    is_included_in_statistics=False,
                    correction_source="automatic_data_filter",
                    statistics_exclusion_reason="Excluded by automatic_data_filter",
                )

    def build_valid_row_for_test(
        self, side: str, elapsed_time_s: float, step_time_s: float, gait_cycle_s: float
    ) -> TreadmillStepResult:
        """Build a TreadmillStepResult with derived metrics (for testing formulas).

        Returns a row without appending it to the accumulator.
        """
        foot_side: FootSide = side if side in ("left", "right") else "unknown"
        belt_speed_ms = self._config.treadmill_speed / 3.6
        speed_m_s = belt_speed_ms
        distance_cm = belt_speed_ms * elapsed_time_s * 100.0
        step_length_cm = belt_speed_ms * step_time_s * 100.0
        stride_length_cm = belt_speed_ms * gait_cycle_s * 100.0

        return TreadmillStepResult(
            index=-1,
            side=foot_side,
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            time_s=elapsed_time_s,
            distance_cm=distance_cm,
            step_time_s=step_time_s,
            gait_cycle_s=gait_cycle_s,
            step_length_cm=step_length_cm,
            stride_length_cm=stride_length_cm,
            speed_m_s=speed_m_s,
        )
