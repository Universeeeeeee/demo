# User and Team Management Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add team-aware athlete management while enforcing a strict boundary between long-lived athlete profiles and immutable test-session identity snapshots.

**Architecture:** Keep `SubjectStore` as the existing SQLite transaction boundary for this phase so athlete creation plus initial team membership remains atomic. Add `teams` and `team_memberships` as a many-to-many model, add an optional team identity to each test session, and continue storing each report exactly once. UI changes stay inside the existing Athletes, Setup, and History modules; a broad repository refactor is explicitly deferred.

**Tech Stack:** Python 3.11, SQLite, qtpy/PySide6, pytest, pytest-qt.

## Global Constraints

- Work on the current `vae/iron_jump` branch because the user explicitly declined a new branch or worktree.
- Preserve all pre-existing uncommitted changes. Stage and commit only files and hunks created for this plan.
- Follow strict TDD: add one behavior test, run it and observe the expected failure, then write the minimum production code to pass.
- A registered athlete is one `subjects` row and may have zero, one, or many active team memberships.
- “未加入团队” is the display state for an athlete with zero active memberships; athlete creation uses the option text “暂不加入团队”.
- Existing `subjects.id` remains the internal immutable identity. Do not add UUIDs or expose formatted database IDs in normal UI.
- Suspected duplicates are matched by normalized display name plus birth year. Warn and allow the operator to continue creating a separate athlete.
- When a duplicate is reused for a different team, add a membership to the existing athlete instead of duplicating the athlete row.
- Registered-athlete age is read-only on the test setup page. Birth year is editable only in athlete management.
- Test-page profile edits never update the athlete profile implicitly.
- Explicit “更新运动员档案” overwrites height, weight, level, and focus side together; it never changes birth year.
- A registered-athlete test requires an explicit identity choice: one active joined team or “不以团队身份测试”.
- A temporary test always has `subject_id IS NULL` and `team_id IS NULL`.
- Every test creates exactly one `test_sessions` row. Personal and team histories are queries over that same row.
- Personal history includes every session with the athlete’s `subject_id`; team history includes only sessions with that `team_id`.
- Team rename, archive, membership removal, or athlete archive must not rewrite historical session identity snapshots.
- Login, RBAC, cloud sync, UUIDs, cross-device merging, team rankings, complete foot-capture workflow, and retroactive team reassignment are out of scope.
- Do not perform a broad split of `data/subject_store.py` in this phase.

---

### Task 1: Versioned Team Schema and Persistence API

**Files:**
- Modify: `data/subject_store.py`
- Modify: `tests/test_subject_store.py`

**Interfaces:**
- Produces: `TeamProfile`, `TeamMembership`, `SubjectSearchResult.team_names`, and `SessionRecord.team_id`.
- Produces: `SubjectStore.create_team(name) -> int`.
- Produces: `SubjectStore.search_teams(query="", include_archived=False) -> list[TeamProfile]`.
- Produces: `SubjectStore.get_subject_teams(subject_id, active_only=True) -> list[TeamProfile]`.
- Produces: `SubjectStore.add_subject_to_team(subject_id, team_id) -> None`.
- Produces: `SubjectStore.remove_subject_from_team(subject_id, team_id) -> None`.
- Produces: `SubjectStore.create_subject(..., team_id: int | None = None) -> int`.
- Produces: `SubjectStore.find_duplicate_subjects(display_name, birth_year) -> list[SubjectSearchResult]`.
- Produces: schema version `1` through SQLite `PRAGMA user_version`.

- [ ] **Step 1: Add failing migration and team-schema tests**

Add focused tests that assert:

```python
def test_schema_v1_adds_team_tables_and_nullable_session_team(self):
    with self.store._connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        session_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(test_sessions)")
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    self.assertIn("teams", tables)
    self.assertIn("team_memberships", tables)
    self.assertIn("team_id", session_columns)
    self.assertIn("team_snapshot_json", session_columns)
    self.assertEqual(version, 1)
```

Extend the existing legacy database fixture and assert migration preserves its subject and session while assigning no team:

```python
self.assertIsNone(migrated.get_session(7).team_id)
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_subject_store.py::SubjectStoreTest::test_schema_v1_adds_team_tables_and_nullable_session_team \
  tests/test_subject_store.py::SubjectStoreTest::test_existing_required_subject_schema_is_migrated_without_data_loss
```

