"""Standalone demo that shows how to split LED bits into clusters and
run a single-foot touch/lift detector.

Usage::

    python -m demo.cluster_test  # requires hardware

The script fabricates a few frames that mimic one foot landing on the
96×1 LED strip, staying in contact, then lifting off.  It prints the
clusters that were detected per frame and the touch/lift events found
by a lightweight state machine.
"""

from __future__ import annotations

import argparse
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

try:
    from .receive import CyUsbInterfaceDevice
except Exception:  # pragma: no cover
    try:
        from receive import CyUsbInterfaceDevice  # type: ignore
    except Exception:
        CyUsbInterfaceDevice = None  # type: ignore

try:
    from .protocol import E_DATA_REPORT
except Exception:  # pragma: no cover
    try:
        from protocol import E_DATA_REPORT  # type: ignore
    except Exception:
        E_DATA_REPORT = None

COLS = 96
SPACING_CM = 1.04
DEFAULT_DLL = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../Newtongxin/CyUsbInterface/output/CyUsbInterface.dll")
)
DEFAULT_VID = 0x04B4
DEFAULT_PID = 0x1004


@dataclass
class LedFrame:
    """Raw LED frame for the demo."""

    timestamp: float
    bits: Sequence[int]  # 1 means covered/pressed


@dataclass
class Cluster:
    start: int
    end: int
    length: int
    centroid_idx: float
    centroid_cm: float
    ratio: float


@dataclass
class FootEvent:
    kind: str  # "touch" or "lift"
    time: float
    ratio: float
    centroid_cm: Optional[float]


class SingleFootDetector:
    """Very small state machine that only tracks the strongest cluster.

    This is a pedagogical subset of :class:`GaitAnalyzer`.  It keeps one
    state (air / ground) and triggers events based on the cluster's
    coverage ratio and slope.
    """

    def __init__(
        self,
        cols: int = COLS,
        spacing_cm: float = SPACING_CM,
        gap_threshold: int = 1,
        touch_ratio_threshold: float = 0.05,
        lift_ratio_threshold: float = 0.05,
        confirm_samples: int = 10,
    ) -> None:
        self.cols = cols
        self.spacing_cm = spacing_cm
        self.gap_threshold = gap_threshold
        self.touch_ratio_threshold = touch_ratio_threshold
        self.lift_ratio_threshold = lift_ratio_threshold
        self.confirm_samples = confirm_samples
        self._reset_state()

    # ---- public API -------------------------------------------------

    def process(self, frames: Sequence[LedFrame]) -> List[FootEvent]:
        self.reset()
        events: List[FootEvent] = []
        for frame in frames:
            events.extend(self.consume(frame))
        return events

    def consume(self, frame: LedFrame) -> List[FootEvent]:
        if self._prev_time is None:
            self._prev_time = frame.timestamp
        return self._process_frame(frame)

    def reset(self) -> None:
        self._reset_state()

    def _reset_state(self) -> None:
        self._state = "air"
        self._touch_streak = 0
        self._lift_streak = 0
        self._prev_ratio = 0.0
        self._prev_time: Optional[float] = None

    def _process_frame(self, frame: LedFrame) -> List[FootEvent]:
        cluster = self._extract_primary_cluster(frame.bits)
        ratio = cluster.ratio if cluster else 0.0
        centroid = cluster.centroid_cm if cluster else None
        dt = max(frame.timestamp - (self._prev_time or frame.timestamp), 1e-3)
        d_ratio = (ratio - self._prev_ratio) / dt
        self._prev_time = frame.timestamp
        self._prev_ratio = ratio
        grad_trigger = self.touch_ratio_threshold * 0.3
        events: List[FootEvent] = []

        touch_condition = (
            self._state == "air"
            and ratio >= self.touch_ratio_threshold
            #and d_ratio > grad_trigger
            and ratio < 0.38
        )
        lift_condition = (
            self._state == "ground"
            and (ratio <= self.lift_ratio_threshold or cluster is None)
            #and d_ratio < -grad_trigger
        )

        if touch_condition:
            self._touch_streak += 1
            self._lift_streak = max(0, self._lift_streak - 1)
            if self._touch_streak >= self.confirm_samples:
                events.append(FootEvent("touch", frame.timestamp, ratio, centroid))
                self._state = "ground"
                self._touch_streak = 0
        elif lift_condition:
            self._lift_streak += 1
            self._touch_streak = max(0, self._touch_streak - 1)
            if self._lift_streak >= self.confirm_samples:
                events.append(FootEvent("lift", frame.timestamp, ratio, centroid))
                self._state = "air"
                self._lift_streak = 0
        else:
            self._touch_streak = max(0, self._touch_streak - 1)
            self._lift_streak = max(0, self._lift_streak - 1)
        return events

    # ---- helpers -----------------------------------------------------

    def _extract_primary_cluster(self, bits: Sequence[int]) -> Optional[Cluster]:
        active = [idx for idx, val in enumerate(bits) if val]
        if not active:
            return None
        clusters = list(self._split_clusters(active))
        if not clusters:
            return None
        primary_cluster = max(clusters, key=lambda cl: cl.length)
        # Allow smaller contacts; ignore extremely long spans that likely indicate a steady pattern
        if primary_cluster.length < 10:
            return None
        return primary_cluster

    def _split_clusters(self, active_indices: Sequence[int]) -> Iterable[Cluster]:
        if not active_indices:
            return []
        start = active_indices[0]
        prev = start
        for idx in active_indices[1:]:
            if idx - prev > self.gap_threshold:
                yield self._make_cluster(start, prev)
                start = idx
            prev = idx
        yield self._make_cluster(start, prev)

    def _make_cluster(self, start: int, end: int) -> Cluster:
        length = end - start + 1
        centroid_idx = (start + end) / 2.0
        centroid_cm = centroid_idx * self.spacing_cm
        ratio = length / self.cols
        return Cluster(start, end, length, centroid_idx, centroid_cm, ratio)

