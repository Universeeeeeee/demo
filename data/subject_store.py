"""SQLite persistence for athlete/subject profiles and test sessions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from config.test_config import TestConfig
from config.test_report import GaitTestReport, JumpTestReport, TestReport
from path_utils import get_base_dir


LEVELS = {"beginner", "intermediate", "advanced"}
FOCUS_SIDES = {"", "left", "right", "both"}
FINISH_REASONS = {"jump_count_reached", "time_up", "manual", "error"}


@dataclass(frozen=True)
class SubjectProfile:
    id: int
    display_name: str
    sex: str
    birth_year: int
    height_cm: float | None = None
    weight_kg: float | None = None
    level: str = "intermediate"
    focus_side: str = ""
    notes: str = ""
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class SubjectSearchResult:
    subject: SubjectProfile
    display_labels: dict[str, str]
    last_session_at: str | None = None


@dataclass(frozen=True)
class SessionRecord:
    id: int
    subject_id: int
    started_at: str
    finished_at: str | None
    test_type: str
    config_json: str
    height_cm: float | None = None
    weight_kg: float | None = None
    total_jumps: int | None = None
    finish_reason: str | None = None
    report_summary_json: str | None = None
    export_path: str | None = None

    @property
    def config(self) -> TestConfig:
        return TestConfig.from_dict(json.loads(self.config_json))

    @property
    def report_summary(self) -> dict[str, Any]:
        if not self.report_summary_json:
            return {}
        return json.loads(self.report_summary_json)


def default_db_path() -> Path:
    return Path(get_base_dir()) / "data" / "iron_jump.sqlite3"


class SubjectStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_subject(
        self,
        display_name: str,
        birth_year: int,
        *,
        sex: str = "",
        height_cm: float | None = None,
        weight_kg: float | None = None,
        level: str = "intermediate",
        focus_side: str = "",
        notes: str = "",
    ) -> int:
        self._validate_subject_values(display_name, birth_year, level, focus_side)
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO subjects (
                    display_name, sex, birth_year, height_cm, weight_kg,
                    level, focus_side, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    display_name.strip(),
                    sex,
                    birth_year,
                    height_cm,
                    weight_kg,
                    level,
                    focus_side,
                    notes,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def update_subject(self, subject_id: int, **fields: Any) -> None:
        allowed = {
            "display_name",
            "sex",
            "birth_year",
            "height_cm",
            "weight_kg",
            "level",
            "focus_side",
            "notes",
            "archived",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown subject fields: {', '.join(sorted(unknown))}")
        if not fields:
            return

        current = self.get_subject(subject_id)
        if current is None:
            raise KeyError(f"Subject not found: {subject_id}")

        display_name = fields.get("display_name", current.display_name)
        birth_year = fields.get("birth_year", current.birth_year)
        level = fields.get("level", current.level)
        focus_side = fields.get("focus_side", current.focus_side)
        self._validate_subject_values(display_name, birth_year, level, focus_side)

        assignments = [f"{name} = ?" for name in fields]
        values = [_db_value(fields[name]) for name in fields]
        assignments.append("updated_at = ?")
        values.append(_now())
        values.append(subject_id)

        with self._connect() as conn:
            conn.execute(
                f"UPDATE subjects SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def archive_subject(self, subject_id: int) -> None:
        self.update_subject(subject_id, archived=True)

    def delete_subject_if_unused(self, subject_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM test_sessions WHERE subject_id = ?",
                (subject_id,),
            ).fetchone()
            if row["count"]:
                conn.execute(
                    "UPDATE subjects SET archived = 1, updated_at = ? WHERE id = ?",
                    (_now(), subject_id),
                )
                return False
            cur = conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
            return cur.rowcount > 0

    def search_subjects(
        self, query: str = "", *, include_archived: bool = False
    ) -> list[SubjectSearchResult]:
        sql = """
            SELECT
                s.*,
                latest.last_session_at
            FROM subjects s
            LEFT JOIN (
                SELECT subject_id, MAX(started_at) AS last_session_at
                FROM test_sessions
                GROUP BY subject_id
            ) latest ON latest.subject_id = s.id
        """
        where: list[str] = []
        params: list[Any] = []

        if query.strip():
            where.append("s.display_name LIKE ?")
            params.append(f"%{query.strip()}%")
        if not include_archived:
            where.append("s.archived = 0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.updated_at DESC, s.id DESC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            SubjectSearchResult(
                subject=_subject_from_row(row),
                display_labels=self._display_labels(row),
                last_session_at=row["last_session_at"],
            )
            for row in rows
        ]

    def get_subject(self, subject_id: int) -> SubjectProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()
        return _subject_from_row(row) if row else None

    def get_last_session(
        self, subject_id: int, test_type: str | None = None
    ) -> SessionRecord | None:
        sql = "SELECT * FROM test_sessions WHERE subject_id = ?"
        params: list[Any] = [subject_id]
        if test_type is not None:
            sql += " AND test_type = ?"
            params.append(test_type)
        sql += " ORDER BY started_at DESC, id DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return _session_from_row(row) if row else None

    def get_recent_history(
        self, subject_id: int, *, limit: int = 3
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM test_sessions
                WHERE subject_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (subject_id, limit),
            ).fetchall()
        return [_history_from_session(_session_from_row(row)) for row in reversed(rows)]

    def record_session(
        self,
        subject_id: int,
        config: TestConfig,
        report: TestReport,
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        height_cm: float | None = None,
        weight_kg: float | None = None,
        export_path: str | None = None,
    ) -> int:
        summary = _report_summary(report)
        finish_reason = _normalize_finish_reason(report.finish_reason)
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO test_sessions (
                    subject_id, started_at, finished_at, test_type, config_json,
                    height_cm, weight_kg, total_jumps, finish_reason,
                    report_summary_json, export_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_id,
                    started_at or now,
                    finished_at or now,
                    config.test_type,
                    json.dumps(config.to_dict(), ensure_ascii=False),
                    height_cm,
                    weight_kg,
                    summary.get("total_jumps"),
                    finish_reason,
                    json.dumps(summary, ensure_ascii=False),
                    export_path,
                ),
            )
            self._update_subject_measurements(conn, subject_id, height_cm, weight_kg)
            return int(cur.lastrowid)

    def subject_to_athlete_profile(
        self,
        subject: SubjectProfile,
        recent_sessions: list[dict[str, Any]] | None = None,
    ) -> AthleteProfile:
        from agent.models import AthleteProfile  # 延迟导入，避免拖入 pydantic 依赖
        history = (
            recent_sessions
            if recent_sessions is not None
            else self.get_recent_history(subject.id)
        )
        return AthleteProfile(
            age=max(0, datetime.now().year - subject.birth_year),
            weight=float(subject.weight_kg or 0.0),
            height=float(subject.height_cm or 0.0),
            level=subject.level,
            focus_side=subject.focus_side,
            history=history,
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    sex TEXT NOT NULL DEFAULT '',
                    birth_year INTEGER NOT NULL,
                    height_cm REAL,
                    weight_kg REAL,
                    level TEXT NOT NULL DEFAULT 'intermediate'
                        CHECK(level IN ('beginner', 'intermediate', 'advanced')),
                    focus_side TEXT NOT NULL DEFAULT ''
                        CHECK(focus_side IN ('', 'left', 'right', 'both')),
                    notes TEXT NOT NULL DEFAULT '',
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS test_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id INTEGER NOT NULL REFERENCES subjects(id),
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    finished_at TEXT,
                    test_type TEXT NOT NULL DEFAULT 'Jump Test',
                    config_json TEXT NOT NULL,
                    height_cm REAL,
                    weight_kg REAL,
                    total_jumps INTEGER,
                    finish_reason TEXT CHECK(finish_reason IN
                        ('jump_count_reached', 'time_up', 'manual', 'error')),
                    report_summary_json TEXT,
                    export_path TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_subjects_name_archived
                    ON subjects(display_name, archived);
                CREATE INDEX IF NOT EXISTS idx_sessions_subject_started
                    ON test_sessions(subject_id, started_at DESC);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _display_labels(self, row: sqlite3.Row) -> dict[str, str]:
        labels = {
            "Age": str(max(0, datetime.now().year - int(row["birth_year"]))),
            "Level": row["level"],
        }
        if row["focus_side"]:
            labels["Focus"] = row["focus_side"]
        if row["last_session_at"]:
            labels["Last test"] = row["last_session_at"][:10]
        return labels

    def _update_subject_measurements(
        self,
        conn: sqlite3.Connection,
        subject_id: int,
        height_cm: float | None,
        weight_kg: float | None,
    ) -> None:
        updates: dict[str, Any] = {}
        if height_cm is not None:
            updates["height_cm"] = height_cm
        if weight_kg is not None:
            updates["weight_kg"] = weight_kg
        if updates:
            assignments = [f"{name} = ?" for name in updates]
            values = list(updates.values())
            assignments.append("updated_at = ?")
            values.append(_now())
            values.append(subject_id)
            conn.execute(
                f"UPDATE subjects SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    @staticmethod
    def _validate_subject_values(
        display_name: str, birth_year: int, level: str, focus_side: str
    ) -> None:
        if not display_name or not display_name.strip():
            raise ValueError("display_name is required")
        current_year = datetime.now().year
        if birth_year < 1900 or birth_year > current_year:
            raise ValueError("birth_year is out of range")
        if level not in LEVELS:
            raise ValueError(f"level must be one of {sorted(LEVELS)}")
        if focus_side not in FOCUS_SIDES:
            raise ValueError(f"focus_side must be one of {sorted(FOCUS_SIDES)}")


def _subject_from_row(row: sqlite3.Row) -> SubjectProfile:
    return SubjectProfile(
        id=int(row["id"]),
        display_name=row["display_name"],
        sex=row["sex"],
        birth_year=int(row["birth_year"]),
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        level=row["level"],
        focus_side=row["focus_side"],
        notes=row["notes"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=int(row["id"]),
        subject_id=int(row["subject_id"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        test_type=row["test_type"],
        config_json=row["config_json"],
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        total_jumps=row["total_jumps"],
        finish_reason=row["finish_reason"],
        report_summary_json=row["report_summary_json"],
        export_path=row["export_path"],
    )


def _history_from_session(session: SessionRecord) -> dict[str, Any]:
    config = session.config
    summary = session.report_summary
    # Extra fields are reserved for future report-analysis agents; the current
    # config agent only reads date/test_type/number_of_jumps/min_contact_time.
    return {
        "date": session.started_at[:10],
        "test_type": session.test_type,
        "number_of_jumps": config.number_of_jumps,
        "min_contact_time": config.min_contact_time,
        "finish_reason": session.finish_reason,
        "total_jumps": session.total_jumps,
        "summary": summary,
    }


def _report_summary(report: TestReport) -> dict[str, Any]:
    base: dict[str, Any] = {
        "finish_reason": report.finish_reason,
        "touch_count": report.touch_count,
        "lift_count": report.lift_count,
    }
    if isinstance(report, JumpTestReport):
        base.update(
            {
                "report_type": "jump",
                "total_jumps": report.touch_count,
                "avg_jump_height": report.avg_jump_height,
                "max_jump_height": report.max_jump_height,
                "avg_air_time": report.avg_air_time,
                "max_air_time": report.max_air_time,
                "avg_contact_time": report.avg_contact_time,
                "avg_cadence": report.avg_cadence,
            }
        )
    elif isinstance(report, GaitTestReport):
        base.update(
            {
                "report_type": "gait",
                "avg_stride": report.avg_stride,
                "max_stride": report.max_stride,
                "avg_velocity": report.avg_velocity,
                "max_velocity": report.max_velocity,
                "imbalance_index": report.imbalance_index,
                "avg_double_support": report.avg_double_support,
                "avg_single_support": report.avg_single_support,
                "avg_acceleration": report.avg_acceleration,
            }
        )
    return base


def _normalize_finish_reason(reason: str) -> str:
    return reason if reason in FINISH_REASONS else "error"


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _db_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    return value
