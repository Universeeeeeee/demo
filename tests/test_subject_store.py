"""Tests for the SQLite subject store MVP."""

import sys
import tempfile
import unittest
from dataclasses import fields
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.models import AthleteProfile
from config.test_config import TestConfig as _TestConfig
from config.test_report import JumpTestReport
from config.treadmill_config import TreadmillGaitConfig
from config.treadmill_report import (
    GaitBoundaryPartial,
    GaitCycleRecord,
    GaitEventRecord,
    TreadmillGaitReport,
    TreadmillStepResult,
    summarize,
)
from data.subject_store import SubjectProfile, SubjectStore


def _jump_report(**overrides):
    values = {
        "touch_count": 5,
        "lift_count": 5,
        "air_times": (0.4, 0.42),
        "contact_times": (0.2, 0.21),
        "cycle_times": (0.6, 0.63),
        "avg_jump_height": 0.2,
        "max_jump_height": 0.22,
        "avg_air_time": 0.41,
        "max_air_time": 0.42,
        "avg_contact_time": 0.205,
        "avg_cadence": 95.0,
        "finish_reason": "jump_count_reached",
        "jump_heights": (0.18, 0.22),
        "cadences": (92.0, 98.0),
        "min_jump_height": 0.18,
        "std_jump_height": 0.02,
        "min_air_time": 0.4,
        "std_air_time": 0.01,
        "min_contact_time": 0.2,
        "max_contact_time": 0.21,
        "std_contact_time": 0.005,
        "export_frames": ([1, 0, 1],),
        "export_timestamps": (1.0,),
    }
    values.update(overrides)
    return JumpTestReport(**values)


class SubjectStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "iron_jump.sqlite3"
        self.store = SubjectStore(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_schema_uses_level_and_focus_side_only(self):
        with self.store._connect() as conn:
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(subjects)").fetchall()
            }
        self.assertIn("level", cols)
        self.assertIn("focus_side", cols)
        self.assertNotIn("condition", cols)
        self.assertNotIn("affected_side", cols)

        profile_fields = {field.name for field in fields(SubjectProfile)}
        self.assertIn("level", profile_fields)
        self.assertIn("focus_side", profile_fields)
        self.assertNotIn("condition", profile_fields)
        self.assertNotIn("affected_side", profile_fields)

    def test_create_subject_defaults_level_to_intermediate(self):
        subject_id = self.store.create_subject("Alice", 1990)
        subject = self.store.get_subject(subject_id)
        self.assertIsNotNone(subject)
        self.assertEqual(subject.level, "intermediate")
        self.assertEqual(subject.focus_side, "")

    def test_search_subjects_returns_display_labels(self):
        subject_id = self.store.create_subject(
            "Alice", 1990, level="beginner", focus_side="left"
        )
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=5),
            _jump_report(),
            started_at="2026-05-14 10:00:00",
        )

        results = self.store.search_subjects("Ali")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].subject.id, subject_id)
        self.assertEqual(results[0].display_labels["Level"], "beginner")
        self.assertEqual(results[0].display_labels["Focus"], "left")
        self.assertEqual(results[0].display_labels["Last test"], "2026-05-14")

    def test_subject_to_athlete_profile_uses_new_fields(self):
        subject_id = self.store.create_subject(
            "Bob",
            2000,
            height_cm=180,
            weight_kg=75,
            level="advanced",
            focus_side="right",
        )
        subject = self.store.get_subject(subject_id)
        profile = self.store.subject_to_athlete_profile(subject, recent_sessions=[])

        self.assertIsInstance(profile, AthleteProfile)
        self.assertEqual(profile.age, datetime.now().year - 2000)
        self.assertEqual(profile.height, 180)
        self.assertEqual(profile.weight, 75)
        self.assertEqual(profile.level, "advanced")
        self.assertEqual(profile.focus_side, "right")

    def test_record_session_round_trips_config_and_summary(self):
        subject_id = self.store.create_subject("Carol", 1995)
        config = _TestConfig(number_of_jumps=7, min_contact_time=80)
        report = _jump_report(touch_count=7)

        session_id = self.store.record_session(
            subject_id,
            config,
            report,
            height_cm=168,
            weight_kg=60,
        )
        session = self.store.get_last_session(subject_id)

        self.assertEqual(session.id, session_id)
        self.assertEqual(session.config.number_of_jumps, 7)
        self.assertEqual(session.config.min_contact_time, 80)
        self.assertEqual(session.total_jumps, 7)
        self.assertEqual(session.report_summary["total_jumps"], 7)
        self.assertEqual(session.report_summary["min_jump_height"], report.min_jump_height)
        self.assertEqual(session.report_summary["std_jump_height"], report.std_jump_height)
        self.assertEqual(session.report_summary["min_air_time"], report.min_air_time)
        self.assertEqual(session.report_summary["std_air_time"], report.std_air_time)
        self.assertEqual(session.report_summary["min_contact_time"], report.min_contact_time)
        self.assertEqual(session.report_summary["max_contact_time"], report.max_contact_time)
        self.assertEqual(session.report_summary["std_contact_time"], report.std_contact_time)
        self.assertNotIn("jump_heights", session.report_summary)
        self.assertNotIn("cadences", session.report_summary)
        self.assertNotIn("export_frames", session.report_summary)
        self.assertNotIn("export_timestamps", session.report_summary)

        subject = self.store.get_subject(subject_id)
        self.assertEqual(subject.height_cm, 168)
        self.assertEqual(subject.weight_kg, 60)

    def test_recent_history_uses_agent_expected_keys(self):
        subject_id = self.store.create_subject("Dana", 1998)
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=4, min_contact_time=90),
            _jump_report(touch_count=4),
            started_at="2026-05-14 11:00:00",
        )

        history = self.store.get_recent_history(subject_id)
        self.assertEqual(history[0]["date"], "2026-05-14")
        self.assertEqual(history[0]["test_type"], "Jump Test")
        self.assertEqual(history[0]["number_of_jumps"], 4)
        self.assertEqual(history[0]["min_contact_time"], 90)
        self.assertNotIn("condition", history[0])
        self.assertNotIn("affected_side", history[0])

    def test_get_sessions_filters_by_subject_and_returns_newest_first(self):
        subject_id = self.store.create_subject("Eve", 1992)
        other_id = self.store.create_subject("Frank", 1991)
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            started_at="2026-05-14 09:00:00",
        )
        latest_id = self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=6),
            _jump_report(touch_count=6, finish_reason="manual"),
            started_at="2026-05-14 11:00:00",
        )
        self.store.record_session(
            other_id,
            _TestConfig(number_of_jumps=9),
            _jump_report(touch_count=9),
            started_at="2026-05-14 12:00:00",
        )

        sessions = self.store.get_sessions(subject_id, limit=1)

        self.assertEqual([session.id for session in sessions], [latest_id])
        self.assertEqual(sessions[0].config.number_of_jumps, 6)
        self.assertEqual(sessions[0].report_summary["finish_reason"], "manual")

    def test_delete_unused_subject_but_archive_used_subject(self):
        unused_id = self.store.create_subject("Unused", 1980)
        self.assertTrue(self.store.delete_subject_if_unused(unused_id))
        self.assertIsNone(self.store.get_subject(unused_id))

        used_id = self.store.create_subject("Used", 1985)
        self.store.record_session(used_id, _TestConfig(), _jump_report())
        self.assertFalse(self.store.delete_subject_if_unused(used_id))
        self.assertTrue(self.store.get_subject(used_id).archived)
        self.assertEqual(self.store.search_subjects("Used"), [])
        self.assertEqual(len(self.store.search_subjects("Used", include_archived=True)), 1)


    def test_subject_store_persists_measured_foot_length_and_treadmill_detail(self):
        subject_id = self.store.create_subject(
            display_name="Runner",
            sex="",
            birth_year=1990,
            height_cm=175.0,
            weight_kg=70.0,
            level="intermediate",
            focus_side="",
            notes="",
        )
        self.store.update_subject_measurements(
            subject_id,
            height_cm=175.0,
            weight_kg=70.0,
            measured_foot_length_cm=26.5,
        )
        config = TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
            foot_length_cm_snapshot=26.5,
            foot_length_source="manual",
        )

        report = TreadmillGaitReport(
            finish_reason="manual",
            touch_count=0,
            lift_count=0,
            resolved_starting_foot="unknown",
            starting_foot_source="unknown",
            per_step_results=(
                TreadmillStepResult(
                    index=0,
                    side="left",
                    row_status="valid",
                    is_event_valid=True,
                    is_included_in_statistics=True,
                    correction_source="none",
                    gap_between_feet_cm=8.5,
                    quality_flags=("gap_below_minimum",),
                ),
            ),
            metric_summaries={"contact_time_s": summarize(())},
            report_config_snapshot=config.to_dict(),
            raw_gait_events=(GaitEventRecord(0, 0.0, "left", "touch"),),
            gait_cycles=(
                GaitCycleRecord(
                    index=0,
                    side="left",
                    start_time_s=0.0,
                    end_time_s=1.0,
                    gait_cycle_s=1.0,
                    stance_phase_s=0.6,
                    stance_phase_percent=60.0,
                    swing_phase_s=0.4,
                    swing_phase_percent=40.0,
                    step_time_s=0.5,
                    single_support_s=0.4,
                    single_support_percent=40.0,
                    total_double_support_s=0.2,
                    total_double_support_percent=20.0,
                    load_response_s=0.1,
                    load_response_percent=10.0,
                    pre_swing_s=0.1,
                    pre_swing_percent=10.0,
                    total_flight_time_s=0.0,
                    statistics_exclusion_reason=(
                        "Contact time below minimum threshold"
                    ),
                    quality_flags=("running_overlap_above_tolerance",),
                ),
            ),
            boundary_partials=(
                GaitBoundaryPartial("right", 0.5, 1.2, 0.7, "摆动相"),
            ),
            cycle_metric_summaries={"gait_cycle_s": summarize((1.0,))},
            cycle_side_summaries={
                "left": {"gait_cycle_s": summarize((1.0,))},
                "right": {"gait_cycle_s": summarize(())},
            },
        )

        session_id = self.store.record_session(
            subject_id,
            config=config,
            report=report,
        )
        session = self.store.get_session(session_id)

        self.assertEqual(session.report_summary["report_type"], "treadmill_gait")
        self.assertEqual(session.report_summary["valid_cycle_count"], 1)
        self.assertEqual(session.report_detail["report_schema_version"], 3)
        self.assertEqual(session.report_detail["report_config_snapshot"]["treadmill_speed"], 5.0)
        self.assertEqual(session.report_detail["raw_gait_events"][0]["side"], "left")
        self.assertEqual(session.report_detail["gait_cycles"][0]["gait_cycle_s"], 1.0)
        self.assertEqual(
            session.report_detail["gait_cycles"][0]["statistics_exclusion_reason"],
            "Contact time below minimum threshold",
        )
        self.assertEqual(
            session.report_detail["gait_cycles"][0]["quality_flags"],
            ["running_overlap_above_tolerance"],
        )
        self.assertEqual(
            session.report_detail["per_step_results"][0]["gap_between_feet_cm"],
            8.5,
        )
        self.assertEqual(
            session.report_detail["per_step_results"][0]["quality_flags"],
            ["gap_below_minimum"],
        )
        self.assertEqual(session.report_detail["boundary_partials"][0]["phase"], "摆动相")


if __name__ == "__main__":
    unittest.main()
