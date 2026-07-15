"""Pure data contracts and event-level left/right foot classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median
from typing import Iterable, Sequence


class FootLabel(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VisionConfig:
    pre_event_ms: int = 120
    post_event_ms: int = 80
    inference_interval_ms: int = 33
    decision_timeout_ms: int = 200
    min_confidence: float = 0.90
    min_landmark_quality: float = 0.65
    frame_buffer_ms: int = 1200
    max_frames: int = 120
    max_events: int = 32

    def __post_init__(self) -> None:
        if self.pre_event_ms < 0:
            raise ValueError("pre_event_ms must be non-negative")
        if self.post_event_ms < 0:
            raise ValueError("post_event_ms must be non-negative")
        if self.inference_interval_ms <= 0:
            raise ValueError("inference_interval_ms must be positive")
        if self.decision_timeout_ms <= 0:
            raise ValueError("decision_timeout_ms must be positive")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0.0 <= self.min_landmark_quality <= 1.0:
            raise ValueError("min_landmark_quality must be between 0 and 1")
        if self.frame_buffer_ms <= 0:
            raise ValueError("frame_buffer_ms must be positive")
        if self.max_frames <= 0:
            raise ValueError("max_frames must be positive")
        if self.max_events <= 0:
            raise ValueError("max_events must be positive")


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float
    visibility: float
    presence: float

    @property
    def quality(self) -> float:
        return min(self.visibility, self.presence)


@dataclass(frozen=True)
class FootPoseSample:
    timestamp_s: float
    left_hip: Landmark
    left_knee: Landmark
    left_ankle: Landmark
    left_heel: Landmark
    left_foot_index: Landmark
    right_hip: Landmark
    right_knee: Landmark
    right_ankle: Landmark
    right_heel: Landmark
    right_foot_index: Landmark

    def landmarks(self) -> tuple[Landmark, ...]:
        return (
            self.left_hip,
            self.left_knee,
            self.left_ankle,
            self.left_heel,
            self.left_foot_index,
            self.right_hip,
            self.right_knee,
            self.right_ankle,
            self.right_heel,
            self.right_foot_index,
        )

    def foot_y(self, side: FootLabel) -> float:
        if side is FootLabel.LEFT:
            points = (self.left_ankle, self.left_heel, self.left_foot_index)
        elif side is FootLabel.RIGHT:
            points = (self.right_ankle, self.right_heel, self.right_foot_index)
        else:
            raise ValueError("foot_y requires left or right")
        return median(point.y for point in points)


@dataclass(frozen=True)
class FrameSample:
    captured_at_s: float
    frame: object


@dataclass(frozen=True)
class TouchEvent:
    event_id: int
    event_time_s: float
    submitted_at_s: float


@dataclass(frozen=True)
class VisionDecision:
    event_id: int
    label: FootLabel
    confidence: float
    reason: str
    event_time_s: float
    decided_at_s: float | None = None
    candidate_label: FootLabel | None = None


_BOTH_MARGIN = 0.04
_SINGLE_MARGIN = 0.08
_MAX_STABLE_RANGE = 0.04
_CONSISTENCY_RATIO = 0.80


def unknown_decision(
    event_id: int,
    event_time_s: float,
    reason: str,
    *,
    decided_at_s: float | None = None,
) -> VisionDecision:
    return VisionDecision(
        event_id=event_id,
        label=FootLabel.UNKNOWN,
        confidence=0.0,
        reason=reason,
        event_time_s=event_time_s,
        decided_at_s=decided_at_s,
    )


def classify_event(
    event_id: int,
    event_time_s: float,
    samples: Sequence[FootPoseSample],
    config: VisionConfig | None = None,
) -> VisionDecision:
    """Classify a pose window conservatively.

    Image ``y`` grows downwards. The lower, stable foot is therefore the
    contact candidate. This is a deliberately rejectable first-pass heuristic;
    its thresholds must be validated with the target camera positions.
    """

    cfg = config or VisionConfig()
    if not samples:
        return unknown_decision(event_id, event_time_s, "no_pose_samples")

    ordered = sorted(samples, key=lambda sample: sample.timestamp_s)
    qualities = [min(point.quality for point in sample.landmarks()) for sample in ordered]
    if median(qualities) < cfg.min_landmark_quality:
        return unknown_decision(event_id, event_time_s, "landmarks_not_visible")
    if len(ordered) < 2:
        return unknown_decision(event_id, event_time_s, "insufficient_pose_samples")

    left_y = [sample.foot_y(FootLabel.LEFT) for sample in ordered]
    right_y = [sample.foot_y(FootLabel.RIGHT) for sample in ordered]
    frame_labels = [_label_from_difference(left - right) for left, right in zip(left_y, right_y)]
    label, ratio = _dominant_label(frame_labels)
    if label is FootLabel.UNKNOWN or ratio < _CONSISTENCY_RATIO:
        return unknown_decision(event_id, event_time_s, "window_inconsistent")
    if label is FootLabel.BOTH:
        stable = (
            _value_range(left_y) <= _MAX_STABLE_RANGE
            and _value_range(right_y) <= _MAX_STABLE_RANGE
        )
    elif label is FootLabel.LEFT:
        stable = _value_range(left_y) <= _MAX_STABLE_RANGE
    else:
        stable = _value_range(right_y) <= _MAX_STABLE_RANGE
    if not stable:
        return unknown_decision(event_id, event_time_s, "contact_foot_not_stable")

    difference = abs(median(left_y) - median(right_y))
    quality = median(qualities)
    if label is FootLabel.BOTH:
        geometry = max(0.0, 1.0 - difference / _BOTH_MARGIN)
        reason = "both_feet_level_and_stable"
    else:
        geometry = min(1.0, difference / 0.15)
        reason = f"{label.value}_foot_lower_and_stable"
    confidence = min(1.0, quality * 0.6 + geometry * 0.3 + ratio * 0.1)
    if confidence < cfg.min_confidence:
        return VisionDecision(
            event_id=event_id,
            label=FootLabel.UNKNOWN,
            confidence=confidence,
            reason="confidence_below_threshold",
            event_time_s=event_time_s,
            candidate_label=label,
        )
    return VisionDecision(event_id, label, confidence, reason, event_time_s)


def _label_from_difference(difference: float) -> FootLabel:
    if abs(difference) <= _BOTH_MARGIN:
        return FootLabel.BOTH
    if difference >= _SINGLE_MARGIN:
        return FootLabel.LEFT
    if difference <= -_SINGLE_MARGIN:
        return FootLabel.RIGHT
    return FootLabel.UNKNOWN


def _dominant_label(labels: Iterable[FootLabel]) -> tuple[FootLabel, float]:
    values = list(labels)
    if not values:
        return FootLabel.UNKNOWN, 0.0
    counts = {label: values.count(label) for label in FootLabel}
    label = max(counts, key=counts.get)  # type: ignore[arg-type]
    return label, counts[label] / len(values)


def _value_range(values: Sequence[float]) -> float:
    return max(values) - min(values) if values else 0.0
