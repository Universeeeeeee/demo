import unittest

from vision.foot_reference import (
    FootLabel,
    FootPoseSample,
    Landmark,
    VisionConfig,
    classify_event,
    classify_landing_event,
)


def _landmark(y: float, visibility: float = 0.99) -> Landmark:
    return Landmark(x=0.5, y=y, z=0.0, visibility=visibility, presence=visibility)


def _sample(
    timestamp_s: float,
    *,
    left_y: float,
    right_y: float,
    visibility: float = 0.99,
    left_hip_y: float = 0.40,
    right_hip_y: float = 0.40,
) -> FootPoseSample:
    left = _landmark(left_y, visibility)
    right = _landmark(right_y, visibility)
    left_hip = _landmark(left_hip_y, visibility)
    right_hip = _landmark(right_hip_y, visibility)
    return FootPoseSample(
        timestamp_s=timestamp_s,
        left_hip=left_hip,
        left_knee=left,
        left_ankle=left,
        left_heel=left,
        left_foot_index=left,
        right_hip=right_hip,
        right_knee=right,
        right_ankle=right,
        right_heel=right,
        right_foot_index=right,
    )


class FootReferenceTests(unittest.TestCase):
    def test_vision_config_rejects_impossible_windows(self):
        with self.assertRaisesRegex(ValueError, "pre_event_ms"):
            VisionConfig(pre_event_ms=-1)
        with self.assertRaisesRegex(ValueError, "inference_interval_ms"):
            VisionConfig(inference_interval_ms=0)
        with self.assertRaisesRegex(ValueError, "min_confidence"):
            VisionConfig(min_confidence=1.1)

    def test_classifier_rejects_low_visibility(self):
        samples = [_sample(1.25, left_y=0.9, right_y=0.7, visibility=0.2)]

        result = classify_event(7, 1.25, samples)

        self.assertIs(result.label, FootLabel.UNKNOWN)
        self.assertEqual(result.reason, "landmarks_not_visible")

    def test_classifier_labels_stable_lower_left_foot(self):
        samples = [
            _sample(1.20, left_y=0.91, right_y=0.72),
            _sample(1.24, left_y=0.91, right_y=0.71),
            _sample(1.28, left_y=0.90, right_y=0.72),
        ]

        result = classify_event(3, 1.25, samples)

        self.assertIs(result.label, FootLabel.LEFT)
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertEqual(result.reason, "left_foot_lower_and_stable")

    def test_classifier_labels_stable_lower_right_foot(self):
        samples = [
            _sample(2.20, left_y=0.70, right_y=0.91),
            _sample(2.24, left_y=0.71, right_y=0.91),
            _sample(2.28, left_y=0.70, right_y=0.90),
        ]

        result = classify_event(4, 2.25, samples)

        self.assertIs(result.label, FootLabel.RIGHT)
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_classifier_allows_swing_foot_to_move_when_left_is_stable(self):
        samples = [
            _sample(2.20, left_y=0.91, right_y=0.68),
            _sample(2.24, left_y=0.91, right_y=0.58),
            _sample(2.28, left_y=0.90, right_y=0.70),
        ]

        result = classify_event(10, 2.25, samples)

        self.assertIs(result.label, FootLabel.LEFT)
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_low_confidence_rejection_preserves_candidate_and_raw_score(self):
        samples = [
            _sample(2.20, left_y=0.82, right_y=0.72, visibility=0.70),
            _sample(2.24, left_y=0.82, right_y=0.72, visibility=0.70),
            _sample(2.28, left_y=0.82, right_y=0.72, visibility=0.70),
        ]

        result = classify_event(11, 2.25, samples)

        self.assertIs(result.label, FootLabel.UNKNOWN)
        self.assertIs(result.candidate_label, FootLabel.LEFT)
        self.assertGreater(result.confidence, 0.0)
        self.assertEqual(result.reason, "confidence_below_threshold")

    def test_live_reference_threshold_accepts_moderate_left_candidate(self):
        samples = [
            _sample(2.20, left_y=0.82, right_y=0.72, visibility=0.70),
            _sample(2.24, left_y=0.82, right_y=0.72, visibility=0.70),
            _sample(2.28, left_y=0.82, right_y=0.72, visibility=0.70),
        ]

        result = classify_event(
            12,
            2.25,
            samples,
            VisionConfig(min_confidence=0.65),
        )

        self.assertIs(result.label, FootLabel.LEFT)

    def test_classifier_labels_two_level_stable_feet_as_both(self):
        samples = [
            _sample(3.20, left_y=0.90, right_y=0.89),
            _sample(3.24, left_y=0.90, right_y=0.90),
            _sample(3.28, left_y=0.89, right_y=0.90),
        ]

        result = classify_event(5, 3.25, samples)

        self.assertIs(result.label, FootLabel.BOTH)
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertEqual(result.reason, "both_feet_level_and_stable")

    def test_classifier_rejects_window_with_inconsistent_lower_foot(self):
        samples = [
            _sample(4.20, left_y=0.91, right_y=0.70),
            _sample(4.24, left_y=0.70, right_y=0.91),
            _sample(4.28, left_y=0.91, right_y=0.70),
        ]

        result = classify_event(6, 4.25, samples)

        self.assertIs(result.label, FootLabel.UNKNOWN)
        self.assertEqual(result.reason, "window_inconsistent")

    def test_landing_classifier_chooses_descending_left_not_lower_stance_foot(self):
        samples = [
            _sample(0.82, left_y=0.58, right_y=0.84),
            _sample(0.90, left_y=0.68, right_y=0.84),
            _sample(1.00, left_y=0.82, right_y=0.84),
            _sample(1.06, left_y=0.83, right_y=0.84),
            _sample(1.10, left_y=0.83, right_y=0.84),
        ]

        result = classify_landing_event(
            21,
            1.0,
            samples,
            VisionConfig(min_confidence=0.65),
        )

        self.assertIs(result.label, FootLabel.LEFT)
        self.assertEqual(result.reason, "left_foot_descended_and_settled")

    def test_landing_classifier_chooses_descending_right(self):
        samples = [
            _sample(1.82, left_y=0.84, right_y=0.58),
            _sample(1.90, left_y=0.84, right_y=0.68),
            _sample(2.00, left_y=0.84, right_y=0.82),
            _sample(2.06, left_y=0.84, right_y=0.83),
            _sample(2.10, left_y=0.84, right_y=0.83),
        ]

        result = classify_landing_event(
            22,
            2.0,
            samples,
            VisionConfig(min_confidence=0.65),
        )

        self.assertIs(result.label, FootLabel.RIGHT)

    def test_landing_classifier_supports_both_feet(self):
        samples = [
            _sample(2.82, left_y=0.58, right_y=0.59),
            _sample(2.90, left_y=0.68, right_y=0.69),
            _sample(3.00, left_y=0.82, right_y=0.83),
            _sample(3.06, left_y=0.83, right_y=0.84),
            _sample(3.10, left_y=0.83, right_y=0.84),
        ]

        result = classify_landing_event(
            23,
            3.0,
            samples,
            VisionConfig(min_confidence=0.65),
        )

        self.assertIs(result.label, FootLabel.BOTH)
        self.assertEqual(result.reason, "both_feet_descended_and_settled")

    def test_landing_classifier_rejects_two_stationary_visible_feet(self):
        samples = [
            _sample(3.82, left_y=0.83, right_y=0.84),
            _sample(3.90, left_y=0.83, right_y=0.84),
            _sample(4.00, left_y=0.83, right_y=0.84),
            _sample(4.06, left_y=0.83, right_y=0.84),
        ]

        result = classify_landing_event(
            24,
            4.0,
            samples,
            VisionConfig(min_confidence=0.65),
        )

        self.assertIs(result.label, FootLabel.UNKNOWN)
        self.assertEqual(result.reason, "no_landing_motion")

    def test_landing_classifier_ignores_whole_body_vertical_translation(self):
        samples = [
            _sample(
                4.82,
                left_y=0.70,
                right_y=0.72,
                left_hip_y=0.30,
                right_hip_y=0.32,
            ),
            _sample(
                4.90,
                left_y=0.78,
                right_y=0.80,
                left_hip_y=0.38,
                right_hip_y=0.40,
            ),
            _sample(
                5.00,
                left_y=0.86,
                right_y=0.88,
                left_hip_y=0.46,
                right_hip_y=0.48,
            ),
            _sample(
                5.06,
                left_y=0.86,
                right_y=0.88,
                left_hip_y=0.46,
                right_hip_y=0.48,
            ),
        ]

        result = classify_landing_event(
            25,
            5.0,
            samples,
            VisionConfig(min_confidence=0.65),
        )

        self.assertIs(result.label, FootLabel.UNKNOWN)
        self.assertEqual(result.reason, "no_landing_motion")


if __name__ == "__main__":
    unittest.main()
