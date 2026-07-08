# Footprint Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live and replayable footprint-channel visualization for gait-related modes, using engine-owned canonical timeline frames as the only replay truth source.

**Architecture:** The engine/processor layer converts contact tracker state into fixed-cadence `FootprintVisualFrame` objects. Execution view and report view both render those canonical frames through a shared Qt widget; neither UI path interprets touch/lift events or maintains footprint lifecycle state.

**Tech Stack:** Python dataclasses, Qt via `qtpy`, existing `GaitEngine`, `TreadmillProcessor`, `SessionController`, `ExecutionView`, `ReportView`, pytest/pytest-qt.

---

## Scope Check

This is one cohesive feature: canonical visualization state, live rendering, and report replay. The tasks below keep the state source in the engine/report layer and only add UI after the data model and fixed-cadence recorder are tested.

## File Structure

- Create `engine/footprint_visualization.py`: pure engine-layer dataclasses and fixed-cadence recorder. No Qt imports.
- Modify `config/test_report.py`: add `visual_timeline` to `GaitTestReport`.
- Modify `config/treadmill_report.py`: add `FootprintActiveState`, `FootprintVisualFrame`, and `visual_timeline` to `TreadmillReportBase`.
- Modify `engine/modes/treadmill_processor.py`: record fixed-cadence visual frames from the existing contact tracker and expose them for live emission/report construction.
- Modify `engine/gait_engine.py`: add visual frame signal, record inline gait frames, forward treadmill processor visual frames, and include inline gait `visual_timeline` in reports.
- Modify `ui/session_controller.py`: forward the new visual frame signal.
- Modify `ui/main_window.py`: connect controller visual frames to execution view.
- Create `ui/assets/left_foot.png` and `ui/assets/right_foot.png`: processed transparent project assets.
- Create `ui/footprint_channel.py`: shared `FootprintChannelWidget` and `FootprintReplayPanel`.
- Modify `ui/views/execution_view.py`: replace gait-related bar charts with the footprint widget; keep jump charts.
- Modify `ui/views/report_view.py`: show replay panel for gait-related reports; keep jump charts and existing treadmill tables/export behavior.
- Add/modify tests in:
  - `tests/test_footprint_visualization.py`
  - `tests/test_treadmill_report.py`
  - `tests/test_treadmill_processor.py`
  - `tests/test_mode_runtime.py`
  - `tests/test_report_view.py` or existing report view tests if present
  - `tests/test_setup_view.py` only if existing UI smoke coverage needs updated expectations

---

### Task 1: Canonical Footprint Frame Model And Fixed-Cadence Recorder

**Files:**
- Create: `engine/footprint_visualization.py`
- Test: `tests/test_footprint_visualization.py`

- [ ] **Step 1: Write failing tests for frame schema and tracker-derived feet**

Create `tests/test_footprint_visualization.py` with:

```python
from engine.contact_tracker import ContactBasedGaitTracker
from engine.footprint_visualization import (
    FootprintTimelineRecorder,
    FootprintVisualFrame,
    build_visual_frame,
    led_index_to_unit_y,
)


def test_led_index_to_unit_y_bounds_and_midpoint():
    assert led_index_to_unit_y(0) == 0.0
    assert led_index_to_unit_y(95) == 1.0
    assert led_index_to_unit_y(47.5) == 0.5


def test_visual_frame_schema_has_no_presentation_opacity():
    frame = FootprintVisualFrame(timestamp_s=0.25, contact_bits=(0,) * 96)

    assert hasattr(frame, "contact_bits")
    assert hasattr(frame, "feet")
    assert not hasattr(frame, "opacity")


def test_build_visual_frame_derives_feet_from_contact_tracker():
    tracker = ContactBasedGaitTracker(
        contact_confirm_frames=1,
        contact_lift_miss_frames=2,
        min_step_interval=0.0,
        arm_frames=1,
        max_contact_age=1.0,
        min_cluster_length=10.0,
        max_centroid_jitter=10.0,
        jitter_window=1,
    )
    tracker.process_frame(0.0, [])
    tracker.process_frame(
        0.1,
        [{"track_id": 7, "centroid_cm": 21.0, "length_cm": 14.0}],
    )

    frame = build_visual_frame(0.1, [0] * 20 + [1] * 8 + [0] * 68, tracker)

    assert frame.timestamp_s == 0.1
    assert frame.contact_bits == tuple([0] * 20 + [1] * 8 + [0] * 68)
    assert len(frame.feet) == 1
    foot = frame.feet[0]
    assert foot.contact_id == 1
    assert foot.side == "unknown"
    assert foot.status == "confirmed"
    assert foot.centroid_cm == 21.0
    assert foot.length_cm == 14.0


def test_timeline_recorder_uses_fixed_cadence_without_event_boundary_inserts():
    tracker = ContactBasedGaitTracker(arm_frames=1)
    recorder = FootprintTimelineRecorder(interval_s=0.10)

    assert recorder.record_if_due(0.00, [0] * 96, tracker) is not None
    assert recorder.record_if_due(0.03, [1] * 96, tracker) is None
    assert recorder.record_if_due(0.09, [1] * 96, tracker) is None
    assert recorder.record_if_due(0.10, [1] * 96, tracker) is not None

    assert [frame.timestamp_s for frame in recorder.frames] == [0.0, 0.1]
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
pytest tests/test_footprint_visualization.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'engine.footprint_visualization'`.

