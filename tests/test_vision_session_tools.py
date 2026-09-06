from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from vision.annotations import (
    first_unannotated_index,
    load_annotations,
    save_annotations,
    set_annotation,
)
from vision.foot_reference import FootLabel, Landmark, VisionDecision
from vision.replay import (
    metrics_for_rows,
    replay_phase_resync,
    replay_session,
    run_phase_slip_injections,
    write_replay_outputs,
)
from vision.session import CONTACT_FIELDS, VisionSessionRecorder, make_session_id


def _pose_record(timestamp_s: float) -> dict:
    landmarks = [
        {
            "x": 0.5,
            "y": 0.5,
            "z": 0.0,
            "visibility": 0.99,
            "presence": 0.99,
        }
        for _ in range(33)
    ]
    return {
        "frame_index": int(timestamp_s * 1000),
        "camera_sample_timestamp": timestamp_s - 10.0,
        "perf_counter_timestamp": timestamp_s,
        "inference_start_timestamp": timestamp_s + 0.001,
        "inference_end_timestamp": timestamp_s + 0.011,
        "inference_latency_ms": 10.0,
        "pose_available": True,
        "landmarks": landmarks,
        "error": None,
    }


def _contact(event_id: int, timestamp_s: float, scenario: str = "normal") -> dict:
    return {
        "event_id": event_id,
        "contact_timestamp": timestamp_s,
        "visual_label": "Unknown",
        "visual_raw_label": "unknown",
        "visual_raw_score": 0.0,
        "reject_reason": "insufficient_pose_samples",
        "sync_state": "ready",
        "classifier_version": "landing_v1",
        "classifier_entrypoint": "vision.foot_reference.classify_landing_event",
        "project_mode": "treadmill-gait",
        "event_role": "grid_touch",
        "valid_for_benchmark": "1",
        "scenario": scenario,
    }


class VisionSessionRecorderTests(unittest.TestCase):
    def test_contact_schema_keeps_raw_effective_and_phase_provenance(self):
        for field in (
            "raw_device_symbol",
            "raw_device_label",
            "effective_device_label",
            "final_label",
            "phase_offset",
            "phase_epoch",
            "phase_action",
            "phase_flip_start_event_id",
            "phase_flip_confirm_event_id",
        ):
            self.assertIn(field, CONTACT_FIELDS)

    def test_session_id_avoids_existing_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "20260809_001").mkdir()
            (root / "20260809_003").mkdir()
            self.assertEqual(
                make_session_id(root, datetime(2026, 8, 9)),
                "20260809_004",
            )

    def test_recorder_writes_pose_contact_annotations_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = VisionSessionRecorder(
                temporary,
                session_id="20260809_001",
                metadata={"scenario": "random"},
            )
            initial_metadata = json.loads(recorder.paths.session_json.read_text())
            self.assertEqual(initial_metadata["status"], "recording")
            recorder.record_pose(_pose_record(100.0))
            recorder.record_contact(_contact(1, 100.0, "random"))
            recorder.close(
                recording={
                    "status": "partial",
                    "written": 10,
                    "dropped": 2,
                    "queue_peak": 4,
                    "errors": ["dropped frames"],
                }
            )

            self.assertTrue(recorder.paths.pose_frames.exists())
            self.assertTrue(recorder.paths.contact_events.exists())
            self.assertTrue(recorder.paths.annotations.exists())
            metadata = json.loads(recorder.paths.session_json.read_text())
            self.assertEqual(metadata["status"], "partial")
            self.assertEqual(metadata["recording"]["status"], "partial")
            self.assertEqual(metadata["writers"]["pose"]["written"], 1)
            self.assertEqual(metadata["writers"]["contact"]["written"], 1)
            self.assertEqual(metadata["writers"]["video"]["dropped"], 2)

    def test_clean_native_recording_marks_session_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = VisionSessionRecorder(
                temporary,
                session_id="20260809_001",
            )
            recorder.close(
                recording={
                    "status": "complete",
                    "written": 100,
                    "dropped": 0,
                    "queue_peak": 3,
                    "errors": [],
                }
            )
            metadata = json.loads(recorder.paths.session_json.read_text())
            self.assertEqual(metadata["status"], "complete")