Expected: FAIL because team tables, team session columns, or schema version are missing.

- [ ] **Step 3: Implement schema version 1**

Add frozen records:

```python
@dataclass(frozen=True)
class TeamProfile:
    id: int
    name: str
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TeamMembership:
    subject_id: int
    team_id: int
    active: bool
    joined_at: str
    left_at: str | None = None
```

Create:

```sql
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS team_memberships (
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    active INTEGER NOT NULL DEFAULT 1,
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    left_at TEXT,
    PRIMARY KEY (subject_id, team_id)
);
```

Add nullable `team_id INTEGER REFERENCES teams(id)` and `team_snapshot_json TEXT` to `test_sessions`. Add `normalized_name TEXT NOT NULL DEFAULT ''` to `subjects`, backfill it with `_normalize_name(display_name)`, and create indexes for duplicate lookup, active memberships, and team session history. Set `PRAGMA user_version = 1` only after the migration succeeds.

- [ ] **Step 4: Add failing team API and many-to-many tests**

Add tests for:

```python
def test_subject_can_join_multiple_teams_and_leave_one(self):
    subject_id = self.store.create_subject("Alice", 1990)
    team_a = self.store.create_team("Alpha")
    team_b = self.store.create_team("Beta")

    self.store.add_subject_to_team(subject_id, team_a)
    self.store.add_subject_to_team(subject_id, team_b)
    self.assertEqual(
        [team.name for team in self.store.get_subject_teams(subject_id)],
        ["Alpha", "Beta"],
    )

    self.store.remove_subject_from_team(subject_id, team_a)
    self.assertEqual(
        [team.name for team in self.store.get_subject_teams(subject_id)],
        ["Beta"],
    )
```

Also prove:

- Team names are trimmed and normalized before uniqueness checks.
- Re-adding an inactive `(subject_id, team_id)` membership reactivates it.
- Missing or archived teams cannot receive a new membership.
- `create_subject(..., team_id=team_id)` creates the athlete and membership atomically.

- [ ] **Step 5: Run the new API tests and verify RED**

Run the individual new tests. Expected: FAIL because the public team methods do not exist.

- [ ] **Step 6: Implement the minimal team API**

Use parameterized SQL and the existing `_connect()` transaction boundary. `create_subject(..., team_id=...)` must insert the membership through the same connection before commit. `get_subject_teams()` returns active, non-archived teams ordered by normalized team name then ID.

- [ ] **Step 7: Add and implement duplicate lookup**

Write a failing test:

```python
def test_duplicate_lookup_matches_normalized_name_and_birth_year(self):
    subject_id = self.store.create_subject("  Alice  Smith ", 1990)
    self.store.create_subject("Alice Smith", 1991)

    matches = self.store.find_duplicate_subjects("alice   smith", 1990)

    self.assertEqual([item.subject.id for item in matches], [subject_id])
```

Implement `_normalize_name()` as trim, internal-whitespace collapse, and `casefold()`. Duplicate lookup warns through returned candidates; it never enforces uniqueness.

- [ ] **Step 8: Run Task 1 tests and commit**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_subject_store.py
```

Stage only `data/subject_store.py` and Task 1 hunks in `tests/test_subject_store.py`.

Commit:

```bash
git commit -m "feat: add team persistence model"
```

---

### Task 2: Profile Validation and Session Snapshot Boundary

**Files:**
- Modify: `data/subject_store.py`
- Modify: `ui/main_window.py`
- Modify: `tests/test_subject_store.py`
- Modify: `tests/test_main_window_navigation.py`

**Interfaces:**
- Consumes: Task 1 `SubjectStore` schema and records.
- Produces: `SubjectStore.update_subject_from_session_profile(subject_id, *, height_cm, weight_kg, level, focus_side) -> None`.
- Changes: `SubjectStore.record_session()` no longer mutates `subjects`.

- [ ] **Step 1: Write the failing no-implicit-writeback test**

```python
def test_record_session_does_not_update_subject_measurements(self):
    subject_id = self.store.create_subject(
        "Alice", 1990, height_cm=170.0, weight_kg=60.0
    )

    self.store.record_session(
        subject_id,
        _TestConfig(),
        _jump_report(),
        height_cm=180.0,
        weight_kg=70.0,
        subject_snapshot={"height_cm": 180.0, "weight_kg": 70.0},
    )

    subject = self.store.get_subject(subject_id)
    self.assertEqual(subject.height_cm, 170.0)
    self.assertEqual(subject.weight_kg, 60.0)
