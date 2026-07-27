# Execution Preview Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the completed-cycle table from the treadmill execution page, maximize the 16:9 camera/countdown/footprint region, and show a large current-cycle summary only when it fits without shrinking the camera.

**Architecture:** Keep the existing `ExecutionView`, `EmbeddedCameraPanel`, and `FootprintChannelWidget` boundaries. Replace the table-backed cycle panel with a fixed-height summary inside a new camera-column layout, then let one `ExecutionView` geometry helper decide whether the summary fits after calculating the camera's maximum 16:9 height.

**Tech Stack:** Python 3, Qt through `qtpy`, Dayu widgets, `pytest`, `pytest-qt`

## Global Constraints

- The camera image must remain exact 16:9, with no stretching and no cropping.
- The completed-cycle label and table must not appear on the execution page.
- The current-cycle summary height is exactly 72px and must never reduce the maximum camera size.
- The countdown column is exactly 72px wide and spans the complete lower execution area.
- The countdown widget has no horizontal padding; its chunk fills the width inside the 1px border.
- 1920×1080 full screen is the primary acceptance scenario; smaller windows may hide the summary.
- Completed cycles must still flow through engine statistics, reports, exports, and history.
- Treadmill gait and treadmill running use the new layout; jump-mode charts and controls do not change.
- Preserve the existing committed behavior that pauses and resumes timed-test countdowns.
- Do not modify camera capture, gait algorithms, report snapshots, Excel export, or history storage.

---

## File Structure

- Modify `ui/views/execution_view.py`: build and update the current-cycle summary, remove the completed-cycle table, create the responsive camera column, and enforce countdown geometry.
- Modify `tests/test_execution_view_footprint.py`: replace table assertions with summary, aspect-ratio, responsive-visibility, and countdown-fill assertions.
- Modify `plan.md`: align the previously confirmed live-display rule with the new “current summary only” execution-page behavior.
- Read only `ui/embedded_camera_panel.py`: retain its existing `_AspectRatioContainer` implementation as the source of exact 16:9 geometry.

### Task 1: Replace the completed-cycle table with a current-cycle summary

**Files:**
- Modify: `tests/test_execution_view_footprint.py:149-308`
- Modify: `ui/views/execution_view.py:18-50`
- Modify: `ui/views/execution_view.py:295-325`
- Modify: `ui/views/execution_view.py:595-608`
- Modify: `ui/views/execution_view.py:690-760`

**Interfaces:**
- Consumes: `ExecutionView.on_gait_snapshot(snapshot: dict)` and `snapshot["gait_cycle_state"]`
- Produces: `ExecutionView._current_cycle_state: MLabel`, `ExecutionView._left_cycle_value: MLabel`, and `ExecutionView._right_cycle_value: MLabel`
- Produces: `ExecutionView._render_gait_cycle_state(state: dict) -> None`, which ignores `completed_cycles` for display purposes

- [ ] **Step 1: Replace completed-table tests with a failing summary test**

Replace `test_execution_view_shows_current_and_completed_gait_cycles` and delete the two table-specific tests. Use this test body:

```python
def test_execution_view_shows_current_gait_cycle_without_completed_table(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )
    QApplication.processEvents()

    view.on_gait_snapshot({
        "touch_count": 3,
        "stride_count": 0,
        "velocity_count": 0,
        "gait_cycle_asymmetry_percent": {"gait_cycle_s": 4.5},
        "gait_cycle_state": {
            "support_state": "左脚单支撑",
            "completed_cycle_count": 1,
            "completed_cycle_start_index": 0,
            "current_cycles": {
                "left": {"phase": "支撑相", "elapsed_s": 0.4},
            },
            "completed_cycles": [{
                "index": 0,
                "side": "right",
                "gait_cycle_s": 1.0,
                "stance_phase_s": 0.6,
                "swing_phase_s": 0.4,
                "total_double_support_s": 0.2,
            }],
        },
    })

    assert view._current_cycle_state.text() == "左脚单支撑"
    assert view._left_cycle_value.text() == "左脚  支撑相 0.400 s"
    assert view._right_cycle_value.text() == "右脚  --"
    assert not hasattr(view, "_completed_cycle_label")
    assert not hasattr(view, "_completed_cycle_table")
    assert view._card_imbalance._value.text() == "4.5"
```

- [ ] **Step 2: Add a failing test for missing phase time and reset state**

