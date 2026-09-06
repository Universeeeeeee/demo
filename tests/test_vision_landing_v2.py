from __future__ import annotations

import math

import pytest

from vision.foot_reference import FootLabel, FootPoseSample, Landmark
from vision.landing_v2 import (
    LandingV2Classifier,
    TreadmillAxisCalibration,
    classify_landing_v2,
)


def _point(x: float, y: float, quality: float = 0.99) -> Landmark:
    return Landmark(x, y, 0.0, quality, quality)


def _sample(timestamp: float, left_x: float, right_x: float) -> FootPoseSample:
    return FootPoseSample(
        timestamp_s=timestamp,
        left_hip=_point(0.45, 0.35),
        left_knee=_point((0.45 + left_x) / 2, 0.60),
        left_ankle=_point(left_x, 0.85),
        left_heel=_point(left_x - 0.01, 0.86),
        left_foot_index=_point(left_x + 0.02, 0.86),
        right_hip=_point(0.55, 0.35),
        right_knee=_point((0.55 + right_x) / 2, 0.60),
        right_ankle=_point(right_x, 0.85),
        right_heel=_point(right_x - 0.01, 0.86),
        right_foot_index=_point(right_x + 0.02, 0.86),
    )


def _calibration() -> TreadmillAxisCalibration:
    return TreadmillAxisCalibration.create((0.1, 0.8), (0.9, 0.8), (0.0, 1.0))


def test_calibration_normalizes_basis_and_solves_non_orthogonal_coordinates():
    calibration = TreadmillAxisCalibration.create(
        (0.1, 0.8), (0.9, 0.7), (0.2, 1.0)
    )
    longitudinal, vertical = calibration.solve(calibration.forward_axis_unit)

    assert math.hypot(*calibration.forward_axis_unit) == pytest.approx(1.0)
    assert math.hypot(*calibration.vertical_axis_unit) == pytest.approx(1.0)
    assert longitudinal == pytest.approx(1.0)
    assert vertical == pytest.approx(0.0)


def test_calibration_rejects_degenerate_basis():
    with pytest.raises(ValueError, match="calibration_basis_degenerate"):
        TreadmillAxisCalibration.create((0.1, 0.1), (0.9, 0.1), (1.0, 0.1))


def test_resolution_change_invalidates_cached_axis_points():
    classifier = LandingV2Classifier((0.1, 0.8), (0.9, 0.8))
    assert classifier.axis_points is not None
    assert classifier.set_frame_geometry(1280, 720)
    assert classifier.axis_points is None


def test_v2_selects_side_whose_forward_peak_turns_backward_at_contact():
    timestamps = (-0.24, -0.12, -0.005, 0.04, 0.12, 0.19)
    left = (0.42, 0.50, 0.56, 0.53, 0.47, 0.40)
    right = (0.60, 0.61, 0.62, 0.63, 0.64, 0.65)
    samples = [_sample(t, lx, rx) for t, lx, rx in zip(timestamps, left, right)]

    decision = classify_landing_v2(1, 0.0, samples, _calibration())

    assert decision.label is FootLabel.LEFT
    assert decision.left_evidence is not None
    assert decision.right_evidence is not None
    assert decision.left_evidence > decision.right_evidence
    assert decision.classifier_diagnostics["left_post_velocity"] < 0


def test_v2_rejects_low_quality_side_instead_of_single_side_correction():
    samples = [_sample(t, 0.5, 0.60) for t in (-0.18, -0.08, 0.04, 0.14)]
    samples = [
        FootPoseSample(
            **{**sample.__dict__, "right_ankle": _point(0.60, 0.85, 0.2)}
        )
        for sample in samples
    ]

    decision = classify_landing_v2(1, 0.0, samples, _calibration())

    assert decision.label is FootLabel.UNKNOWN
    assert decision.reason == "landmarks_not_visible"