```

- [ ] **Step 2: Run the test and verify RED**

Expected: FAIL with the current profile values changed to `180.0` and `70.0`.

- [ ] **Step 3: Remove implicit profile mutation**

Remove the `_update_subject_measurements()` call from `record_session()`. Preserve the passed height and weight on `test_sessions` and in `subject_snapshot_json`.

- [ ] **Step 4: Add failing explicit whole-profile update tests**

Test that `update_subject_from_session_profile()` updates height, weight, level, and focus side together while leaving birth year and name unchanged.

- [ ] **Step 5: Implement the explicit update method**

Use the signature:

```python
def update_subject_from_session_profile(
    self,
    subject_id: int,
    *,
    height_cm: float | None,
    weight_kg: float | None,
    level: str,
    focus_side: str,
) -> None:
```

Delegate to validated `update_subject()` fields and never accept `birth_year`.

- [ ] **Step 6: Add failing invalid-measurement tests**

Use table-driven literal cases covering:

```python
(-1.0, None)
(float("nan"), None)
(float("inf"), None)
(251.0, None)
(None, -1.0)
(None, 301.0)
```

Each case must raise `ValueError` from both create and update entry points. `None` remains valid.

- [ ] **Step 7: Implement validation and SQLite guards**

Use `math.isfinite()`. Valid non-null height is `0 < height_cm <= 250`; valid non-null weight is `0 < weight_kg <= 300`; valid non-null measured foot length is finite and positive. Apply validation in `create_subject()`, `update_subject()`, and `update_subject_measurements()`.

For fresh and migrated databases, create SQLite insert/update triggers that reject non-null non-positive or over-limit height and weight. Do not rebuild the existing tables.

- [ ] **Step 8: Update main-window persistence tests**

Adjust tests so a completed registered session persists the session snapshot but does not alter the subject master profile. Keep the temporary-session behavior unchanged.

- [ ] **Step 9: Run Task 2 tests and commit**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_subject_store.py tests/test_main_window_navigation.py
```

Stage only the four Task 2 files and only Task 2 hunks.

Commit:

```bash
git commit -m "fix: separate athlete profiles from session snapshots"
```

---

### Task 3: Athlete Team Management UI

**Files:**
- Modify: `ui/views/athletes_view.py`
- Modify: `tests/test_athletes_view.py`

**Interfaces:**
- Consumes: Task 1 team and duplicate APIs.
- Produces: `AthletesView` team filter and team-aware create/edit workflows.
- Produces: `_SubjectDialog.values()` with `team_ids: list[int]`.

- [ ] **Step 1: Add failing athlete-list team display and filter tests**

Create real teams and memberships, instantiate `AthletesView`, then assert:

- A multi-team athlete displays both team names.
- A zero-team athlete displays `未加入团队`.
- Choosing a team filter shows only active members of that team.
- Choosing `未加入团队` shows only athletes with no active membership.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: FAIL because the table has no team column or filter.

- [ ] **Step 3: Implement team display and filtering**

Add a team-filter combo with:

```text
全部团队
未加入团队
<each active team>
```

Add an `所属团队` column. Extend `search_subjects()` only as needed to accept `team_id` and `without_team`; do not filter in Python after loading all athletes.

- [ ] **Step 4: Add failing create-dialog tests**

Assert the dialog offers:

```text
暂不加入团队
<existing active teams>
新建团队…
```

For edit mode, use a checkable team list so multiple memberships can be selected. Registered athlete creation initially selects zero or one team; later editing may select many.

- [ ] **Step 5: Implement team-aware create and edit**

New-team creation validates and persists the team before selecting it. Athlete creation with an initial team uses `create_subject(..., team_id=...)`. Athlete edit synchronizes active memberships to the selected team IDs without deleting membership history.

- [ ] **Step 6: Add failing duplicate-flow tests**

Cover:

1. No candidate: create normally.
2. Candidate in another team: “使用已有档案” adds the target membership and does not add a `subjects` row.
3. Candidate already in target team: “使用已有档案” reuses it without duplicate membership.
4. “仍然新建”: creates a second athlete after confirmation.

The duplicate dialog displays name, birth year, teams, creation date, and most recent test. It does not show `subject.id`.

- [ ] **Step 7: Implement duplicate flow**