- [ ] **Step 3: Implement the pure engine visualization module**

Create `engine/footprint_visualization.py`:

```python
"""Canonical footprint visualization state.

This module has no Qt dependency. It owns the engine/report representation that
both live UI and report replay render.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from engine.contact_tracker import ContactBasedGaitTracker

FootSideVisual = Literal["left", "right", "unknown"]
FootStatusVisual = Literal["candidate", "confirmed", "lifted"]


@dataclass(frozen=True)
class FootprintActiveState:
    contact_id: int
    side: FootSideVisual
    centroid_cm: float | None
    length_cm: float | None
    status: FootStatusVisual


@dataclass(frozen=True)
class FootprintVisualFrame:
    timestamp_s: float
    contact_bits: tuple[int, ...]
    feet: tuple[FootprintActiveState, ...] = ()

    def to_dict(self) -> dict:
        return {
            "timestamp_s": self.timestamp_s,
            "contact_bits": list(self.contact_bits),
            "feet": [
                {
                    "contact_id": foot.contact_id,
                    "side": foot.side,
                    "centroid_cm": foot.centroid_cm,
                    "length_cm": foot.length_cm,
                    "status": foot.status,
                }
                for foot in self.feet
            ],
        }


def led_index_to_unit_y(index: float, *, led_count: int = 96) -> float:
    if led_count <= 1:
        return 0.0
    clamped = min(max(float(index), 0.0), float(led_count - 1))
    return clamped / float(led_count - 1)


def side_from_foot_label(label: str | None) -> FootSideVisual:
    if label == "A":
        return "left"
    if label == "B":
        return "right"
    return "unknown"


def _normalized_bits(contact_bits: Sequence[int]) -> tuple[int, ...]:
    bits = tuple(1 if int(bit) else 0 for bit in contact_bits[:96])
    if len(bits) >= 96:
        return bits
    return bits + (0,) * (96 - len(bits))


def build_visual_frame(
    timestamp_s: float,
    contact_bits: Sequence[int],
    tracker: ContactBasedGaitTracker,
) -> FootprintVisualFrame:
    feet = []
    for contact in sorted(tracker.active_contacts.values(), key=lambda c: c.contact_id):
        if contact.status not in ("candidate", "confirmed", "lifted"):
            continue
        centroid = contact.latest_centroid
        if centroid is None:
            centroid = contact.centroid_at_touch
        length = contact.latest_cluster_length
        if length is None:
            length = contact.cluster_length_at_touch
        feet.append(
            FootprintActiveState(
                contact_id=contact.contact_id,
                side=side_from_foot_label(contact.foot_label),
                centroid_cm=centroid,
                length_cm=length,
                status=contact.status,
            )
        )
    return FootprintVisualFrame(
        timestamp_s=float(timestamp_s),
        contact_bits=_normalized_bits(contact_bits),
        feet=tuple(feet),
    )


class FootprintTimelineRecorder:
    def __init__(self, interval_s: float = 1.0 / 25.0) -> None:
        self.interval_s = float(interval_s)
        self._last_timestamp_s: float | None = None
        self._frames: list[FootprintVisualFrame] = []
        self._pending: list[FootprintVisualFrame] = []

    @property
    def frames(self) -> tuple[FootprintVisualFrame, ...]:
        return tuple(self._frames)

    def reset(self) -> None:
        self._last_timestamp_s = None
        self._frames.clear()
        self._pending.clear()

    def record_if_due(
        self,
        timestamp_s: float,
        contact_bits: Sequence[int],
        tracker: ContactBasedGaitTracker,
    ) -> FootprintVisualFrame | None:
        if (
            self._last_timestamp_s is not None
            and timestamp_s - self._last_timestamp_s < self.interval_s
        ):
            return None
        frame = build_visual_frame(timestamp_s, contact_bits, tracker)
        self._last_timestamp_s = float(timestamp_s)
        self._frames.append(frame)
        self._pending.append(frame)
        return frame

    def pop_pending(self) -> tuple[FootprintVisualFrame, ...]:
        pending = tuple(self._pending)
        self._pending.clear()
        return pending
```

