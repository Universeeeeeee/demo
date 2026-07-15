"""Independent visual foot-reference package."""

from .foot_reference import (
    FootLabel,
    VisionConfig,
    VisionDecision,
)
from .mediapipe_pose import VisionInferenceError, VisionUnavailableError
from .service import FootVisionService

__all__ = [
    "FootLabel",
    "FootVisionService",
    "VisionConfig",
    "VisionDecision",
    "VisionInferenceError",
    "VisionUnavailableError",
]
