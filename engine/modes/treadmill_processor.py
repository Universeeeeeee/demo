"""
treadmill_processor.py — Treadmill-mode processor (gait / running)

Pipeline per process_raw_frame call:
  1. extract_clusters(bits) -> List[Cluster]
  2. ClusterTracker.update() / get_active_tracks_view()
  3. ContactBasedGaitTracker.process_frame() -> List[GaitStepEvent]
  4. Delegate touch/lift events to TreadmillAccumulator
  5. Return event list for Qt signal emission

Distance metrics use treadmill belt travel plus safe touch-boundary foot
reference deltas when available, with speed-only fallback diagnostics.
"""

from __future__ import annotations

import logging
from typing import Any, Final, List

from config.treadmill_config import (
    Direction,
    FootSide,
    TreadmillBaseConfig,
    TreadmillGaitConfig,
    TreadmillRunningConfig,
)
from config.treadmill_report import (
    MetricSummary,
    TreadmillGaitReport,
    TreadmillRunningReport,
    summarize,
)
from engine.contact_tracker import ContactBasedGaitTracker, GaitStepEvent
from engine.modes.base import ModeProcessor
from engine.modes.treadmill_accumulator import TreadmillAccumulator, step_reference_cm
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from engine.modes.treadmill_running_accumulator import TreadmillRunningAccumulator
from engine.modes.treadmill_v2 import (
    TreadmillContactSnapshot,
    TreadmillCoordinateSystem,
    TreadmillFootResolver,
)
from engine.spatial_clusterer import ClusterTracker, extract_clusters

log = logging.getLogger(__name__)


# Heel/toe reference offsets in cm from observed centroid.
# These are rough defaults used when we do not have an accurate foot-length
# snapshot.  The processor will prefer config.foot_length_cm_snapshot when set.
_DEFAULT_HEEL_OFFSET_CM: Final[float] = 15.0
_DEFAULT_TOE_OFFSET_CM: Final[float] = 15.0