- [ ] **Step 4: Run tests for the module**

Run:

```bash
pytest tests/test_footprint_visualization.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add engine/footprint_visualization.py tests/test_footprint_visualization.py
git commit -m "feat: add canonical footprint visualization frames"
```

---

### Task 2: Add Canonical Timeline Fields To Report Models

**Files:**
- Modify: `config/test_report.py`
- Modify: `config/treadmill_report.py`
- Test: `tests/test_treadmill_report.py`
- Test: `tests/test_engine_protection.py`

- [ ] **Step 1: Write failing tests for report defaults**

Append to `tests/test_treadmill_report.py`:

```python
from engine.footprint_visualization import FootprintVisualFrame


def test_treadmill_report_defaults_visual_timeline_to_empty_tuple():
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
    )

    assert report.visual_timeline == ()


def test_treadmill_report_accepts_visual_timeline_frames():
    frame = FootprintVisualFrame(timestamp_s=0.0, contact_bits=(0,) * 96)
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        visual_timeline=(frame,),
    )

    assert report.visual_timeline == (frame,)
```

Append to `tests/test_engine_protection.py`:

```python
def test_gait_report_defaults_visual_timeline_to_empty_tuple():
    report = GaitTestReport(
        touch_count=0,
        lift_count=0,
        stride_lengths=(),
        velocities=(),
        avg_stride=0.0,
        max_stride=0.0,
        avg_velocity=0.0,
        max_velocity=0.0,
    )

    assert report.visual_timeline == ()
```

- [ ] **Step 2: Run the report model tests and verify failure**

Run:

```bash
pytest tests/test_treadmill_report.py::test_treadmill_report_defaults_visual_timeline_to_empty_tuple tests/test_treadmill_report.py::test_treadmill_report_accepts_visual_timeline_frames tests/test_engine_protection.py::test_gait_report_defaults_visual_timeline_to_empty_tuple -v
```

Expected: FAIL with `AttributeError` or unexpected keyword argument for `visual_timeline`.

- [ ] **Step 3: Add timeline fields**

Modify `config/test_report.py` `GaitTestReport`:

```python
@dataclass(frozen=True)
class GaitTestReport:
    """步态测试结果快照（不可变）"""
    touch_count: int
    lift_count: int
    stride_lengths: tuple
    velocities: tuple
    avg_stride: float
    max_stride: float
    avg_velocity: float
    max_velocity: float
    foot_a_support_times: tuple = ()
    foot_b_support_times: tuple = ()
    imbalance_index: Optional[float] = None
    avg_double_support: Optional[float] = None
    avg_single_support: Optional[float] = None
    avg_acceleration: Optional[float] = None
    finish_reason: str = "manual"
    export_frames: tuple = ()
    export_timestamps: tuple = ()
    visual_timeline: tuple = ()
```

Modify `config/treadmill_report.py` `TreadmillReportBase`:

```python
@dataclass(frozen=True)
class TreadmillReportBase:
    """跑步机测试报告基类，包含所有公共字段。"""
    finish_reason: str
    touch_count: int
    lift_count: int
    resolved_starting_foot: FootSide
    starting_foot_source: StartingFootSource
    foot_length_cm_snapshot: float | None = None
    foot_length_source: str = "unknown"
    per_step_results: tuple[TreadmillStepResult, ...] = ()
    metric_summaries: dict[str, MetricSummary] = field(default_factory=dict)
    left_right_results: dict[str, MetricSummary] = field(default_factory=dict)
    asymmetry_metrics: dict[str, float] = field(default_factory=dict)
    report_config_snapshot: dict[str, Any] = field(default_factory=dict)
    export_frames: tuple = ()
    export_timestamps: tuple = ()
    visual_timeline: tuple = ()
```

- [ ] **Step 4: Run the targeted tests**

Run:

```bash
pytest tests/test_treadmill_report.py::test_treadmill_report_defaults_visual_timeline_to_empty_tuple tests/test_treadmill_report.py::test_treadmill_report_accepts_visual_timeline_frames tests/test_engine_protection.py::test_gait_report_defaults_visual_timeline_to_empty_tuple -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add config/test_report.py config/treadmill_report.py tests/test_treadmill_report.py tests/test_engine_protection.py
git commit -m "feat: add footprint visual timeline to reports"
```

---

### Task 3: Generate Fixed-Cadence Visual Frames In Engine And Treadmill Processor

**Files:**
- Modify: `engine/modes/treadmill_processor.py`
- Modify: `engine/gait_engine.py`
- Test: `tests/test_treadmill_processor.py`
- Test: `tests/test_mode_runtime.py`

- [ ] **Step 1: Write failing tests for treadmill timeline and live frame extraction**

