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


def normalize_foot_side(side: str) -> FootSide:
    """Return a stable FootSide label from tracker output."""
    return side if side in ("left", "right") else "unknown"


def belt_speed_m_s(config: TreadmillBaseConfig) -> float:
    """Convert treadmill speed from km/h to m/s."""
    return config.treadmill_speed / 3.6


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

        # Spatial correction tracking for per-step speed estimation
        self._last_step_reference_cm: float | None = None
        self._last_step_side: FootSide | None = None
        self._stagger_estimates: dict[tuple[FootSide, FootSide], float] = {}

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
        self, time_s: float, side: str, heel_cm: float, toe_cm: float
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

    def _spatial_correction_cm(
        self, current_ref: float | None, current_side: FootSide
    ) -> float:
        """Estimate spatial displacement corrected for foot stagger bias.

        On a treadmill the runner stays roughly in place, but foot placement
        drifts by a few cm each step.  Adjacent steps alternate left↔right,
        introducing a systematic stagger (natural foot separation) that must
        be subtracted to avoid a sawtooth artifact in per-step speed.
        """
        if self._last_step_reference_cm is None or current_ref is None:
            return 0.0

        raw_delta = current_ref - self._last_step_reference_cm

        # Update stagger estimate for alternating-foot transitions
        if (
            current_side != self._last_step_side
            and current_side != "unknown"
            and self._last_step_side is not None
            and self._last_step_side != "unknown"
        ):
            transition = (self._last_step_side, current_side)
            alpha = 0.3  # EWMA learning rate
            if transition not in self._stagger_estimates:
                self._stagger_estimates[transition] = raw_delta
            else:
                self._stagger_estimates[transition] = (
                    alpha * raw_delta
                    + (1.0 - alpha) * self._stagger_estimates[transition]
                )
            corrected_delta = raw_delta - self._stagger_estimates[transition]
        else:
            corrected_delta = raw_delta

        # Direction sign: forward drift adds to effective step length.
        # "Interface side": runner faces increasing LED indices → +1
        # "Opposite side": runner faces decreasing LED indices → -1
        direction_sign = -1 if self._config.direction == "Opposite side" else 1
        return direction_sign * corrected_delta

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

        # P1-4c: step_length_calculation reference point — record toe or heel
        reference_cm: float | None = None
        if self._config.step_length_calculation == "Tip-to-Tip":
            reference_cm = p.toe_cm
        elif self._config.step_length_calculation == "Heel-to-Heel":
            reference_cm = p.heel_cm

        # Compute derived metrics for valid rows
        time: float | None = time_s
        distance_cm: float | None = None
        step_length_cm: float | None = None
        stride_length_cm: float | None = None
        speed_m_s: float | None = None
        cadence_steps_per_s: float | None = None

        if is_event_valid:
            # Spatial correction: belt_distance + foot_placement_drift
            spatial_cm = self._spatial_correction_cm(reference_cm, p.side)
            if p.lift_time_s is not None:
                if step_time_s is not None and step_time_s > 0:
                    step_length_cm = belt_speed_ms * step_time_s * 100.0 + spatial_cm
                    speed_m_s = step_length_cm / 100.0 / step_time_s
                    cadence_steps_per_s = 1.0 / step_time_s
                else:
                    speed_m_s = belt_speed_ms
            else:
                speed_m_s = belt_speed_ms
            distance_cm = belt_speed_ms * time_s * 100.0

            # Update spatial tracking for next step
            self._last_step_reference_cm = reference_cm
            self._last_step_side = p.side

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
            cadence_steps_per_s=cadence_steps_per_s,
        )
        self._rows.append(result)
        self._next_index += 1
        self._pending = None
        # Record this row's touch time for inter-touch step_time on the NEXT row
        self._last_touch_time_s = p.touch_time_s

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
        stride_length_cm = None

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