Use the `SubjectSearchResult` object stored as item data. Never reverse-map the chosen athlete by display name.

- [ ] **Step 8: Run Task 3 tests and commit**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_athletes_view.py tests/test_subject_store.py
```

Commit:

```bash
git commit -m "feat: manage athlete team memberships"
```

---

### Task 4: Explicit Profile Update and Test Identity Selection

**Files:**
- Modify: `ui/views/agent_config_panel.py`
- Modify: `ui/views/setup_view.py`
- Modify: `tests/test_agent_config_panel.py`
- Modify: `tests/test_setup_view.py`

**Interfaces:**
- Consumes: Task 1 `get_subject_teams()` and Task 2 explicit profile update.
- Produces: `AgentConfigPanel.profile_changed` signal.
- Produces: `SessionSetup.team_id: int | None` and `SessionSetup.team_snapshot: dict | None`.

- [ ] **Step 1: Add failing registered-age and explicit-update tests**

Assert:

- `AgentConfigPanel.set_subject_result(result)` disables the age field.
- `set_subject_result(None)` enables age for temporary tests.
- Editing a registered athlete’s height, weight, level, or focus reveals `更新运动员档案`.
- Clicking it writes all four safe fields and never changes birth year.
- Completing a test without clicking it leaves the subject profile unchanged.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: FAIL because age stays editable and the update action is absent.

- [ ] **Step 3: Implement explicit profile update UI**

Add `profile_changed = Signal()` to `AgentConfigPanel` and emit it from the four safe profile controls. In `SetupView`, compare the current profile snapshot against the selected `SubjectProfile`. Show one button only when they differ. Confirmation text lists old and new values, but the action has no per-field checkboxes.

- [ ] **Step 4: Add failing team-identity selector tests**

For an athlete in teams Alpha and Beta, assert the selector contains:

```text
请选择本次测试身份
Alpha
Beta
不以团队身份测试
```

Assert:

- No valid selection keeps `进入测试准备` disabled.
- Selecting Alpha produces `SessionSetup.team_id == alpha_id`.
- Selecting personal identity produces `team_id is None`.
- A temporary test offers only `不以团队身份测试`.
- Archived or inactive memberships are absent.

- [ ] **Step 5: Implement team identity selection**

Add a team identity combo beside the subject selector. Store `TeamProfile` as item data. Do not infer identity from display text. On subject change, repopulate from active memberships and reset to the explicit placeholder. For temporary tests, select and lock personal identity.

`SessionSetup.team_snapshot` for a team test is:

```python
{"id": team.id, "name": team.name}
```

Personal and temporary tests use `None`.

- [ ] **Step 6: Keep readiness validation unified**

Update `_on_ready_clicked()` so it rejects a registered subject with no explicit team/personal choice before emitting `ready_signal`. Preserve the existing runtime-config validation order.

- [ ] **Step 7: Run Task 4 tests and commit**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_agent_config_panel.py tests/test_setup_view.py
```

Because both test files already contain user changes, stage only Task 4 hunks.

Commit:

```bash
git commit -m "feat: select test team identity"
```

---

### Task 5: Single-Row Team Session Persistence and Histories

**Files:**
- Modify: `data/subject_store.py`
- Modify: `ui/main_window.py`
- Modify: `ui/views/history_view.py`
- Modify: `tests/test_subject_store.py`
- Modify: `tests/test_main_window_navigation.py`
- Modify: `tests/test_history_view.py`

**Interfaces:**
- Consumes: Task 4 `SessionSetup.team_id` and `team_snapshot`.
- Produces: `SubjectStore.record_session(..., team_id=None, team_snapshot=None)`.
- Produces: `SubjectStore.get_team_sessions(team_id, limit=200) -> list[SessionRecord]`.
- Produces: `HistoryView.load_team(team: TeamProfile) -> None`.

- [ ] **Step 1: Add failing session-membership integrity tests**

Assert:

- A registered subject may save a personal session with `team_id=None`.
- An active member may save a session for that team.
- A non-member, inactive member, archived team, or temporary subject with a team raises `ValueError`.
- Team snapshot JSON round-trips through `SessionRecord.team_snapshot`.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: FAIL because `record_session()` does not accept team identity.

- [ ] **Step 3: Implement team-aware record_session**

Add keyword-only arguments:

```python
team_id: int | None = None
team_snapshot: dict[str, Any] | None = None
```