Append to `tests/test_treadmill_processor.py`:

```python
def test_treadmill_processor_records_fixed_cadence_visual_timeline():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    processor.process_raw_frame([0] * 96, rel_time=0.00, abs_time=0.00)
    processor.process_raw_frame([1] * 96, rel_time=0.01, abs_time=0.01)
    processor.process_raw_frame([1] * 96, rel_time=0.05, abs_time=0.05)
    report = processor.build_report(reason="manual", export_frames=(), export_timestamps=())

    assert [frame.timestamp_s for frame in report.visual_timeline] == [0.0, 0.05]
    assert report.visual_timeline[1].contact_bits == tuple([1] * 96)


def test_treadmill_processor_pop_visual_frames_returns_pending_once():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    processor.process_raw_frame([0] * 96, rel_time=0.00, abs_time=0.00)

    first = processor.pop_visual_frames()
    second = processor.pop_visual_frames()

    assert len(first) == 1
    assert second == ()
```

Append to `tests/test_mode_runtime.py`:

```python
def test_gait_engine_emits_treadmill_visual_frame(qtbot):
    from qtpy.QtTest import QSignalSpy

    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    engine = GaitEngine(config=config)
    spy = QSignalSpy(engine.footprint_visual_frame)

    engine.process_raw_frame([0] * 96, 0.001)

    assert spy.count() == 1
    payload = spy.at(0)[0]
    assert payload["timestamp_s"] == 0.0
    assert payload["contact_bits"] == [0] * 96
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_treadmill_processor.py::test_treadmill_processor_records_fixed_cadence_visual_timeline tests/test_treadmill_processor.py::test_treadmill_processor_pop_visual_frames_returns_pending_once tests/test_mode_runtime.py::test_gait_engine_emits_treadmill_visual_frame -v
```

Expected: FAIL because visual timeline APIs and signal do not exist.

- [ ] **Step 3: Add recorder to treadmill processor**

Modify imports in `engine/modes/treadmill_processor.py`:

```python
from engine.footprint_visualization import FootprintTimelineRecorder
```

In `TreadmillProcessor.__init__` add:

```python
self._visual_recorder = FootprintTimelineRecorder()
```

In `reset()` add:

```python
self._visual_recorder.reset()
```

In `process_raw_frame()` after `events = self._contact_tracker.process_frame(...)` add:

```python
self._visual_recorder.record_if_due(
    rel_time,
    contact_bits,
    self._contact_tracker,
)
```

Add method:

```python
def pop_visual_frames(self):
    return self._visual_recorder.pop_pending()
```

In `build_report()` add to `base_kwargs`:

```python
visual_timeline=self._visual_recorder.frames,
```

- [ ] **Step 4: Add live visual signal and inline gait recorder to `GaitEngine`**

Modify imports in `engine/gait_engine.py`:

```python
from .footprint_visualization import FootprintTimelineRecorder
```

Add signal to `GaitEngine`:

```python
footprint_visual_frame = Signal(dict)
```

In `__init__` add:

```python
self._visual_recorder = FootprintTimelineRecorder()
```

In `reset()` add:

```python
self._visual_recorder.reset()
```

In `process_raw_frame()`, after non-jump processor event emission, add:

```python
if not isinstance(self._processor, JumpProcessor) and hasattr(self._processor, "pop_visual_frames"):
    for frame in self._processor.pop_visual_frames():
        self.footprint_visual_frame.emit(frame.to_dict())
```

In `_process_gait()` after touch/lift event emission add:

```python
frame = self._visual_recorder.record_if_due(rel_time, bits, self._contact_tracker)
if frame is not None:
    self.footprint_visual_frame.emit(frame.to_dict())
```

In `_build_gait_report()` add:

```python
visual_timeline=self._visual_recorder.frames,
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
pytest tests/test_treadmill_processor.py::test_treadmill_processor_records_fixed_cadence_visual_timeline tests/test_treadmill_processor.py::test_treadmill_processor_pop_visual_frames_returns_pending_once tests/test_mode_runtime.py::test_gait_engine_emits_treadmill_visual_frame -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add engine/modes/treadmill_processor.py engine/gait_engine.py tests/test_treadmill_processor.py tests/test_mode_runtime.py
git commit -m "feat: record canonical footprint visual timeline"
```

---

### Task 4: Forward Canonical Frames Through Controller To Execution View

**Files:**
- Modify: `ui/session_controller.py`
- Modify: `ui/main_window.py`
- Modify: `ui/views/execution_view.py`
- Test: `tests/test_mode_runtime.py`

- [ ] **Step 1: Write failing signal plumbing test**

Append to `tests/test_mode_runtime.py`:

```python
def test_session_controller_exposes_footprint_visual_signal(qtbot):
    from ui.session_controller import SessionController

    controller = SessionController()

    assert hasattr(controller, "footprint_visual_frame")
```

- [ ] **Step 2: Run the signal test and verify failure**

Run:

```bash
pytest tests/test_mode_runtime.py::test_session_controller_exposes_footprint_visual_signal -v
```

Expected: FAIL because `SessionController.footprint_visual_frame` does not exist.

- [ ] **Step 3: Add controller signal forwarding**

Modify `ui/session_controller.py`:

```python
footprint_visual_frame = Signal(dict)    # canonical footprint frame for live rendering
```

In `prepare()` after `gait_status_snapshot` connection:

```python
self._engine.footprint_visual_frame.connect(self._on_footprint_visual_frame)
```

Add slot:

```python
@Slot(dict)
def _on_footprint_visual_frame(self, frame):
    self.footprint_visual_frame.emit(frame)
```

- [ ] **Step 4: Connect controller to execution view**

Modify `ui/main_window.py` `_connect_signals()`:

```python
self._controller.footprint_visual_frame.connect(self._exec_view.on_footprint_visual_frame)
```

Modify `ui/views/execution_view.py` with a temporary storage method before the widget is added:

```python
def on_footprint_visual_frame(self, frame: dict):
    self._latest_footprint_frame = frame
    if hasattr(self, "_footprint_channel"):
        self._footprint_channel.render_state(frame)
```

In `ExecutionView.__init__` add:

```python
self._latest_footprint_frame = None
```

- [ ] **Step 5: Run signal test**

Run:

```bash
pytest tests/test_mode_runtime.py::test_session_controller_exposes_footprint_visual_signal -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add ui/session_controller.py ui/main_window.py ui/views/execution_view.py tests/test_mode_runtime.py
git commit -m "feat: forward footprint visual frames to execution view"
```

---

### Task 5: Add Project Foot Assets And Shared Footprint Channel Widget

**Files:**
- Create: `ui/assets/left_foot.png`
- Create: `ui/assets/right_foot.png`
- Create: `ui/footprint_channel.py`
- Test: `tests/test_footprint_channel.py`

- [ ] **Step 1: Create transparent project foot assets**

Run:

```bash
mkdir -p ui/assets
/Users/vae/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -c "from PIL import Image; pairs=[('/Users/vae/Downloads/feet_white_background_highres/left_foot_white_background_highres.png','ui/assets/left_foot.png'),('/Users/vae/Downloads/feet_white_background_highres/right_foot_white_background_highres.png','ui/assets/right_foot.png')];\
for src,dst in pairs:\
    im=Image.open(src).convert('RGBA'); px=im.load();\
    w,h=im.size;\
    for y in range(h):\
        for x in range(w):\
            r,g,b,a=px[x,y];\
            if r>245 and g>245 and b>245: px[x,y]=(255,255,255,0);\
    im.save(dst)"
```

Expected: `ui/assets/left_foot.png` and `ui/assets/right_foot.png` exist.

- [ ] **Step 2: Write failing widget tests**

Create `tests/test_footprint_channel.py`:

```python
import pytest

pytest.importorskip("qtpy")

from ui.footprint_channel import FootprintChannelWidget, FootprintReplayPanel


def test_channel_widget_accepts_short_frame_without_resizing(qtbot):
    widget = FootprintChannelWidget()
    qtbot.addWidget(widget)

    widget.render_state({"timestamp_s": 0.0, "contact_bits": [1, 0, 1], "feet": []})

    assert widget._contact_bits[:3] == [1, 0, 1]
    assert len(widget._contact_bits) == 96


def test_channel_widget_does_not_store_opacity_state(qtbot):
    widget = FootprintChannelWidget()
    qtbot.addWidget(widget)
    frame = {
        "timestamp_s": 0.0,
        "contact_bits": [0] * 96,
        "feet": [{"contact_id": 1, "side": "left", "status": "candidate"}],
    }

    widget.render_state(frame)

    assert "opacity" not in widget._feet[0]


def test_replay_panel_renders_first_timeline_frame(qtbot):
    panel = FootprintReplayPanel()
    qtbot.addWidget(panel)
    timeline = (
        {"timestamp_s": 0.0, "contact_bits": [0] * 96, "feet": []},
        {"timestamp_s": 0.1, "contact_bits": [1] * 96, "feet": []},
    )

    panel.set_timeline(timeline)

    assert panel._timeline == list(timeline)
    assert panel._channel._contact_bits == [0] * 96
```

- [ ] **Step 3: Run widget tests and verify failure**

Run:

```bash
pytest tests/test_footprint_channel.py -v
```

Expected: FAIL because `ui.footprint_channel` does not exist.

- [ ] **Step 4: Implement shared widget and replay panel**