```python
def test_current_cycle_summary_uses_dashes_for_missing_values(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    view._render_gait_cycle_state({
        "support_state": "右脚单支撑",
        "current_cycles": {
            "left": {"phase": "摆动相", "elapsed_s": None},
        },
        "completed_cycles": [],
    })

    assert view._current_cycle_state.text() == "右脚单支撑"
    assert view._left_cycle_value.text() == "左脚  摆动相 --"
    assert view._right_cycle_value.text() == "右脚  --"

    view.reset()

    assert view._current_cycle_state.text() == "等待触地事件"
    assert view._left_cycle_value.text() == "左脚  --"
    assert view._right_cycle_value.text() == "右脚  --"
```

- [ ] **Step 3: Run the new tests and confirm they fail for missing summary fields**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest \
  tests/test_execution_view_footprint.py::test_execution_view_shows_current_gait_cycle_without_completed_table \
  tests/test_execution_view_footprint.py::test_current_cycle_summary_uses_dashes_for_missing_values -v
```

Expected: both tests fail because `_current_cycle_state`, `_left_cycle_value`, and `_right_cycle_value` do not exist.

- [ ] **Step 4: Build the fixed-height summary and remove table-only code**

In `ExecutionView._build_ui`, replace the table-backed cycle panel with:

```python
self._cycle_panel = QFrame()
self._cycle_panel.setObjectName("CurrentCyclePanel")
self._cycle_panel.setFixedHeight(72)
self._cycle_panel.setStyleSheet(
    "QFrame#CurrentCyclePanel {"
    "  background-color: rgba(18, 18, 22, 0.92);"
    "  border: 1px solid rgba(90, 90, 95, 0.7);"
    "  border-radius: 8px;"
    "}"
)
cycle_layout = QHBoxLayout(self._cycle_panel)
cycle_layout.setContentsMargins(14, 4, 14, 4)
cycle_layout.setSpacing(14)

state_layout = QVBoxLayout()
state_layout.setContentsMargins(0, 0, 0, 0)
state_layout.setSpacing(0)
self._current_cycle_title = MLabel("当前周期")
self._current_cycle_title.setStyleSheet(
    "font-size: 9pt; color: #ff9b3d; border: none; background: transparent;"
)
self._current_cycle_state = MLabel("等待触地事件")
self._current_cycle_state.setStyleSheet(
    "font-size: 18pt; font-weight: bold; color: #f0f3f8; "
    "border: none; background: transparent;"
)
state_layout.addWidget(self._current_cycle_title)
state_layout.addWidget(self._current_cycle_state)
cycle_layout.addLayout(state_layout, 1)

self._left_cycle_value = MLabel("左脚  --")
self._left_cycle_value.setAlignment(Qt.AlignCenter)
self._left_cycle_value.setStyleSheet(
    "font-size: 14pt; color: #d9dee8; border: none; background: transparent;"
)
cycle_layout.addWidget(self._left_cycle_value, 1)

self._right_cycle_value = MLabel("右脚  --")
self._right_cycle_value.setAlignment(Qt.AlignCenter)
self._right_cycle_value.setStyleSheet(
    "font-size: 14pt; color: #d9dee8; border: none; background: transparent;"
)
cycle_layout.addWidget(self._right_cycle_value, 1)
self._cycle_panel.hide()
```

Delete `_format_cycle_value`, the `QTableWidget`, `QTableWidgetItem`, and `QHeaderView` imports, the `CompletedCycleTable` stylesheet rules, and all completed-row insertion/scrolling code.

- [ ] **Step 5: Update current-state rendering and reset behavior**

Use one small formatter inside `_render_gait_cycle_state`:

```python
def _render_gait_cycle_state(self, state: dict):
    current = state.get("current_cycles", {})
    support_state = state.get("support_state") or "等待触地事件"
    self._current_cycle_state.setText(support_state)

    def phase_text(side: str, label: str) -> str:
        value = current.get(side)
        if not value:
            return f"{label}  --"
        phase = value.get("phase") or "--"
        elapsed = value.get("elapsed_s")
        elapsed_text = f"{elapsed:.3f} s" if elapsed is not None else "--"
        return f"{label}  {phase} {elapsed_text}"

    self._left_cycle_value.setText(phase_text("left", "左脚"))
    self._right_cycle_value.setText(phase_text("right", "右脚"))
```

In `reset()`, set the same three initial strings used by the tests. Do not read or render `completed_cycles`.

- [ ] **Step 6: Run focused and full execution-view tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_execution_view_footprint.py -v
```

Expected: all tests in `tests/test_execution_view_footprint.py` pass; the camera remains directly in the lower grid until Task 2.

