# Visual foot reference module

This package is independent from the Iron_Jump engine and reports a rejectable
visual reference for timestamped touch events. It does not modify optical-grid
timing, treadmill rows, reports, or UI state.

## Inputs and output

- `submit_frame(frame, captured_at_s)` accepts an unmirrored BGR frame and a
  timestamp already mapped into the host `time.perf_counter()` domain.
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

# Legacy cameras may connect directly only when their frame timestamp is already
# in the optical event's clock domain. TinySE uses the synchronized validator
# path described below instead.
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

## Windows real-event validation

Run the sidecar validator by itself when both the Tiny SE camera and optical
grid are connected. It reuses the project's `SessionController` touch events
but does not write visual labels back to the engine or report:

```powershell
python tools\vision_event_validator.py `
  --camera tinyse `
  --mode treadmill-gait `
  --model .\models\pose_landmarker_full.task `
  --output .\vision-event-validation.csv
```

The live image overlays left/right hip, knee, ankle, heel, and foot-index
landmarks. Each real grid touch preserves an event image on the right. Press
`L`, `R`, `B`, or `U` to record manual left/right/both/unreviewable truth for
the latest event; press `Q` to exit.

For TinySE, the validator first collects at least 30 frames over at least 0.8
seconds and maps the DirectShow sample clock into `time.perf_counter()`. It does
not start the optical-grid session until the UI shows `sync=ready`. Keep the
optical area clear during this warm-up and for another 1–2 seconds after the
grid session starts, then begin stepping. If the sample clock regresses, its
P95–P5 delivery uncertainty exceeds 40 ms, or its rolling drift exceeds 40 ms,
the session becomes `degraded` and affected events are exported as
`unknown/clock_sync_degraded`; legacy decode timestamps are never mixed into
the aligned stream.

`camera_callback_time_s` is captured at the Python ctypes callback entrance,
before copying the MJPEG buffer; `camera_legacy_time_s` remains the old
post-decode timestamp for comparison.

The validator uses a 250 ms pre-event window, a 200 ms post-event window, a
60 ms pose interval, and a 500 ms decision timeout. Each CSV row includes the
actual analysis/Pose FPS, inference attempts, successful Pose counts before and
after touch, maximum Pose gap, sync offset/uncertainty/sample period, and both
legacy and aligned camera timestamps. The exported camera frame index and
`camera_event_delta_ms` identify the latest analysis frame delivered when the
grid event reaches the validator. That same frame and its nearest cached pose
are used for the right-side event snapshot. The exact sync failure is retained in
`sync_reason`, and `sync_warmup_ms` records how long the initial mapping took;
the event-level fallback remains `unknown/clock_sync_degraded`. In Jump mode, an
initial touch without a preceding lift is retained as `baseline` but excluded
from landing coverage and accuracy.

Analysis FPS is calculated from aligned camera sample timestamps. Pose FPS is
calculated from successful result arrival times, so CPU inference backlog lowers
the displayed value instead of being hidden by evenly spaced sample timestamps.

Do not run this validator at the same time as the main application because both
would attempt to own the optical device. TinySE real synchronization quality
must be accepted on Windows hardware; Mac tests use synthetic timestamps only.

For the first acceptance run, create separate CSV files for 10 left steps, 10
right steps, and 10 two-foot jumps. The automatic scheme passes only if sync is
ready within 2 seconds, uncertainty P95 is at most 40 ms, clean-event pose
coverage is at least 80%, and decision latency P95 is at most 350 ms.

After the three runs, this PowerShell summary excludes Jump baseline rows and
checks the four automatic acceptance measurements:

```powershell
$files = @(
  ".\vision-left.csv",
  ".\vision-right.csv",
  ".\vision-jump.csv"
)
$rows = @($files | ForEach-Object { Import-Csv $_ })
$eligible = @($rows | Where-Object {
  $_.event_role -in @("grid_touch", "landing")
})

function Get-P95($values) {
  $sorted = @($values | Where-Object { $_ -ne "" } |
    ForEach-Object { [double]$_ } | Sort-Object)
  if ($sorted.Count -eq 0) { return [double]::NaN }
  $index = [int][Math]::Max(0, [Math]::Ceiling($sorted.Count * 0.95) - 1)
  return $sorted[$index]
}

$poseCovered = @($eligible | Where-Object {
  [int]$_.pose_before -ge 2 -and [int]$_.pose_after -ge 2
}).Count
$syncReady = @($eligible | Where-Object { $_.sync_status -eq "ready" }).Count

[pscustomobject]@{
  EligibleEvents      = $eligible.Count
  SyncReadyPercent    = if ($eligible.Count) {
    100 * $syncReady / $eligible.Count
  } else { 0 }
  SyncWarmupMaxMs     = (@($eligible.sync_warmup_ms |
    Where-Object { $_ -ne "" } | ForEach-Object { [double]$_ }) |
    Measure-Object -Maximum).Maximum
  UncertaintyP95Ms    = Get-P95 $eligible.sync_uncertainty_ms
  PoseCoveragePercent = if ($eligible.Count) {
    100 * $poseCovered / $eligible.Count
  } else { 0 }
  DecisionP95Ms       = Get-P95 $eligible.latency_ms
}
```