class LiveFrameReader:
    """Connects to the hardware and emits 96-bit frames via a callback."""

    def __init__(
        self,
        on_frame: Callable[[LedFrame], None],
        dll_path: Optional[str] = None,
        vid: Optional[int] = None,
        pid: Optional[int] = None,
        timeout_ms: int = 30,
        chunk_size: int = 512,
    ):
        self.on_frame = on_frame
        self.dll_path = dll_path or os.getenv("DAYU_DLL", DEFAULT_DLL)
        self.vid = vid if vid is not None else int(os.getenv("DAYU_VID", f"0x{DEFAULT_VID:04X}"), 0)
        self.pid = pid if pid is not None else int(os.getenv("DAYU_PID", f"0x{DEFAULT_PID:04X}"), 0)
        self.timeout_ms = timeout_ms
        self.chunk_size = chunk_size
        self.dev = None
        self._frames = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        if CyUsbInterfaceDevice is None:
            raise RuntimeError("CyUsbInterfaceDevice unavailable; please ensure receive.py is accessible.")
        self.dev = CyUsbInterfaceDevice(self.dll_path)
        if not self.dev.open(self.vid, self.pid):
            raise RuntimeError(f"无法打开设备 VID=0x{self.vid:04X} PID=0x{self.pid:04X}")
        try:
            self.dev.dll.set_timeout(self.timeout_ms)
        except Exception:
            pass
        self.dev.set_on_bytes(None)
        self.dev.set_on_frame(self._on_frame)
        self.dev.start_capture()
        self.dev.start_auto_read(self.chunk_size)

    def stop(self) -> None:
        if not self.dev:
            return
        try:
            self.dev.stop_auto_read()
        except Exception:
            pass
        try:
            self.dev.stop_capture()
        except Exception:
            pass
        try:
            self.dev.close()
        except Exception:
            pass
        self.dev = None

    def _on_frame(self, frame_type, ack, subpack, status):
        if E_DATA_REPORT is not None and frame_type != E_DATA_REPORT:
            return
        if not subpack:
            return
        payload = self._extract_payload(subpack)
        if not payload:
            return
        pack_num = int(getattr(subpack, "packNum", 1) or 1)
        frame_idx = int(getattr(subpack, "frameIdx", 0) or 0)
        pack_idx = int(getattr(subpack, "packIdx", 1) or 1)
        if pack_num <= 1 and len(payload) >= 12:
            self._emit_frame(payload[:12])
            return
        node = self._frames.setdefault(frame_idx, {"packs": {}, "packNum": pack_num})
        node["packs"][pack_idx] = bytes(payload)
        node["packNum"] = max(node.get("packNum", pack_num), pack_num)
        packs = node["packs"]
        if len(packs) < node["packNum"]:
            return
        payload_bytes = bytearray()
        ordered = False
        try:
            for i in range(1, node["packNum"] + 1):
                payload_bytes.extend(packs[i])
            ordered = True
        except Exception:
            pass
        if not ordered:
            payload_bytes = bytearray()
            for i in range(node["packNum"]):
                part = packs.get(i)
                if part:
                    payload_bytes.extend(part)
        if len(payload_bytes) >= 12:
            self._emit_frame(bytes(payload_bytes[:12]))
        with self._lock:
            self._frames.pop(frame_idx, None)

    def _emit_frame(self, body12: bytes) -> None:
        bits = self._bytes_to_bits(body12)
        if not bits:
            return
        # Drop degenerate frames (all 0 or all 1) which often appear at startup or on faults
        ones = sum(bits)
        if ones == 0 or ones == len(bits):
            return
        frame = LedFrame(time.perf_counter(), bits)
        self.on_frame(frame)

    @staticmethod
    def _bytes_to_bits(payload: bytes) -> List[int]:
        bits: List[int] = []
        for b in payload[:12]:
            for i in range(8):
                bits.append((b >> i) & 0x1)
        # Normalize semantics: 1 = covered/pressed, 0 = uncovered/light
        bits = [1 - x for x in bits[:96]]
        return bits

    @staticmethod
    def _extract_payload(subpack) -> bytes:
        cand_names = ["body", "payload", "data", "buffer", "buf"]
        buf = None
        for name in cand_names:
            if hasattr(subpack, name):
                val = getattr(subpack, name)
                if val is not None:
                    buf = val
                    break
        if buf is None:
            return b""
        try:
            raw = bytes(buf)
        except Exception:
            try:
                raw = bytes(bytearray(buf))
            except Exception:
                raw = b""
        try:
            blen = int(getattr(subpack, "bufferLen"))
            if 0 < blen <= len(raw):
                raw = raw[:blen]
        except Exception:
            pass
        return raw