- [ ] **Step 7: Commit the summary change**

```bash
git add ui/views/execution_view.py tests/test_execution_view_footprint.py
git commit -m "feat: simplify live gait cycle summary"
```

### Task 2: Make camera enlargement primary and summary visibility responsive

**Files:**
- Modify: `tests/test_execution_view_footprint.py:46-97`
- Modify: `tests/test_execution_view_footprint.py` after the current-cycle tests
- Modify: `ui/views/execution_view.py:277-325`
- Modify: `ui/views/execution_view.py:470-505`
- Modify: `ui/views/execution_view.py:790-826`

**Interfaces:**
- Consumes: `_camera_panel`, `_cycle_panel`, `_lower_split`, and `_config`
- Produces: `ExecutionView._camera_column: QWidget`
- Produces: `ExecutionView._update_cycle_panel_visibility() -> None`
- Produces: `ExecutionView.resizeEvent(event) -> None`

- [ ] **Step 1: Update the lower-grid test to expect a camera column**

Replace the direct camera-grid assertion with:

```python
layout = view._lower_split.layout()
assert isinstance(layout, QGridLayout)
assert layout.getItemPosition(layout.indexOf(view._camera_column)) == (0, 0, 2, 1)
assert view._camera_panel.parentWidget() is view._camera_column
assert view._cycle_panel.parentWidget() is view._camera_column
assert layout.getItemPosition(layout.indexOf(view._progress_container)) == (0, 1, 2, 1)
assert layout.getItemPosition(layout.indexOf(view._footprint_channel)) == (0, 2, 1, 1)
assert layout.getItemPosition(layout.indexOf(view._controls_container)) == (1, 2, 1, 1)
assert layout.columnStretch(0) == 3
assert layout.columnStretch(2) == 1
```

- [ ] **Step 2: Add failing responsive and 16:9 tests**

```python
def test_current_cycle_summary_only_uses_space_left_after_max_camera(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )
    QApplication.processEvents()

    preview = view._camera_panel._preview
    container = view._camera_panel._preview_container
    assert view._cycle_panel.isVisible()
    assert view._cycle_panel.height() == 72
    assert preview.width() == (container.width() // 16) * 16
    assert preview.width() * 9 == preview.height() * 16

    view.resize(1280, 720)
    QApplication.processEvents()

    assert not view._cycle_panel.isVisible()
    assert preview.width() * 9 == preview.height() * 16
```

- [ ] **Step 3: Strengthen the countdown-fill geometry test**

After configuring the timed treadmill view and processing events, add:

```python
assert view._progress_container.width() == 72
assert view._progress_container.height() == view._lower_split.height()
assert view._progress_bar.width() == view._progress_container.width()
assert view._progress_bar.height() == view._progress_container.height()
assert view._progress_overlay.geometry() == view._progress_bar.geometry()
```

- [ ] **Step 4: Run the new layout tests and confirm they fail**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest \
  tests/test_execution_view_footprint.py::test_execution_view_shows_footprint_channel_for_treadmill \
  tests/test_execution_view_footprint.py::test_current_cycle_summary_only_uses_space_left_after_max_camera \
  tests/test_execution_view_footprint.py::test_gait_time_and_controls_use_vertical_lower_layout -v
