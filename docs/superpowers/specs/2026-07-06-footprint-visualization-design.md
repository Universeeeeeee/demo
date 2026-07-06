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
4. Keep one canonical visualization state source for both live display and report replay.
5. Preserve existing metric cards, report tables, Excel export behavior, and jump-mode behavior unless explicitly changed later.

## Non-Goals

- Do not redesign jump-test visualization in this change.
- Do not add a static footprint distribution summary to the report page.
- Do not change gait/treadmill timing or metric formulas.
- Do not make the UI depend on image files from `Downloads`; production assets must live inside the project.

## Recommended Approach

Use an integrated visualization data flow with a single state owner:

1. The algorithm layer continues to parse 96-bit contact frames, extract clusters, track contacts, and emit gait step events.
2. The engine/processor layer converts tracker state into canonical visualization frames.
3. The same canonical frame shape is used for live display and report replay.
4. The final gait-related report stores a `visual_timeline` tuple of canonical frames.
5. The report view replays `visual_timeline` directly without interpreting events or recomputing gait tracking.

This keeps the UI focused on rendering and avoids a second algorithm path in the report page. Touch/lift events remain useful for metrics and optional diagnostics, but they are not the replay truth source.

## UI Design

### Shared Footprint Channel Widget

Add a reusable Qt widget, likely `ui/footprint_channel.py`.

The widget renders:

- Left rail: 96 vertically arranged LED markers.
- Right rail: 96 vertically arranged LED markers.
- Center lane: left/right footprint images placed between the rails.
- Active beam segments derived from 96-bit `contact_bits`.
- Footprints rendered from canonical frame state produced by the engine/report layer.

Coordinate mapping:

- `index = 0..95`
- `distance_cm = index * spacing_cm`
- `y = distance_cm / total_distance_cm * drawable_height`
- Initial orientation: LED 0 is at the top and LED 95 is at the bottom.

The widget should expose:

- `render_state(frame: FootprintVisualFrame | dict)`: render one canonical visualization frame.
- `clear()`: reset LEDs and footprints.

Visual rules:

- Inactive LEDs use a muted gray.
- Active LEDs/beam segments use a clear highlight.
- A touching foot is drawn solid.
- A lifted/recent foot is shown only if the canonical frame includes it.
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
- Replay should advance through `visual_timeline`.
- Each replay tick passes exactly one canonical frame to the shared footprint channel widget.

If replay data is unavailable, show a compact placeholder and keep the statistics/tables usable.

## Data Model

Add lightweight immutable visualization state models. Names can be adjusted during implementation, but the ownership boundary should remain: engine/report layer computes state, UI renders state.

```python
@dataclass(frozen=True)
class FootprintActiveState:
    contact_id: int
    side: FootSide
    centroid_cm: float | None
    length_cm: float | None
    status: Literal["candidate", "confirmed", "lifted"]
    opacity: float = 1.0


@dataclass(frozen=True)
class FootprintVisualFrame:
    timestamp_s: float
    contact_bits: tuple[int, ...]  # length 96, one bit per cross-beam/channel
    feet: tuple[FootprintActiveState, ...] = ()
```

Add to gait-related report models, including `GaitTestReport` and `TreadmillReportBase`:

```python
visual_timeline: tuple[FootprintVisualFrame, ...] = ()
```

The canonical frame should be built from current `ContactBasedGaitTracker` state at a fixed visualization cadence. It should include all state the UI needs to draw the current moment. The UI must not infer active windows from touch/lift events.

`FootprintEvent` may still be added later as optional derived diagnostic data, but it is not required for this feature and must not be used as the replay state source.

## Canonical Frame Shape

The live frame and report frame use the same semantic shape. A dict can be used at signal boundaries to avoid forcing UI imports into the engine:

```python
{
    "timestamp_s": rel_time,
    "contact_bits": list[int],  # length 96
    "feet": [
        {
            "contact_id": int,
            "side": "left" | "right" | "unknown",
            "status": "candidate" | "confirmed" | "lifted",
            "centroid_cm": float | None,
            "length_cm": float | None,
            "opacity": float,
        },
    ],
}
```

Emit/store these frames at a UI-safe deterministic cadence, roughly 20-30 Hz, plus event-boundary frames when needed to avoid missing fast touch/lift transitions. The existing gait status snapshot can remain for metric cards, but it is not a footprint replay source.

## State Ownership

The engine/processor/report layer is the only footprint state machine owner.

It is responsible for:

- Deciding which contacts are visible in a frame.
- Assigning side, status, centroid, length, and opacity.
- Producing the same canonical frame shape for live display and report replay.
- Storing the canonical replay timeline in the final report.

The UI is responsible only for:

- Receiving one frame.
- Mapping each frame's LED indexes and foot states to pixels.
- Drawing the result.

The UI must not:

- Derive active windows from touch/lift events.
- Decide that a missing `lift_time_s` means a foot remains active.
- Maintain an independent footprint state machine across replay ticks.

## Assets

Use the uploaded left/right foot images as the visual source, but store processed transparent PNG assets in the project, for example:

- `ui/assets/left_foot.png`
- `ui/assets/right_foot.png`

If an asset fails to load, the widget should draw a simple fallback footprint shape so the UI does not go blank.

## Error Handling

- If `contact_bits` is missing or shorter than 96, render available bits and leave the rest inactive.
- If `visual_timeline` is empty, show the replay placeholder.
- If pyqtgraph is unavailable, this change should not affect the footprint widget because it uses Qt painting, not pyqtgraph.
- Unknown foot side should render in a neutral color or use a neutral fallback footprint. UI must not infer side by alternating contact order.

## Testing

Unit tests:

- LED index-to-y mapping handles index 0, 95, and midpoints.
- The widget accepts 96-bit frames and does not resize or throw on short frames.
- Canonical frame building includes active contacts and does not require UI event interpretation.
- Gait-related reports default `visual_timeline=()` for backward compatibility.

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
- Report page can replay canonical footprint visualization frames with play/pause and a time slider.
- Existing treadmill metrics, report tables, and export behavior still work.
- Existing jump-mode UI remains unchanged.