Create `ui/footprint_channel.py` with:

```python
"""Shared footprint-channel visualization widgets."""

from __future__ import annotations

import os

from qtpy.QtCore import Qt, QTimer
from qtpy.QtGui import QColor, QPainter, QPixmap
from qtpy.QtWidgets import QFrame, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from dayu_widgets.push_button import MPushButton

from path_utils import get_base_dir


class FootprintChannelWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._contact_bits = [0] * 96
        self._feet: list[dict] = []
        self._left_foot = self._load_pixmap("left_foot.png")
        self._right_foot = self._load_pixmap("right_foot.png")
        self.setMinimumSize(260, 420)
        self.setStyleSheet(
            "FootprintChannelWidget { background-color: rgba(20, 20, 24, 0.9); "
            "border: 1px solid rgba(90, 90, 95, 0.7); border-radius: 8px; }"
        )

    def _load_pixmap(self, name: str) -> QPixmap:
        path = os.path.join(get_base_dir(), "ui", "assets", name)
        pixmap = QPixmap(path)
        return pixmap

    def clear(self):
        self._contact_bits = [0] * 96
        self._feet = []
        self.update()

    def render_state(self, frame):
        if hasattr(frame, "to_dict"):
            frame = frame.to_dict()
        bits = [1 if int(bit) else 0 for bit in frame.get("contact_bits", [])[:96]]
        if len(bits) < 96:
            bits.extend([0] * (96 - len(bits)))
        self._contact_bits = bits
        self._feet = [
            {key: value for key, value in dict(foot).items() if key != "opacity"}
            for foot in frame.get("feet", [])
        ]
        self.update()

    def _y_for_index(self, index: float, top: int, height: int) -> float:
        clamped = min(max(float(index), 0.0), 95.0)
        return top + (clamped / 95.0) * height

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(14, 14, -14, -14)
        rail_left_x = rect.left() + 12
        rail_right_x = rect.right() - 12
        lane_left = rail_left_x + 22
        lane_right = rail_right_x - 22
        top = rect.top() + 20
        height = rect.height() - 40

        painter.setPen(QColor(70, 70, 76))
        painter.setBrush(QColor(28, 28, 32))
        painter.drawRoundedRect(lane_left, top, lane_right - lane_left, height, 8, 8)

        for idx, active in enumerate(self._contact_bits):
            y = self._y_for_index(idx, top, height)
            color = QColor(70, 220, 125) if active else QColor(70, 70, 76)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rail_left_x - 3, int(y) - 2, 6, 4, 2, 2)
            painter.drawRoundedRect(rail_right_x - 3, int(y) - 2, 6, 4, 2, 2)
            if active:
                painter.setPen(QColor(70, 220, 125, 60))
                painter.drawLine(lane_left, int(y), lane_right, int(y))

        for foot in self._feet:
            self._paint_foot(painter, foot, lane_left, lane_right, top, height)

    def _paint_foot(self, painter, foot: dict, lane_left: int, lane_right: int, top: int, height: int):
        centroid_cm = foot.get("centroid_cm")
        if centroid_cm is None:
            return
        index = float(centroid_cm) / 1.04
        y = self._y_for_index(index, top, height)
        side = foot.get("side", "unknown")
        status = foot.get("status", "confirmed")
        alpha = 255 if status == "confirmed" else 130
        color = QColor(82, 170, 255, alpha) if side == "right" else QColor(82, 220, 130, alpha)
        pixmap = self._right_foot if side == "right" else self._left_foot
        foot_w = max(42, int((lane_right - lane_left) * 0.34))
        foot_h = int(foot_w * 1.62)
        x_center = lane_left + (lane_right - lane_left) * (0.64 if side == "right" else 0.36)
        target_x = int(x_center - foot_w / 2)
        target_y = int(y - foot_h / 2)

        if not pixmap.isNull():
            tinted = QPixmap(pixmap.size())
            tinted.fill(Qt.transparent)
            tint_painter = QPainter(tinted)
            tint_painter.drawPixmap(0, 0, pixmap)
            tint_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            tint_painter.fillRect(tinted.rect(), color)
            tint_painter.end()
            painter.drawPixmap(target_x, target_y, foot_w, foot_h, tinted)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(target_x, target_y, foot_w, foot_h)


class FootprintReplayPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._timeline: list = []
        self._index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._channel = FootprintChannelWidget()
        layout.addWidget(self._channel, 1)

        controls = QHBoxLayout()
        self._btn_play = MPushButton("播放")
        self._btn_play.clicked.connect(self._toggle_playback)
        controls.addWidget(self._btn_play)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.valueChanged.connect(self._on_slider_changed)
        controls.addWidget(self._slider, 1)
        self._time_label = QLabel("0.000 s")
        controls.addWidget(self._time_label)
        layout.addLayout(controls)

    def set_timeline(self, timeline):
        self._timer.stop()
        self._btn_play.setText("播放")
        self._timeline = [frame.to_dict() if hasattr(frame, "to_dict") else frame for frame in timeline]
        self._index = 0
        self._slider.setMaximum(max(len(self._timeline) - 1, 0))
        self._slider.setValue(0)
        if self._timeline:
            self._render_index(0)
        else:
            self._channel.clear()
            self._time_label.setText("无回放数据")

    def _toggle_playback(self):
        if not self._timeline:
            return
        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText("播放")
        else:
            self._timer.start(40)
            self._btn_play.setText("暂停")

    def _advance(self):
        if not self._timeline:
            self._timer.stop()
            return
        next_index = self._index + 1
        if next_index >= len(self._timeline):
            self._timer.stop()
            self._btn_play.setText("播放")
            return
        self._slider.setValue(next_index)

    def _on_slider_changed(self, value: int):
        if self._timeline:
            self._render_index(value)

    def _render_index(self, index: int):
        self._index = max(0, min(index, len(self._timeline) - 1))
        frame = self._timeline[self._index]
        self._channel.render_state(frame)
        self._time_label.setText(f"{frame.get('timestamp_s', 0.0):.3f} s")
```

