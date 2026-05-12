"""OpenCV/UVC probe for OBSBOT Tiny SE.

The camera/driver can hang or crash inside VideoCapture.set/read.  This
probe runs every backend/index/mode attempt in a child process so one bad
mode does not stop the whole exploration.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

import cv2


BACKENDS: dict[str, int] = {
    "DSHOW": cv2.CAP_DSHOW,
    "MSMF": cv2.CAP_MSMF,
    "ANY": cv2.CAP_ANY,
}

MODES: dict[str, str] = {
    "default": "no requested format",
    "target_no_fourcc": "set 1920x1080 + 100fps",
    "target_mjpg_first": "set MJPG, then 1920x1080 + 100fps",
    "target_mjpg_last": "set 1920x1080 + 100fps, then MJPG",
    "target_yuy2_last": "set 1920x1080 + 100fps, then YUY2",
}

TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 100
DEFAULT_TINY_SE_INDEX = 2


@dataclass
class ProbeResult:
    camera_index: int
    backend_name: str
    mode: str
    mode_detail: str
    open_ok: bool = False
    read_ok: bool = False
    actual_width: int = 0
    actual_height: int = 0
    actual_fps_capget: float = 0.0
    actual_fourcc_hex: str = ""
    actual_fourcc_ascii: str = ""
    measured_fps: float = 0.0
    frames_measured: int = 0
    timeout: bool = False
    returncode: int = 0
    error: str = ""


def _safe_fourcc(value: float) -> tuple[str, str]:
    raw = int(value) & 0xFFFFFFFF
    text = []
    for index in range(4):
        byte = (raw >> (8 * index)) & 0xFF
        if 32 <= byte < 127:
            text.append(chr(byte))
        else:
            text.append(f"\\x{byte:02X}")
    return f"0x{raw:08X}", "".join(text)


def _apply_mode(cap: cv2.VideoCapture, mode: str) -> None:
    if mode == "default":
        return
    if mode == "target_mjpg_first":
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, TARGET_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TARGET_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    if mode == "target_mjpg_last":
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    elif mode == "target_yuy2_last":
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUY2"))


def _child_probe(camera_index: int, backend_name: str, mode: str) -> ProbeResult:
    result = ProbeResult(
        camera_index=camera_index,
        backend_name=backend_name,
        mode=mode,
        mode_detail=MODES[mode],
    )
    cap: cv2.VideoCapture | None = None
    try:
        cap = cv2.VideoCapture(camera_index, BACKENDS[backend_name])
        result.open_ok = bool(cap.isOpened())
        if not result.open_ok:
            result.error = "open failed"
            return result

        _apply_mode(cap, mode)

        first_ok = False
        for _ in range(5):
            first_ok, _ = cap.read()
            if first_ok:
                break
        result.read_ok = first_ok
        result.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        result.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        result.actual_fps_capget = float(cap.get(cv2.CAP_PROP_FPS))
        result.actual_fourcc_hex, result.actual_fourcc_ascii = _safe_fourcc(
            cap.get(cv2.CAP_PROP_FOURCC)
        )

        if first_ok:
            max_frames = 120
            max_seconds = 4.0
            frames = 0
            start = time.perf_counter()
            while frames < max_frames and time.perf_counter() - start < max_seconds:
                ok, _ = cap.read()
                if not ok:
                    break
                frames += 1
            elapsed = time.perf_counter() - start
            result.frames_measured = frames
            result.measured_fps = frames / elapsed if elapsed > 0 else 0.0
        return result
    except Exception as exc:  # pylint: disable=broad-except
        result.error = repr(exc)
        return result
    finally:
        if cap is not None:
            cap.release()


def _run_child(camera_index: int, backend_name: str, mode: str, timeout_sec: int) -> ProbeResult:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        sys.executable,
        __file__,
        "--child",
        "--camera-index",
        str(camera_index),
        "--backend",
        backend_name,
        "--mode",
        mode,
    ]
    fallback = ProbeResult(
        camera_index=camera_index,
        backend_name=backend_name,
        mode=mode,
        mode_detail=MODES[mode],
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fallback.timeout = True
        fallback.error = "timeout/hung"
        return fallback

    fallback.returncode = proc.returncode
    lines = (proc.stdout or proc.stderr or "").strip().splitlines()
    if proc.returncode != 0:
        fallback.error = f"child crashed/failed; returncode={proc.returncode}"
        if lines:
            fallback.error += f"; last_output={lines[-1]}"
        return fallback
    if not lines:
        fallback.error = "child returned no output"
        return fallback

    try:
        data: dict[str, Any] = json.loads(lines[-1])
        return ProbeResult(**data)
    except Exception as exc:  # pylint: disable=broad-except
        fallback.error = f"bad child json: {exc!r}; last_output={lines[-1]}"
        return fallback


def _format_result(result: ProbeResult) -> str:
    status = "OK" if result.open_ok and result.read_ok else "FAIL"
    if result.timeout:
        status = "TIMEOUT"
    elif result.returncode:
        status = "CRASH"
    actual = f"{result.actual_width}x{result.actual_height}"
    return (
        f"{status:7} cam={result.camera_index:<2} backend={result.backend_name:<5} "
        f"mode={result.mode:<18} actual={actual:<10} "
        f"fourcc={result.actual_fourcc_ascii:<16} "
        f"cap_fps={result.actual_fps_capget:>6.2f} "
        f"measured={result.measured_fps:>6.2f}fps frames={result.frames_measured:<3} "
        f"err={result.error}"
    )


def _rank_key(result: ProbeResult) -> tuple[float, int, int]:
    pixels = result.actual_width * result.actual_height
    return result.measured_fps, pixels, result.frames_measured


def run_parent(args: argparse.Namespace) -> int:
    indices = list(range(args.min_index, args.max_index + 1))
    indices = [idx for idx in indices if idx not in set(args.skip_index)]
    backend_names = args.backend or list(BACKENDS)
    modes = args.mode or list(MODES)

    print("=== OpenCV UVC 勘查（子进程隔离） ===")
    print(f"目标: {TARGET_WIDTH}x{TARGET_HEIGHT}@{TARGET_FPS}fps")
    print(f"索引: {indices}")
    print(f"后端: {backend_names}")
    print(f"模式: {modes}")
    print()

    results: list[ProbeResult] = []
    for backend_name in backend_names:
        for camera_index in indices:
            for mode in modes:
                result = _run_child(camera_index, backend_name, mode, args.timeout)
                results.append(result)
                print(_format_result(result), flush=True)

    valid = [item for item in results if item.open_ok and item.read_ok]
    capable = [
        item
        for item in valid
        if item.actual_width == TARGET_WIDTH
        and item.actual_height == TARGET_HEIGHT
        and item.measured_fps >= TARGET_FPS * 0.95
    ]

    print("\n=== 结论路由 ===")
    if capable:
        best = max(capable, key=_rank_key)
        print("结论: OpenCV/UVC 实测可达到目标。")
        print(_format_result(best))
        return 0

    print("结论: OpenCV/UVC 实测未达到 1920x1080@100fps。")
    if valid:
        best = max(valid, key=_rank_key)
        print("当前实测最佳结果:")
        print(_format_result(best))
    else:
        print("没有任何后端/索引成功读到帧。")
    print("注意: cap.get(FPS/宽高/FOURCC) 只能作参考，最终以 measured fps 为准。")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS.keys(), action="append")
    parser.add_argument("--mode", choices=MODES.keys(), action="append")
    parser.add_argument(
        "--min-index",
        type=int,
        default=DEFAULT_TINY_SE_INDEX,
        help=f"first OpenCV index to probe; default is known Tiny SE index {DEFAULT_TINY_SE_INDEX}",
    )
    parser.add_argument(
        "--max-index",
        type=int,
        default=DEFAULT_TINY_SE_INDEX,
        help=f"last OpenCV index to probe; default is known Tiny SE index {DEFAULT_TINY_SE_INDEX}",
    )
    parser.add_argument("--skip-index", type=int, action="append", default=[])
    parser.add_argument("--timeout", type=int, default=12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.child:
        backend_name = args.backend[0] if args.backend else "DSHOW"
        mode = args.mode[0] if args.mode else "default"
        result = _child_probe(args.camera_index, backend_name, mode)
        print(json.dumps(asdict(result), ensure_ascii=True))
        return 0
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