def run_live(args: argparse.Namespace) -> None:
    detector = SingleFootDetector(
        touch_ratio_threshold=args.touch_threshold,
        lift_ratio_threshold=args.lift_threshold,
        confirm_samples=args.confirm_samples,
    )
    detector.reset()
    frame_queue: "queue.Queue[LedFrame]" = queue.Queue(maxsize=args.queue_size)

    def enqueue(frame: LedFrame) -> None:
        try:
            frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                pass
            frame_queue.put_nowait(frame)

    reader = LiveFrameReader(
        on_frame=enqueue,
        dll_path=args.dll,
        vid=args.vid,
        pid=args.pid,
        timeout_ms=args.timeout_ms,
        chunk_size=args.chunk_size,
    )

    reader.start()
    print(
        "Live mode started. Press Ctrl+C to stop. "
        "Streaming single-foot events..."
    )
    start_ts = time.perf_counter()
    processed = 0
    warmup = 5  # skip first few frames to avoid startup noise
    last_ev: Optional[FootEvent] = None  # 仅在有新事件到来时输出上一条，最终只保留最后一次触地
    try:
        while True:
            try:
                frame = frame_queue.get(timeout=0.5)
            except queue.Empty:
                if args.duration and (time.perf_counter() - start_ts) > args.duration:
                    break
                continue
            # Warm-up skip
            if warmup > 0:
                warmup -= 1
                continue
            processed += 1
            for ev in detector.consume(frame):
                # 若已有上一条事件，安全输出它
                if last_ev is not None:
                    stage = "触地阶段" if last_ev.kind.lower() == "touch" else "腾空阶段"
                    time_str = f"{(last_ev.time - start_ts):.3f}s"
                    ratio_str = f"{last_ev.ratio:.3f}"
                    centroid_str = (
                        f"{last_ev.centroid_cm:.2f}cm" if last_ev.centroid_cm is not None else "N/A"
                    )
                    print(f"{stage} 时刻={time_str} 遮挡率={ratio_str} 质心位置={centroid_str}")
                # 暂存当前事件，最终根据类型决定是否输出
                last_ev = ev
            if args.duration and (time.perf_counter() - start_ts) > args.duration:
                break
    except KeyboardInterrupt:
        print("\nStopping live stream…")
    finally:
        # 循环结束后：如果最后一条是腾空，则丢弃；如果是触地则输出
        if last_ev is not None and last_ev.kind.lower() == "touch":
            stage = "触地阶段"
            time_str = f"{(last_ev.time - start_ts):.3f}s"
            ratio_str = f"{last_ev.ratio:.3f}"
            centroid_str = (
                f"{last_ev.centroid_cm:.2f}cm" if last_ev.centroid_cm is not None else "N/A"
            )
            print(f"{stage} 时刻={time_str} 遮挡率={ratio_str} 质心位置={centroid_str}")
        reader.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cluster-based single foot detector live runner")
    parser.add_argument("--touch-threshold", type=float, default=0.12)
    parser.add_argument("--lift-threshold", type=float, default=0.05)
    parser.add_argument("--confirm-samples", type=int, default=2)
    parser.add_argument("--queue-size", type=int, default=512, help="Max buffered frames in live mode")
    parser.add_argument("--duration", type=float, default=0.0, help="Optional duration limit for live mode (seconds)")
    parser.add_argument("--dll", type=str, default=os.getenv("DAYU_DLL", DEFAULT_DLL))
    default_vid = int(os.getenv("DAYU_VID", f"0x{DEFAULT_VID:04X}"), 0)
    default_pid = int(os.getenv("DAYU_PID", f"0x{DEFAULT_PID:04X}"), 0)
    parser.add_argument("--vid", type=lambda v: int(v, 0), default=default_vid)
    parser.add_argument("--pid", type=lambda v: int(v, 0), default=default_pid)
    parser.add_argument("--timeout-ms", type=int, default=int(os.getenv("DAYU_TIMEOUT", "30")))
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("DAYU_CHUNK", "512")))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_live(args)


if __name__ == "__main__":
    main()