- [ ] **Step 5: Run widget tests**

Run:

```bash
pytest tests/test_footprint_channel.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add ui/assets/left_foot.png ui/assets/right_foot.png ui/footprint_channel.py tests/test_footprint_channel.py
git commit -m "feat: add footprint channel widget"
```

---

### Task 6: Replace Gait-Related Execution Charts With Live Footprint Channel

**Files:**
- Modify: `ui/views/execution_view.py`
- Test: `tests/test_setup_view.py` or create `tests/test_execution_view_footprint.py`

- [ ] **Step 1: Write failing execution view tests**

Create `tests/test_execution_view_footprint.py`:

```python
import pytest

pytest.importorskip("dayu_widgets")

from config.test_config import TestConfig
from config.treadmill_config import TreadmillGaitConfig
from ui.footprint_channel import FootprintChannelWidget
from ui.views.execution_view import ExecutionView


def test_execution_view_shows_footprint_channel_for_treadmill(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)

    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    assert isinstance(view._footprint_channel, FootprintChannelWidget)
    assert view._footprint_channel.isVisible()
    assert not view._chart_container.isVisible()


def test_execution_view_keeps_jump_charts_for_jump(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    config = TestConfig(test_type="Jump Test")

    view.configure(config)

    assert view._chart_container.isVisible()
    assert not view._footprint_channel.isVisible()
```

- [ ] **Step 2: Run execution view tests and verify failure**

Run:

```bash
pytest tests/test_execution_view_footprint.py -v
```

Expected: FAIL because `_footprint_channel` and `_chart_container` are not defined.

- [ ] **Step 3: Add chart container and footprint channel**

Modify imports in `ui/views/execution_view.py`:

```python
from ui.footprint_channel import FootprintChannelWidget
```

In `_build_ui()`, wrap the existing chart layout in `self._chart_container` and add `self._footprint_channel`:

```python
self._chart_container = QWidget()
self._chart_container.setLayout(charts_layout)
main_layout.addWidget(self._chart_container, 1)

self._footprint_channel = FootprintChannelWidget()
self._footprint_channel.hide()
main_layout.addWidget(self._footprint_channel, 1)
```

Remove the current direct call:

```python
main_layout.addLayout(charts_layout, 1)
```

In `configure()` after `is_jump = self._mode == "纵跳"` add:

```python
self._chart_container.setVisible(is_jump)
self._footprint_channel.setVisible(not is_jump)
```

In `reset()` add:

```python
if hasattr(self, "_footprint_channel"):
    self._footprint_channel.clear()
```

In `on_footprint_visual_frame()` replace the temporary method from Task 4 with:

```python
def on_footprint_visual_frame(self, frame: dict):
    self._latest_footprint_frame = frame
    if self._mode != "纵跳":
        self._footprint_channel.render_state(frame)
```

- [ ] **Step 4: Stop gait events from updating hidden bar charts**

Modify `on_gait_step_event()`:

```python
def on_gait_step_event(self, ev):
    """接收步态事件。图表已由足迹通道替代，保留事件入口用于兼容。"""
    return
```

- [ ] **Step 5: Run execution view tests**

Run:

```bash
pytest tests/test_execution_view_footprint.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add ui/views/execution_view.py tests/test_execution_view_footprint.py
git commit -m "feat: show live footprint channel during gait execution"
```

---

### Task 7: Add Report Replay Panel For Gait-Related Reports

