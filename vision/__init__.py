"""Independent visual foot-reference package."""

from .foot_reference import (
    FootLabel,
    VisionConfig,
    VisionDecision,
    VisionWindowDiagnostics,
)
from .mediapipe_pose import VisionInferenceError, VisionUnavailableError
from .service import FootVisionService
from .time_sync import CameraClockSynchronizer, ClockSyncSnapshot, ClockSyncStatus

__all__ = [
    "FootLabel",
    "FootVisionService",
    "CameraClockSynchronizer",
    "ClockSyncSnapshot",
    "ClockSyncStatus",
    "VisionConfig",
    "VisionDecision",
    "VisionWindowDiagnostics",
    "VisionInferenceError",
    "VisionUnavailableError",
]