```

Expected: failures because `_camera_column` and responsive summary visibility do not exist.

- [ ] **Step 5: Put the camera and summary in one column**

Create the camera column before adding it to the lower grid:

```python
self._camera_column = QWidget()
camera_layout = QVBoxLayout(self._camera_column)
camera_layout.setContentsMargins(0, 0, 0, 0)
camera_layout.setSpacing(10)
camera_layout.addWidget(self._camera_panel, 1)
camera_layout.addWidget(self._cycle_panel)
lower_layout.addWidget(self._camera_column, 0, 0, 2, 1)
```

Remove the old `main_layout.addWidget(self._cycle_panel)` call. The countdown and footprint/control placements remain `(0, 1, 2, 1)`, `(0, 2)`, and `(1, 2)`.

- [ ] **Step 6: Add the camera-first visibility calculation**

Add:

```python
def _update_cycle_panel_visibility(self):
    is_treadmill = self._config is not None and self._config.test_type in (
        "Treadmill Gait Test",
        "Treadmill Running Test",
    )
    if not is_treadmill or not self._lower_split.isVisible():
        self._cycle_panel.hide()
        return

    camera_inner_width = max(0, self._camera_column.width() - 8)
    unit = max(1, camera_inner_width // 16)
    maximum_camera_height = unit * 9 + 8
    required_height = maximum_camera_height + 10 + self._cycle_panel.height()
    self._cycle_panel.setVisible(
        self._camera_column.height() >= required_height
    )

def resizeEvent(self, event):
    super().resizeEvent(event)
    if self._mode != "纵跳":
        QTimer.singleShot(0, self._update_cycle_panel_visibility)
```

In `configure()`, stop setting `_cycle_panel` directly from `is_treadmill`; hide it first and schedule `_update_cycle_panel_visibility` after Qt lays out the view:

```python
self._cycle_panel.hide()
if is_treadmill:
    QTimer.singleShot(0, self._update_cycle_panel_visibility)
```

- [ ] **Step 7: Make countdown widgets fill the complete 72px column**

Set zero layout spacing and explicit expanding policies:

```python
progress_layout.setContentsMargins(0, 0, 0, 0)
progress_layout.setSpacing(0)
self._progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
self._progress_overlay.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
```

Keep the existing 1px `QProgressBar` border and do not add padding to either the progress bar or its chunk.

- [ ] **Step 8: Run execution and camera-panel tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest \
  tests/test_execution_view_footprint.py \
  tests/test_embedded_camera_panel.py -v
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit the responsive layout**

```bash
git add ui/views/execution_view.py tests/test_execution_view_footprint.py
git commit -m "feat: prioritize execution preview space"
```

### Task 3: Align documentation and verify the delivered layout

**Files:**
- Modify: `plan.md:244-251`
- Modify: `plan.md:287`
- Verify: `ui/views/execution_view.py`
- Verify: `tests/test_execution_view_footprint.py`

**Interfaces:**
- Consumes: the completed Task 1 and Task 2 execution-page behavior
- Produces: project documentation consistent with the delivered runtime UI

- [ ] **Step 1: Update the live-display rules in `plan.md`**

Replace the first detection-process bullet with:

```markdown
- 实时检测页优先显示最大 16:9 相机、倒计时和足迹通道；不再显示已完成周期列表。
- 当前未完成周期状态只在最大相机之外仍能容纳 72px 摘要栏时显示，空间不足时自动隐藏。
```

Keep the existing bullets that define current state as temporary and completed cycle records as immutable formal data. Update the completed checklist line to:

```markdown
- [x] 在跑步机检测页以自适应摘要显示当前未完成周期；运行页不显示已完成周期列表，临时状态不得进入正式表格、统计、报告或导出。
```

- [ ] **Step 2: Run the complete targeted regression set**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest \
  tests/test_execution_view_footprint.py \
  tests/test_embedded_camera_panel.py \
  tests/test_main_window_navigation.py \
  tests/test_session_controller_lifecycle.py -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Render the 1920×1080 acceptance scenario**

Render the execution-page content size corresponding to the full-screen shell:

```bash
QT_QPA_PLATFORM=offscreen python -c 'from qtpy.QtWidgets import QApplication; from config.treadmill_config import TreadmillGaitConfig; from ui.views.execution_view import ExecutionView; app=QApplication.instance() or QApplication([]); view=ExecutionView(); view._camera_panel.start_preview=lambda: None; view.resize(1690,1050); view.show(); view.configure(TreadmillGaitConfig(stop_type="End of Time",test_length="01:00",treadmill_speed=5.0,direction="Interface side")); app.processEvents(); view._current_cycle_state.setText("右脚单支撑"); view._left_cycle_value.setText("左脚  摆动相 0.545 s"); view._right_cycle_value.setText("右脚  支撑相 0.190 s"); app.processEvents(); assert view.grab().save("/tmp/ironjump-execution-preview.png"); view.close()'
```

Inspect `/tmp/ironjump-execution-preview.png` and confirm:

- the completed-cycle table is absent;
- the preview is the largest exact 16:9 rectangle for its column;
- the 72px summary is visible and readable;
- the countdown chunk fills the column width inside its border;
- the footprint/control column spans the enlarged lower area.

- [ ] **Step 4: Render and inspect the smaller-window fallback**

Run the same command with `view.resize(1280,720)` and output `/tmp/ironjump-execution-preview-small.png`. Confirm the summary is hidden and the camera remains exact 16:9 without overlap.

- [ ] **Step 5: Commit the documentation alignment**

```bash
git add plan.md
git commit -m "docs: align live gait display rules"
```

- [ ] **Step 6: Check the final change set**

Run:

```bash
git status --short
git log -4 --oneline
```

Expected: the three implementation commits are present. Pre-existing unrelated modifications remain unstaged and unchanged.