Validate active membership within the same connection used for the session insert. Personal and temporary sessions require `team_snapshot is None`. Team sessions require the passed snapshot ID to equal `team_id`.

- [ ] **Step 4: Add failing single-row history tests**

Create one Alpha team session and one personal session for the same athlete. Assert:

```python
self.assertEqual(len(self.store.get_sessions(subject_id)), 2)
self.assertEqual(len(self.store.get_team_sessions(alpha_id)), 1)
self.assertEqual(len(self.store.get_all_sessions()), 2)
```

Rename and archive Alpha, then assert the saved session’s `team_snapshot["name"]` remains `"Alpha"`.

- [ ] **Step 5: Implement team queries and history presentation**

Add `get_team_sessions()` using `test_sessions.team_id`. Add a `测试身份` column to HistoryView:

- Team session: saved team snapshot name.
- Registered personal session: `个人`.
- Temporary session: `临时测试`.

Add a team filter or `load_team()` entry without creating a second report store.

- [ ] **Step 6: Pass team identity through MainWindow**

Track `_team_id` and `_team_snapshot` beside `_subject_id` and `_subject_snapshot`. Reset them on navigation/discard. Pass both into `record_session()` after a test finishes.

- [ ] **Step 7: Preserve temporary-result linking semantics**

`link_session_to_subject()` changes only `subject_id`. It must leave `team_id` null and preserve the original subject and team snapshots.

- [ ] **Step 8: Run Task 5 tests and commit**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_subject_store.py tests/test_main_window_navigation.py \
  tests/test_history_view.py
```

Commit:

```bash
git commit -m "feat: persist team test identity"
```

---

### Task 6: End-to-End Regression and Migration Verification

**Files:**
- Modify: `tests/test_main_window_navigation.py`
- Modify: `tests/test_history_view.py`
- Modify: `tests/test_subject_store.py`
- Modify only if failures prove necessary: files changed in Tasks 1-5

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified end-to-end behavior and a clean full-suite result.

- [ ] **Step 1: Add the end-to-end identity scenario**

Using real `SubjectStore` and UI components where practical:

1. Create Alpha and Beta.
2. Create one athlete in Alpha.
3. Add the same athlete to Beta.
4. Save one Alpha session and one personal session.
5. Assert athlete history contains two rows.
6. Assert Alpha history contains one row.
7. Assert Beta history contains zero rows.
8. Assert `get_all_sessions()` contains exactly two rows.

- [ ] **Step 2: Run the new scenario and verify RED if integration is incomplete**

Any failure must name the missing integration boundary. Do not weaken assertions to accommodate implementation.

- [ ] **Step 3: Implement only proven integration fixes**

Fix production code only for failures demonstrated by the new integration test. Add a focused regression test before every additional bug fix.

- [ ] **Step 4: Run all user-management tests**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests/test_subject_store.py tests/test_athletes_view.py \
  tests/test_agent_config_panel.py tests/test_setup_view.py \
  tests/test_main_window_navigation.py tests/test_history_view.py
```

Expected: all pass with no warnings or unexpected output.

- [ ] **Step 5: Run the complete test suite**

Run:

```bash
env QT_QPA_PLATFORM=offscreen /Users/vae/miniconda3/envs/Iron_Jump/bin/python \
  -m pytest -q tests
```

Expected: all tests under `tests/` pass. The pre-change baseline is `384 passed, 2 subtests passed, 1 PytestCollectionWarning`. Running pytest from the repository root also collects `archive/tools/agent/test_parallel_verify.py`, which has a pre-existing `PatientContext` import error and is not part of this plan.

- [ ] **Step 6: Verify the delivered database directly**

Use a temporary SQLite database and query:

```sql
SELECT COUNT(*) FROM subjects;
SELECT COUNT(*) FROM teams;
SELECT COUNT(*) FROM team_memberships WHERE active = 1;
SELECT COUNT(*) FROM test_sessions;
SELECT COUNT(*) FROM test_sessions WHERE team_id = ?;
```

Expected for the Alpha/Beta scenario: one subject, two teams, two active memberships, two total sessions, one Alpha session.

- [ ] **Step 7: Check diff hygiene and commit**

Run:

```bash
git diff --check
git status --short
```

Confirm pre-existing user changes remain unstaged and unmodified except for deliberately merged Task 4 test hunks.

Commit:

```bash
git commit -m "test: cover team-aware athlete workflow"
```
