# Visual foot reference module

This package is independent from the Iron_Jump engine and reports a rejectable
visual reference for timestamped touch events. It does not modify optical-grid
timing, treadmill rows, reports, or UI state.

## Inputs and output

- `submit_frame(frame, captured_at_s)` accepts an unmirrored BGR frame and its
  `time.perf_counter()` timestamp.
- `submit_touch_event(event_id, event_time_s)` accepts a touch event in the same
  monotonic clock domain.
- `decision_ready` emits `VisionDecision` with `left`, `right`, `both`, or
  `unknown`, a confidence value, and a reason.
- Missing dependencies/models, stale windows, timeouts, low landmark quality,
  and inference errors return `unknown`; they never change optical-grid data.

```python
from vision import FootVisionService, VisionConfig

service = FootVisionService(
    VisionConfig(),
    r"C:\Iron_Jump\models\pose_landmarker_full.task",
)
service.decision_ready.connect(print)
service.start()

# A camera capture's analysis signal can be connected directly:
capture.analysis_frame_ready.connect(service.submit_frame)

# Submit only touch events, using the optical event's perf_counter timestamp:
service.submit_touch_event(event_id=1, event_time_s=touch_time_s)

service.stop()
```

The first-release thresholds are uncalibrated starting values. Passing unit
tests proves software ordering and fallback behavior, not real-person label
accuracy.

## Windows diagnostic

After installing dependencies and placing the MediaPipe Pose Landmarker Full
`.task` model locally:

```powershell
New-Item -ItemType Directory -Force .\models | Out-Null
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task" `
  -OutFile ".\models\pose_landmarker_full.task"

python tools\vision_live.py `
  --camera tinyse `
  --model .\models\pose_landmarker_full.task `
  --output vision-results.csv
```

The independent window continuously evaluates rolling visual windows (default
250 ms interval); press Q to exit. The live window uses a 0.65 reference-only
threshold and 80 ms pose sampling to keep CPU load bounded; the core module's
0.90 high-confidence fusion default is unchanged. The CSV records timestamps,
label, candidate label, confidence, rejection reason, and end-to-end latency.
Continuous visual state does not validate synchronization with the optical grid.
