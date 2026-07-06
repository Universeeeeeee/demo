# Footprint Visualization Design

Date: 2026-07-06

## Context

The gait and treadmill modes currently show metric cards plus two pyqtgraph bar charts during execution. The hardware model for the new visualization is:

- The device has two physical LED rails.
- Each side has 96 LEDs.
- The software receives 96 `contact_bits`; each bit represents one cross-beam/channel between the two rails.
- A foot should be drawn in the channel between the rails, not outside the LED rails.

The approved report requirement is replay only: the report page should replay the captured LED and footprint state over time, without adding a separate static footprint overview.

## Goals

1. Show a live footprint channel during gait-related detection modes.
2. Remove the two execution-page bar charts for gait/treadmill modes and use that space for the footprint channel.
3. Add replay controls to gait-related reports so the user can play back LED state and footprints by time.
4. Keep the visualization data flow aligned with the existing tracking pipeline instead of re-running tracking inside the UI.
5. Preserve existing metric cards, report tables, Excel export behavior, and jump-mode behavior unless explicitly changed later.

## Non-Goals

- Do not redesign jump-test visualization in this change.
- Do not add a static footprint distribution summary to the report page.
- Do not change gait/treadmill timing or metric formulas.
- Do not make the UI depend on image files from `Downloads`; production assets must live inside the project.

## Recommended Approach

Use an integrated visualization data flow:

1. The algorithm layer continues to parse 96-bit contact frames, extract clusters, track contacts, and emit gait step events.
2. The algorithm/session layer emits a throttled live visualization snapshot for the execution page.
3. The gait and treadmill processing paths record lightweight footprint events while processing touch/lift events.
4. The final gait-related report stores `export_frames`, `export_timestamps`, and `footprint_events`.
5. The report view replays LED frames and footprint events without recomputing gait tracking.

This keeps the UI focused on rendering and avoids a second algorithm path in the report page.

## UI Design

### Shared Footprint Channel Widget

Add a reusable Qt widget, likely `ui/footprint_channel.py`.

The widget renders:

- Left rail: 96 vertically arranged LED markers.
- Right rail: 96 vertically arranged LED markers.
- Center lane: left/right footprint images placed between the rails.
- Active beam segments derived from 96-bit `contact_bits`.
- Footprints derived from contact events or current active contacts.

Coordinate mapping:

- `index = 0..95`
- `distance_cm = index * spacing_cm`
- `y = distance_cm / total_distance_cm * drawable_height`
- Initial orientation: LED 0 is at the top and LED 95 is at the bottom.

The widget should expose:

- `set_live_snapshot(snapshot: dict)`: update the current LED frame and active footprints.
- `set_replay_frame(frame: dict)`: update the frame shown by report replay.
- `clear()`: reset LEDs and footprints.

Visual rules:

- Inactive LEDs use a muted gray.
- Active LEDs/beam segments use a clear highlight.
- A touching foot is drawn solid.
- A lifted/recent foot may fade out only if the replay frame still includes it.
- Left and right footprints use separate assets.

### Execution View

For gait-related modes:

- Replace the two pyqtgraph bar charts with the footprint channel widget.
- Keep the top status row and core metric cards.
- Use a practical split layout: footprint channel as the main visual area, metric cards and controls arranged beside or above it depending on existing space.

For jump mode:

- Keep the current charts and layout unchanged.

### Report View

For gait-related reports:

- Add a replay panel containing the footprint channel widget.
- Add playback controls: play/pause button, time slider, current time label.
- Replay should advance through `export_timestamps` and `export_frames`.
- Footprints should be shown based on `footprint_events` active at the current replay time.

If replay data is unavailable, show a compact placeholder and keep the statistics/tables usable.

## Data Model

Add a lightweight immutable report event model, for example:

```python
@dataclass(frozen=True)
class FootprintEvent:
    contact_id: int
    side: FootSide
    touch_time_s: float
    lift_time_s: float | None
    centroid_cm: float | None
    length_cm: float | None
```

Add to gait-related report models, including `GaitTestReport` and `TreadmillReportBase`:

```python
footprint_events: tuple[FootprintEvent, ...] = ()
```

The event should be populated from `GaitStepEvent.contact` data in the inline gait path and treadmill processor path. The report replay can derive whether a foot is active with:

```python
touch_time_s <= replay_time <= lift_time_s
```

If `lift_time_s` is missing, the event remains visible until the next event for that contact or until replay end.

## Live Snapshot Shape

A live visualization snapshot can be a dict to avoid forcing UI imports into the engine:

```python
{
    "timestamp": rel_time,
    "contact_bits": list[int],  # length 96
    "contacts": [
        {
            "contact_id": int,
            "side": "left" | "right" | "unknown",
            "status": "candidate" | "confirmed" | "lifted",
            "centroid_cm": float | None,
            "length_cm": float | None,
        },
    ],
}
```

Emit this snapshot at a UI-safe rate, roughly 20-30 Hz. The existing gait status snapshot can remain for metric cards.

## Assets

Use the uploaded left/right foot images as the visual source, but store processed transparent PNG assets in the project, for example:

- `ui/assets/left_foot.png`
- `ui/assets/right_foot.png`

If an asset fails to load, the widget should draw a simple fallback footprint shape so the UI does not go blank.

## Error Handling

- If `contact_bits` is missing or shorter than 96, render available bits and leave the rest inactive.
- If `footprint_events` is empty, replay LEDs only.
- If pyqtgraph is unavailable, this change should not affect the footprint widget because it uses Qt painting, not pyqtgraph.
- Unknown foot side should render in a neutral color or use the left/right asset based on alternating contact order only if already resolved by the tracker.

## Testing

Unit tests:

- LED index-to-y mapping handles index 0, 95, and midpoints.
- The widget accepts 96-bit frames and does not resize or throw on short frames.
- Footprint event active-window logic works for touch/lift/replay-end cases.
- Gait-related reports default `footprint_events=()` for backward compatibility.

Integration/smoke tests:

- `ExecutionView` in gait-related mode creates and updates the footprint widget.
- `ExecutionView` in jump mode still creates existing charts.
- `ReportView` loads a gait-related report with replay data.
- `ReportView` loads older reports without replay data.

Regression tests to run:

- `tests/test_treadmill_processor.py`
- `tests/test_treadmill_report.py`
- `tests/test_setup_view.py`
- `tests/test_mode_runtime.py`

## Acceptance Criteria

- During gait/treadmill detection, the user sees two vertical 96-LED rails with footprints rendered between them.
- Gait/treadmill execution view no longer shows the two bar charts.
- Report page can replay LED frames and matching footprint states with play/pause and a time slider.
- Existing treadmill metrics, report tables, and export behavior still work.
- Existing jump-mode UI remains unchanged.
