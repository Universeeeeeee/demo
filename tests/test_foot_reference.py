import unittest

from vision.foot_reference import (
    FootLabel,
    FootPoseSample,
    Landmark,
    VisionConfig,
    classify_event,
)


def _landmark(y: float, visibility: float = 0.99) -> Landmark:
    return Landmark(x=0.5, y=y, z=0.0, visibility=visibility, presence=visibility)


def _sample(
    timestamp_s: float,
    *,
    left_y: float,
    right_y: float,
    visibility: float = 0.99,
) -> FootPoseSample:
    left = _landmark(left_y, visibility)
    right = _landmark(right_y, visibility)
    return FootPoseSample(
        timestamp_s=timestamp_s,
        left_hip=left,
        left_knee=left,
        left_ankle=left,
        left_heel=left,
        left_foot_index=left,
        right_hip=right,
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


if __name__ == "__main__":
    unittest.main()
