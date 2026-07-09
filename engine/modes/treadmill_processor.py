"""
treadmill_processor.py — Treadmill-mode processor (gait / running)

Pipeline per process_raw_frame call:
  1. extract_clusters(bits) -> List[Cluster]
  2. ClusterTracker.update() / get_active_tracks_view()
  3. ContactBasedGaitTracker.process_frame() -> List[GaitStepEvent]
  4. Delegate touch/lift events to TreadmillAccumulator
  5. Return event list for Qt signal emission

All distance metrics come from treadmill_speed x time in the accumulator.
LED clusters are used ONLY for timing (contact/lift detection).
"""

from __future__ import annotations

import logging
from typing import Any, Final, List

from config.treadmill_config import (
    Direction,
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
from engine.footprint_visualization import FootprintTimelineRecorder
from engine.modes.base import ModeProcessor
from engine.modes.treadmill_accumulator import TreadmillAccumulator
from engine.modes.treadmill_accumulator import belt_speed_m_s
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from engine.modes.treadmill_running_accumulator import TreadmillRunningAccumulator
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
        self._visual_recorder = FootprintTimelineRecorder()
        self._last_clusters = []

    # ---- ModeProcessor interface ----

    def reset(self) -> None:
        """Reset all internal state."""
        self.lift_count = 0
        self._cluster_tracker = ClusterTracker()
        self._contact_tracker.reset()
        self._accumulator = self._make_accumulator()
        self._visual_recorder.reset()
        self._last_clusters = []

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
        self._last_clusters = clusters

        # 2. Update cluster tracker
        self._cluster_tracker.update(rel_time, clusters)

        # 3. Feed active tracks into contact-based gait tracker
        active_tracks = self._cluster_tracker.get_active_tracks_view()
        events = self._contact_tracker.process_frame(rel_time, active_tracks)
        self._visual_recorder.record_if_due(
            rel_time,
            contact_bits,
            self._contact_tracker,
        )

        # 4. Delegate touch/lift events to accumulator
        for ev in events:
            self._handle_step_event(ev, rel_time)

        return events

    def pop_visual_frames(self):
        return self._visual_recorder.pop_pending()

    def make_status_snapshot(self, rel_time: float) -> dict:
        ct = self._contact_tracker
        active_count = len(ct.foot_contact_queue)
        if active_count == 0:
            status = "腾空 / 离地"
        elif active_count == 1:
            status = "单脚支撑"
        else:
            status = f"多支撑 ({active_count}脚)"

        active_centroids = []
        for cid in ct.foot_contact_queue:
            if cid in ct.active_contacts:
                centroid = ct.active_contacts[cid].latest_centroid
                if centroid is not None:
                    active_centroids.append(centroid)

        valid_rows = [
            row
            for row in self._accumulator.rows
            if row.is_event_valid and row.is_included_in_statistics
        ]
        step_lengths = [
            row.step_length_cm
            for row in valid_rows
            if row.step_length_cm is not None
        ]
        speed_cm_s = [
            row.speed_m_s * 100.0
            for row in valid_rows
            if row.speed_m_s is not None
        ]
        if not speed_cm_s:
            speed_cm_s = [belt_speed_m_s(self._config) * 100.0]

        support_by_side: dict[str, list[float]] = {"left": [], "right": []}
        for row in valid_rows:
            if row.side in support_by_side and row.contact_time_s is not None:
                support_by_side[row.side].append(row.contact_time_s)

        latest_extra_metrics = {}
        left_support = support_by_side["left"]
        right_support = support_by_side["right"]
        if left_support and right_support:
            left_avg = sum(left_support) / len(left_support)
            right_avg = sum(right_support) / len(right_support)
            denom = max((left_avg + right_avg) / 2.0, 1e-6)
            latest_extra_metrics["imbalance_index"] = (
                abs(left_avg - right_avg) / denom * 100.0
            )

        return {
            "timestamp": rel_time,
            "status": status,
            "cluster_count": len(self._last_clusters),
            "active_centroids": active_centroids,
            "touch_count": ct.touch_count,
            "lift_count": self.lift_count,
            "stride_count": len(step_lengths),
            "stride_sum": sum(step_lengths),
            "latest_stride": step_lengths[-1] if step_lengths else None,
            "velocity_count": len(speed_cm_s),
            "velocity_sum": sum(speed_cm_s),
            "latest_velocity": speed_cm_s[-1] if speed_cm_s else None,
            "foot_a_support_times": list(support_by_side["left"]),
            "foot_b_support_times": list(support_by_side["right"]),
            "latest_extra_metrics": latest_extra_metrics,
        }

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
            visual_timeline=self._visual_recorder.frames,
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

        # Determine side from foot_label: "A" -> "left", "B" -> "right"
        # (or vice-versa depending on direction; for simplicity map A=left)
        side = "left"
        if ev.contact.foot_label == "B":
            side = "right"
        elif ev.contact.foot_label is None:
            side = "unknown"

        centroid_cm = ev.contact.centroid_at_touch or ev.contact.latest_centroid or 0.0

        # Heel/toe derived from centroid + foot-length offset.
        # For "Interface side", heel is left of centroid, toe is right.
        # (LED index increases left-to-right at the interface.)
        if self._direction == "Interface side":
            heel_cm = centroid_cm - self._heel_offset_cm
            toe_cm = centroid_cm + self._toe_offset_cm
        else:
            # Opposite side: reversed perspective
            heel_cm = centroid_cm + self._heel_offset_cm
            toe_cm = centroid_cm - self._toe_offset_cm

        if ev.kind == "touch":
            self._accumulator.record_touch(
                time_s=rel_time, side=side, heel_cm=heel_cm, toe_cm=toe_cm
            )
        elif ev.kind == "lift":
            self.lift_count += 1
            self._accumulator.record_lift(time_s=rel_time, side=side)


__all__ = ["TreadmillProcessor"]
