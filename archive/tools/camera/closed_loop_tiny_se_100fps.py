"""Closed-loop Tiny SE 100fps UVC verification.

Flow:
1. DirectShow baseline caps + forced 100fps SetFormat.
2. SDK baseline status.
3. SDK set record encode to 1080p100 MJPEG, then re-run DirectShow.
4. SDK set output encode to 1080p100 MJPEG, then re-run DirectShow.

The script targets only SDK-detected Tiny SE and the DirectShow probe targets
only "OBSBOT Tiny SE" by friendly name.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

from diagnose_tiny_se import (
    FMT_NAMES,
    MODE_NAMES,
    PRODUCT_NAMES,
    ObsbotCameraStatusInfo,
    ObsbotDeviceInfo,
    ObsbotEncodeParam,
    ObsbotVideoFormatInfo,
    bind,
    cstr,
)


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
CAMERA_DIR = PROJECT_ROOT / "camera"
WRAPPER_DIR = CAMERA_DIR / "bin"
WRAPPER_DLL = WRAPPER_DIR / "obsbot_c_api.dll"
DSHOW_PROBE = CAMERA_DIR / "bin" / "dshow_probe.exe"

TINY_SE_PRODUCT_TYPE = 12
ENCODER_AUTO = 0
ENCODER_MJPEG = 3


def load_wrapper() -> ctypes.CDLL:
    if not WRAPPER_DLL.exists():
        raise FileNotFoundError(f"wrapper DLL not found: {WRAPPER_DLL}")
    os.add_dll_directory(str(WRAPPER_DIR))
    dll = ctypes.CDLL(str(WRAPPER_DLL))
    bind(dll)
    return dll


def find_tiny_se(dll: ctypes.CDLL, wait_ms: int = 5000) -> int:
    count = dll.obsbot_refresh_devices(wait_ms)
    print(f"SDK device count: {count}")
    for index in range(max(0, count)):
        info = ObsbotDeviceInfo()
        ret = dll.obsbot_get_device_info(index, ctypes.byref(info))
        if ret == 0 and (
            info.product_type == TINY_SE_PRODUCT_TYPE
            or "Tiny SE" in cstr(info.video_friendly_name)
        ):
            print(
                f"Using SDK device {index}: SN={cstr(info.sn)} "
                f"product={info.product_type}({PRODUCT_NAMES.get(info.product_type, '?')}) "
                f"mode={info.dev_mode}({MODE_NAMES.get(info.dev_mode, '?')})"
            )
            return index
    raise RuntimeError("Tiny SE not found by SDK")


def print_sdk_snapshot(dll: ctypes.CDLL, index: int) -> None:
    status = ObsbotCameraStatusInfo()
    ret = dll.obsbot_get_camera_status(index, ctypes.byref(status), 1)
    print(
        f"  cameraStatus ret={ret}: tiny.fps={status.tiny_fps} "
        f"tiny.live={status.tiny_live_stream_mode} fov={status.tiny_fov}"
    )

    formats = (ObsbotVideoFormatInfo * 32)()
    total = dll.obsbot_get_video_formats(index, formats, len(formats))
    print(f"  videoFormatInfo total={total}")
    for item in formats[: max(0, min(total, len(formats)))]:
        print(
            f"    {item.width}x{item.height} fps=[{item.fps_min},{item.fps_max}] "
            f"{FMT_NAMES.get(item.format, hex(item.format))}"
        )


def run_dshow(label: str) -> None:
    print(f"\n=== DirectShow probe: {label} ===")
    if not DSHOW_PROBE.exists():
        raise FileNotFoundError(f"DirectShow probe not built: {DSHOW_PROBE}")
    proc = subprocess.run(
        [str(DSHOW_PROBE), "OBSBOT Tiny SE"],
        cwd=str(ROOT.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    text = (proc.stdout or proc.stderr).strip()
    print(text if text else "(no output)")
    print(f"DirectShow probe exit code: {proc.returncode}")


def sdk_phase(label: str, setter_name: str | None = None, param: ObsbotEncodeParam | None = None) -> None:
    print(f"\n=== SDK phase: {label} ===")
    dll = load_wrapper()
    try:
        index = find_tiny_se(dll)
        print_sdk_snapshot(dll, index)
        if setter_name and param is not None:
            setter = getattr(dll, setter_name)
            ret = setter(index, ctypes.byref(param), 0)
            print(
                f"  {setter_name}(w={param.width}, h={param.height}, fps={param.fps}, "
                f"bitrate={param.bitrate}, enc={param.encode_format}) -> {ret}"
            )
            time.sleep(1.0)
            print_sdk_snapshot(dll, index)
    finally:
        dll.obsbot_close()


def main() -> int:
    run_dshow("baseline before SDK changes")
    sdk_phase("baseline")

    record_param = ObsbotEncodeParam(
        width=1920,
        height=1080,
        fps=100,
        bitrate=-1,
        encode_format=ENCODER_MJPEG,
    )
    sdk_phase("set record encode 1080p100 MJPEG", "obsbot_set_record_encode_param", record_param)
    time.sleep(2.0)
    run_dshow("after set_record_encode_param 1080p100 MJPEG")

    output_param = ObsbotEncodeParam(
        width=1920,
        height=1080,
        fps=100,
        bitrate=-1,
        encode_format=ENCODER_MJPEG,
    )
    sdk_phase("set output encode 1080p100 MJPEG", "obsbot_set_output_encode_param", output_param)
    time.sleep(2.0)
    run_dshow("after set_output_encode_param 1080p100 MJPEG")

    print("\nClosed-loop verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