class TreadmillProcessor:
    """
    ModeProcessor for treadmill gait and treadmill running modes.

    Converts raw contact-bit frames into touch/lift events via cluster
    extraction + cluster tracking + contact-based gait tracking, then
    delegates step accumulation to TreadmillAccumulator.
    """

    _DISPLAY_MODES: Final[dict[str, str]] = {
        "treadmill_gait": "跑步机步态",
        "treadmill_running": "跑步机跑步",
    }

    # ---- Protocol attributes ----

    name: str
    display_mode: str
    lift_count: int  # exposed for GaitEngine._check_stop_condition

    # ---- Internal components ----

    _config: TreadmillBaseConfig
    _direction: Direction
    _cluster_tracker: ClusterTracker
    _contact_tracker: ContactBasedGaitTracker
    _accumulator: TreadmillAccumulator
    _heel_offset_cm: float
    _toe_offset_cm: float
    _foot_resolver: TreadmillFootResolver
    _active_sides_by_contact_id: dict[int, FootSide]
    _previous_touch_side: FootSide | None

    def __init__(self, config: TreadmillBaseConfig, mode_name: str) -> None:
        self.name = mode_name
        self.display_mode = self._DISPLAY_MODES.get(mode_name, mode_name)
        self._config = config
        self._direction = config.direction
        self.lift_count = 0

        # Derive heel/toe offsets from foot-length snapshot if available.
        self._heel_offset_cm = _DEFAULT_HEEL_OFFSET_CM
        self._toe_offset_cm = _DEFAULT_TOE_OFFSET_CM
        fl = self._config.foot_length_cm_snapshot
        if fl is not None and fl > 0:
            # Approximate: heel and toe each occupy half the foot length
            self._heel_offset_cm = fl * 0.5
            self._toe_offset_cm = fl * 0.5

        self._cluster_tracker = ClusterTracker()
        self._contact_tracker = ContactBasedGaitTracker()
        self._accumulator = self._make_accumulator()
        self._foot_resolver = TreadmillFootResolver()
        self._active_sides_by_contact_id = {}
        self._previous_touch_side = None

    # ---- ModeProcessor interface ----

    def reset(self) -> None:
        """Reset all internal state."""
        self.lift_count = 0
        self._cluster_tracker = ClusterTracker()
        self._contact_tracker.reset()
        self._accumulator = self._make_accumulator()
        self._foot_resolver = TreadmillFootResolver()
        self._active_sides_by_contact_id = {}
        self._previous_touch_side = None

    def process_raw_frame(
        self, contact_bits: List[int], rel_time: float, abs_time: float
    ) -> List[object]:
        """
        Process one frame of raw contact data.

        Pipeline:
          1. Extract spatial clusters from contact bits.
          2. Update cluster tracker with the new clusters.
          3. Get active track view and feed into contact-based gait tracker.
          4. Process touch/lift events -> emit to accumulator.

        Returns a list of event objects (currently GaitStepEvent) for
        the caller to re-emit via Qt signals.
        """
        # 1. Extract clusters
        clusters = extract_clusters(contact_bits)

        # 2. Update cluster tracker
        self._cluster_tracker.update(rel_time, clusters)

        # 3. Feed active tracks into contact-based gait tracker
        active_tracks = self._cluster_tracker.get_active_tracks_view()
        events = self._contact_tracker.process_frame(rel_time, active_tracks)

        # 4. Delegate touch/lift events to accumulator
        for ev in events:
            self._handle_step_event(ev, rel_time)

        return events

    def build_report(
        self, reason: str, export_frames: tuple, export_timestamps: tuple
    ):
        """
        Build the final test report.

        Delegates to TreadmillAccumulator for per-step data and metric
        summaries, then wraps everything in the appropriate report type.
        """
        self._accumulator.apply_automatic_data_filter()
        rows = self._accumulator.rows
        config_snapshot = self._config.to_dict()

        # Build metric summaries from valid, included rows
        valid_included = [
            r for r in rows
            if r.is_event_valid and r.is_included_in_statistics
            and r.contact_time_s is not None
        ]

        metric_summaries: dict[str, MetricSummary] = {}
        if valid_included:
            contact_times = tuple(
                r.contact_time_s for r in valid_included
                if r.contact_time_s is not None
            )
            metric_summaries["contact_time_s"] = summarize(contact_times)

            step_lengths = tuple(
                r.step_length_cm for r in valid_included
                if r.step_length_cm is not None
            )
            metric_summaries["step_length_cm"] = summarize(step_lengths)

            flight_times = tuple(
                r.flight_time_s for r in valid_included
                if r.flight_time_s is not None
            )
            metric_summaries["flight_time_s"] = summarize(flight_times)

        # Build left/right breakdowns
        left_rows = [
            r for r in rows
            if r.side == "left" and r.is_event_valid and r.is_included_in_statistics
        ]
        right_rows = [
            r for r in rows
            if r.side == "right" and r.is_event_valid and r.is_included_in_statistics
        ]

        left_right: dict[str, MetricSummary] = {}
        for side_name, side_rows in [("left", left_rows), ("right", right_rows)]:
            side_ct = tuple(
                r.contact_time_s for r in side_rows
                if r.contact_time_s is not None
            )
            side_results = side_ct  # only contact_time_s for now
            if side_results:
                left_right[side_name] = summarize(side_results)
            else:
                left_right[side_name] = summarize(())

        # Asymmetry metrics
        asymmetry: dict[str, float] = {}
        if left_rows and right_rows:
            left_ct = tuple(
                r.contact_time_s for r in left_rows
                if r.contact_time_s is not None
            )
            right_ct = tuple(
                r.contact_time_s for r in right_rows
                if r.contact_time_s is not None
            )
            if left_ct and right_ct:
                asymmetry["contact_time_delta_s"] = (
                    sum(left_ct) / len(left_ct) - sum(right_ct) / len(right_ct)
                )

        base_kwargs: dict[str, Any] = dict(
            finish_reason=reason,
            touch_count=self._contact_tracker.touch_count,
            lift_count=self.lift_count,
            resolved_starting_foot=self._accumulator.resolved_starting_foot,
            starting_foot_source=self._accumulator.starting_foot_source,
            foot_length_cm_snapshot=self._config.foot_length_cm_snapshot,
            foot_length_source=self._config.foot_length_source,
            per_step_results=rows,
            metric_summaries=metric_summaries,
            left_right_results=left_right,
            asymmetry_metrics=asymmetry,
            report_config_snapshot=config_snapshot,
            export_frames=export_frames,
            export_timestamps=export_timestamps,
        )

        if isinstance(self._config, TreadmillRunningConfig):
            return TreadmillRunningReport(**base_kwargs)
        return TreadmillGaitReport(**base_kwargs)

    # ---- Internal helpers ----

    def _make_accumulator(self) -> TreadmillAccumulator:
        if isinstance(self._config, TreadmillGaitConfig):
            return TreadmillGaitAccumulator(self._config)
        if isinstance(self._config, TreadmillRunningConfig):
            return TreadmillRunningAccumulator(self._config)
        raise TypeError(f"Unsupported treadmill config: {type(self._config).__name__}")

    def _handle_step_event(self, ev: object, rel_time: float) -> None:
        """
        Route a GaitStepEvent (touch/lift) to the TreadmillAccumulator.

        Converts cluster centroid position to heel/toe positions based on
        running direction.
        """
        if not isinstance(ev, GaitStepEvent):
            return

        if ev.kind == "touch":
            diagnostics: dict[str, object] = {}
            manual_starting_foot = (
                self._config.starting_foot_override
                if self._previous_touch_side is None
                else None
            )
            side = self._foot_resolver.resolve_touch(
                contact_id=ev.contact.contact_id,
                active_sides_by_contact_id=self._active_sides_by_contact_id,
                previous_touch_side=self._previous_touch_side,
                manual_starting_foot=manual_starting_foot,
                diagnostics=diagnostics,
            )
            if side in ("left", "right"):
                self._previous_touch_side = side
            self._active_sides_by_contact_id[ev.contact.contact_id] = side

            snapshot = self._contact_snapshot(ev, side)
            self._accumulator.record_touch(
                time_s=snapshot.time_s,
                side=side,
                heel_cm=snapshot.heel_cm,
                toe_cm=snapshot.toe_cm,
                snapshot=snapshot,
            )
        elif ev.kind == "lift":
            side = self._active_sides_by_contact_id.get(
                ev.contact.contact_id, "unknown"
            )
            lift_time = (
                ev.contact.lift_time
                if ev.contact.lift_time is not None
                else rel_time
            )
            self.lift_count += 1
            self._accumulator.record_lift(time_s=lift_time, side=side)
            self._active_sides_by_contact_id.pop(ev.contact.contact_id, None)

    def _contact_snapshot(
        self, ev: GaitStepEvent, side: FootSide
    ) -> TreadmillContactSnapshot:
        contact = ev.contact
        touch_time = contact.touch_time
        if touch_time is None:
            touch_time = contact.first_seen_time

        centroid_cm = (
            contact.centroid_at_touch
            if contact.centroid_at_touch is not None
            else contact.latest_centroid
            if contact.latest_centroid is not None
            else 0.0
        )
        foot_length_cm = (
            self._config.foot_length_cm_snapshot
            if self._config.foot_length_cm_snapshot is not None
            else self._heel_offset_cm + self._toe_offset_cm
        )
        foot_ref = TreadmillCoordinateSystem.heel_toe_from_cluster(
            direction=self._direction,
            cluster_start_cm=contact.cluster_start_cm_at_touch,
            cluster_end_cm=contact.cluster_end_cm_at_touch,
            centroid_cm=centroid_cm,
            foot_length_cm=foot_length_cm,
        )
        source = foot_ref.source
        if (
            source == "fallback_centroid"
            and contact.centroid_at_touch is None
            and contact.latest_centroid is not None
        ):
            source = "confirmed_frame"

        reference_cm = step_reference_cm(
            self._config,
            foot_ref.heel_cm,
            foot_ref.toe_cm,
        )
        return TreadmillContactSnapshot(
            contact_id=contact.contact_id,
            foot_side=side,
            time_s=touch_time,
            reference_x_cm=reference_cm,
            heel_cm=foot_ref.heel_cm,
            toe_cm=foot_ref.toe_cm,
            source=source,
        )


__all__ = ["TreadmillProcessor"]