class AnnotationPersistenceTests(unittest.TestCase):
    def test_skip_is_invalid_and_resume_selects_first_unannotated_benchmark(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "annotations.csv"
            annotations = {}
            set_annotation(annotations, 1, "Left", scenario="normal")
            set_annotation(annotations, 2, "Skip", scenario="occlusion")
            save_annotations(path, annotations)
            loaded = load_annotations(path)

            self.assertEqual(loaded["2"]["ground_truth"], "Skip")
            self.assertEqual(loaded["2"]["valid"], "0")
            events = [
                {"event_id": "1", "valid_for_benchmark": "1"},
                {"event_id": "2", "valid_for_benchmark": "1"},
                {"event_id": "3", "valid_for_benchmark": "0"},
                {"event_id": "4", "valid_for_benchmark": "1"},
            ]
            self.assertEqual(first_unannotated_index(events, loaded), 3)


class ReplayTests(unittest.TestCase):
    def test_phase_replay_injection_requires_opposite_device_pair(self):
        events = [
            {"event_id": "1", "raw_device_label": "left", "visual_label": "Left"},
            {"event_id": "2", "raw_device_label": "right", "visual_label": "Right"},
            {"event_id": "3", "raw_device_label": "left", "visual_label": "Left"},
            {"event_id": "4", "raw_device_label": "right", "visual_label": "Right"},
        ]
        summary, rows = replay_phase_resync(events, inject_phase_slip_at=3)

        self.assertTrue(summary["phase_slip_recovered"])
        self.assertEqual(summary["recovery_contact_count"], 2)
        self.assertEqual(summary["automatic_phase_flips"], 1)
        self.assertEqual(rows[-1]["phase_action"], "auto_flip")

    def test_phase_replay_same_device_mismatches_do_not_flip(self):
        events = [
            {"event_id": "1", "raw_device_label": "left", "visual_label": "Right"},
            {"event_id": "2", "raw_device_label": "left", "visual_label": "Right"},
        ]
        summary, _rows = replay_phase_resync(events)

        self.assertEqual(summary["automatic_phase_flips"], 0)

    def test_random_phase_injections_are_deterministic_and_non_mutating(self):
        events = [
            {"event_id": str(index), "raw_device_label": side, "visual_label": side.title()}
            for index, side in enumerate(
                ("left", "right", "left", "right", "left", "right"), start=1
            )
        ]
        original = [dict(event) for event in events]
        summary = run_phase_slip_injections(events, count=10, seed=7)
        repeated = run_phase_slip_injections(events, count=10, seed=7)

        self.assertEqual(summary, repeated)
        self.assertEqual(events, original)
        self.assertGreater(summary["recoverable_injections"], 0)
        self.assertEqual(summary["phase_slip_recovery_rate"], 1.0)

    def test_metrics_include_coverage_accepted_error_and_wrong_ids(self):
        rows = [
            {"event_id": "1", "ground_truth": "Left", "prediction": "Left", "accepted": "1", "correct": "1", "high_confidence_wrong": "0"},
            {"event_id": "2", "ground_truth": "Right", "prediction": "Left", "accepted": "1", "correct": "0", "high_confidence_wrong": "1"},
            {"event_id": "3", "ground_truth": "Left", "prediction": "Unknown", "accepted": "0", "correct": "0", "high_confidence_wrong": "0"},
        ]
        metrics = metrics_for_rows(rows)
        self.assertEqual(metrics["correct"], 1)
        self.assertEqual(metrics["wrong"], 1)
        self.assertEqual(metrics["unknown"], 1)
        self.assertAlmostEqual(metrics["accuracy"], 1 / 3)
        self.assertAlmostEqual(metrics["accepted_accuracy"], 1 / 2)
        self.assertAlmostEqual(metrics["coverage"], 2 / 3)
        self.assertEqual(metrics["high_confidence_wrong_count"], 1)
        self.assertEqual(metrics["wrong_event_ids"], ["2"])

    def test_replay_uses_saved_pose_without_camera_or_mediapipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = VisionSessionRecorder(
                temporary,
                session_id="20260809_001",
                metadata={"scenario": "random"},
            )
            for timestamp in (99.8, 99.95, 100.05, 100.15, 100.8, 100.95, 101.05, 101.15):
                recorder.record_pose(_pose_record(timestamp))
            recorder.record_contact(_contact(1, 100.0, "normal"))
            recorder.record_contact(_contact(2, 101.0, "cross_leg"))
            excluded = _contact(3, 101.0, "normal")
            excluded["event_role"] = "initial_touch"
            excluded["valid_for_benchmark"] = "0"
            recorder.record_contact(excluded)
            recorder.close()
            annotations = {}
            set_annotation(annotations, 1, "Left", scenario="normal")
            set_annotation(annotations, 2, "Right", scenario="cross_leg")
            set_annotation(annotations, 3, "Left", scenario="normal")
            save_annotations(recorder.paths.annotations, annotations)

            def classifier(event_id, event_time_s, samples, config):
                self.assertEqual(config.pre_event_ms, 250)
                self.assertEqual(config.post_event_ms, 200)
                self.assertGreaterEqual(len(samples), 4)
                label = FootLabel.LEFT
                return VisionDecision(event_id, label, 0.95, "synthetic", event_time_s)

            summary, rows = replay_session(recorder.session_root, classifier=classifier)
            self.assertEqual(summary["total_events"], 2)
            self.assertEqual(summary["correct"], 1)
            self.assertEqual(summary["wrong"], 1)
            self.assertEqual(summary["scenarios"]["cross_leg"]["wrong"], 1)
            self.assertIn("replay_time", summary)
            self.assertIn("git_commit", summary)
            self.assertIn("git_dirty", summary)

            summary_path, events_path = write_replay_outputs(
                recorder.session_root, summary, rows
            )
            self.assertTrue(summary_path.exists())
            with events_path.open(newline="", encoding="utf-8") as file:
                self.assertEqual(len(list(csv.DictReader(file))), 2)


if __name__ == "__main__":
    unittest.main()