**Files:**
- Modify: `ui/views/report_view.py`
- Test: `tests/test_treadmill_report.py` or create `tests/test_report_view_footprint.py`

- [ ] **Step 1: Write failing report view tests**

Create `tests/test_report_view_footprint.py`:

```python
import pytest

pytest.importorskip("dayu_widgets")

from config.treadmill_report import TreadmillGaitReport
from engine.footprint_visualization import FootprintVisualFrame
from ui.footprint_channel import FootprintReplayPanel
from ui.views.report_view import ReportView


def test_report_view_shows_replay_panel_for_treadmill_report(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert isinstance(view._replay_panel, FootprintReplayPanel)
    assert view._replay_panel.isVisible()
    assert view._replay_panel._timeline[0]["timestamp_s"] == 0.0
```

- [ ] **Step 2: Run report view test and verify failure**

Run:

```bash
pytest tests/test_report_view_footprint.py -v
```

Expected: FAIL because `_replay_panel` is not defined.

- [ ] **Step 3: Add replay panel to report view**

Modify imports in `ui/views/report_view.py`:

```python
from ui.footprint_channel import FootprintReplayPanel
```

In `_build_ui()`, after right layout creation and divider, add:

```python
self._right_layout = right_layout
self._replay_panel = FootprintReplayPanel()
self._replay_panel.hide()
right_layout.addWidget(self._replay_panel, 1)
```

Create a plot container for existing plots:

```python
self._plot_container = QWidget()
self._plot_container_layout = QVBoxLayout(self._plot_container)
self._plot_container_layout.setContentsMargins(0, 0, 0, 0)
self._plot_container_layout.setSpacing(8)
```

Add `_plot_1` and `_plot_2` to `self._plot_container_layout` instead of `right_layout`, then add:

```python
right_layout.addWidget(self._plot_container, 1)
```

In `load_report()` before dispatching report type add:

```python
if hasattr(self, "_replay_panel"):
    self._replay_panel.hide()
if hasattr(self, "_plot_container"):
    self._plot_container.show()
```

In `_load_gait_report()` and `_load_treadmill_report()` add:

```python
self._plot_container.hide()
self._replay_panel.show()
self._replay_panel.set_timeline(getattr(r, "visual_timeline", ()))
```

Keep `_load_jump_report()` using the existing plot container.

- [ ] **Step 4: Run report view test**

Run:

```bash
pytest tests/test_report_view_footprint.py -v
```

Expected: PASS.

- [ ] **Step 5: Run existing report tests**

Run:

```bash
pytest tests/test_treadmill_report.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add ui/views/report_view.py tests/test_report_view_footprint.py
git commit -m "feat: add footprint replay to reports"
```

---

### Task 8: Final Verification And Cleanup

**Files:**
- Verify all files touched in previous tasks.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
pytest tests/test_footprint_visualization.py tests/test_footprint_channel.py tests/test_execution_view_footprint.py tests/test_report_view_footprint.py tests/test_treadmill_processor.py tests/test_treadmill_report.py tests/test_setup_view.py tests/test_mode_runtime.py -v
```

Expected: PASS.

- [ ] **Step 2: Run import boundary checks**

Run:

```bash
pytest tests/test_agent_import_boundary.py tests/test_engine_protection.py -v
```

Expected: PASS.

- [ ] **Step 3: Inspect git diff for unintended files**

Run:

```bash
git status --short
git diff --stat
```

Expected: only files intentionally touched by the plan are modified or staged. Pre-existing unrelated worktree changes remain unstaged.

- [ ] **Step 4: Confirm Task 8 made no file changes**

Run:

```bash
git diff --stat
```

Expected: no diff produced by Task 8. If this command prints a diff, stop execution and review the changed files before continuing.

## Self-Review

Spec coverage:

- Live footprint channel: Task 3 records frames, Task 4 forwards them, Task 6 renders them.
- Remove gait-related execution bar charts: Task 6.
- Report replay: Task 2 adds report data, Task 3 records timeline, Task 7 renders replay controls.
- Single canonical state source: Task 1 defines frames/recorder, Task 3 uses recorder, Task 5/6/7 render frames without event interpretation.
- No UI presentation in core state: Task 1 tests schema; Task 5 applies opacity/color locally.
- Fixed cadence only: Task 1 recorder test; Task 3 processor timeline test.
- Existing jump behavior: Task 6 test keeps jump charts visible.

Placeholder scan:

- The plan contains no open implementation placeholders. Each task has concrete files, code snippets, commands, and expected outcomes.

Type consistency:

- Canonical model names are `FootprintActiveState` and `FootprintVisualFrame`.
- Report field is consistently `visual_timeline`.
- UI render method is consistently `render_state(frame)`.
