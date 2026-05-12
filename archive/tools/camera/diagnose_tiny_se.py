"""Read-only OBSBOT Tiny SE diagnostics through the C wrapper.

Default mode does not call setters.  Use --set-record-100 explicitly if you
want to repeat the existing SDK record-encode write test.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
CAMERA_DIR = PROJECT_ROOT / "camera"
WRAPPER_DIR = CAMERA_DIR / "bin"
WRAPPER_DLL = WRAPPER_DIR / "obsbot_c_api.dll"


class ObsbotEncodeParam(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("fps", ctypes.c_int32),
        ("bitrate", ctypes.c_int32),
        ("encode_format", ctypes.c_int32),
    ]


class ObsbotVideoFormatInfo(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("fps_min", ctypes.c_int32),
        ("fps_max", ctypes.c_int32),
        ("format", ctypes.c_int32),
    ]


class ObsbotDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("sn", ctypes.c_char * 64),
        ("name", ctypes.c_char * 128),
        ("version", ctypes.c_char * 64),
        ("video_path", ctypes.c_char * 512),
        ("video_friendly_name", ctypes.c_char * 256),
        ("product_type", ctypes.c_int32),
        ("dev_mode", ctypes.c_int32),
    ]


class ObsbotCameraStatusInfo(ctypes.Structure):
    _fields_ = [
        ("query_ret", ctypes.c_int32),
        ("product_type", ctypes.c_int32),
        ("dev_mode", ctypes.c_int32),
        ("tiny_fps", ctypes.c_int32),
        ("tiny_dev_status", ctypes.c_int32),
        ("tiny_hdr", ctypes.c_int32),
        ("tiny_live_stream_mode", ctypes.c_int32),
        ("tiny_fov", ctypes.c_int32),
        ("tiny_vertical", ctypes.c_int32),
        ("tiny_usb_status", ctypes.c_int32),
    ]


@dataclass(frozen=True)
class Stream:
    stream_id: int
    name: str


STREAMS = [
    Stream(1, "Record"),
    Stream(2, "Capture"),
    Stream(3, "Live"),
    Stream(4, "Rtsp"),
    Stream(5, "Ndi"),
    Stream(6, "Srt"),
    Stream(7, "Uvc"),
    Stream(8, "Kcp"),
]

FMT_NAMES = {
    200: "I420",
    201: "NV12",
    300: "YVYU",
    301: "YUY2",
    302: "UYVY",
    400: "MJPEG",
    401: "H264",
    402: "HEVC",
}
PRODUCT_NAMES = {2: "Tiny2", 5: "Meet", 6: "Meet4K", 10: "Meet2", 12: "TinySE", 13: "MeetSE", 18: "Tiny3"}
MODE_NAMES = {0: "UVC", 1: "Net", 2: "MTP", 3: "BLE"}
USB_MODE_NAMES = {0: "Idle", 1: "UVC+UAC", 2: "UVC+RNDIS", 3: "RNDIS", 4: "MTP", 5: "Mass", 6: "Host"}
ACTION_NAMES = {0: "Auto", 1: "Start", 2: "Stop", 3: "Pause", 4: "Resume"}


def cstr(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def bind(dll: ctypes.CDLL) -> None:
    dll.obsbot_refresh_devices.argtypes = [ctypes.c_int32]
    dll.obsbot_refresh_devices.restype = ctypes.c_int32
    dll.obsbot_get_device_info.argtypes = [ctypes.c_int32, ctypes.POINTER(ObsbotDeviceInfo)]
    dll.obsbot_get_device_info.restype = ctypes.c_int32
    dll.obsbot_get_video_formats.argtypes = [
        ctypes.c_int32,
        ctypes.POINTER(ObsbotVideoFormatInfo),
        ctypes.c_int32,
    ]
    dll.obsbot_get_video_formats.restype = ctypes.c_int32
    dll.obsbot_get_camera_status.argtypes = [
        ctypes.c_int32,
        ctypes.POINTER(ObsbotCameraStatusInfo),
        ctypes.c_int32,
    ]
    dll.obsbot_get_camera_status.restype = ctypes.c_int32
    for name in (
        "obsbot_get_record_encode_param",
        "obsbot_get_output_encode_param",
        "obsbot_get_live_encode_param",
    ):
        fn = getattr(dll, name)
        fn.argtypes = [ctypes.c_int32, ctypes.POINTER(ObsbotEncodeParam), ctypes.c_int32]
        fn.restype = ctypes.c_int32
    dll.obsbot_set_record_encode_param.argtypes = [
        ctypes.c_int32,
        ctypes.POINTER(ObsbotEncodeParam),
        ctypes.c_int32,
    ]
    dll.obsbot_set_record_encode_param.restype = ctypes.c_int32
    dll.obsbot_set_output_encode_param.argtypes = [
        ctypes.c_int32,
        ctypes.POINTER(ObsbotEncodeParam),
        ctypes.c_int32,
    ]
    dll.obsbot_set_output_encode_param.restype = ctypes.c_int32
    dll.obsbot_get_media_operate_param.argtypes = [
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
    ]
    dll.obsbot_get_media_operate_param.restype = ctypes.c_int32
    for name in (
        "obsbot_get_usb_mode",
        "obsbot_is_mtp_stream_enabled",
        "obsbot_is_mtp_transferring_file",
    ):
        fn = getattr(dll, name)
        fn.argtypes = [ctypes.c_int32, ctypes.POINTER(ctypes.c_int32)]
        fn.restype = ctypes.c_int32
    dll.obsbot_set_usb_mode.argtypes = [ctypes.c_int32, ctypes.c_int32]
    dll.obsbot_set_usb_mode.restype = ctypes.c_int32
    dll.obsbot_set_mtp_stream_enabled.argtypes = [ctypes.c_int32, ctypes.c_int32]
    dll.obsbot_set_mtp_stream_enabled.restype = ctypes.c_int32
    dll.obsbot_close.argtypes = []
    dll.obsbot_close.restype = None


def load_wrapper() -> ctypes.CDLL:
    if not WRAPPER_DLL.exists():
        raise FileNotFoundError(f"wrapper DLL not found: {WRAPPER_DLL}")
    os.add_dll_directory(str(WRAPPER_DIR))
    dll = ctypes.CDLL(str(WRAPPER_DLL))
    bind(dll)
    return dll


def print_encode(dll: ctypes.CDLL, index: int, fn_name: str, title: str) -> None:
    param = ObsbotEncodeParam()
    ret = getattr(dll, fn_name)(index, ctypes.byref(param), 0)
    print(f"  {title}: ret={ret}", end="")
    if ret == 0:
        print(
            f" width={param.width} height={param.height} fps={param.fps} "
            f"bitrate={param.bitrate} enc={param.encode_format}"
        )
    else:
        print()


def print_status(dll: ctypes.CDLL, index: int, force_query: bool) -> None:
    status = ObsbotCameraStatusInfo()
    ret = dll.obsbot_get_camera_status(index, ctypes.byref(status), int(force_query))
    label = "queried" if force_query else "cached"
    print(f"  cameraStatus({label}): ret={ret} query_ret={status.query_ret}")
    print(
        "    "
        f"product={status.product_type}({PRODUCT_NAMES.get(status.product_type, '?')}) "
        f"mode={status.dev_mode}({MODE_NAMES.get(status.dev_mode, '?')}) "
        f"tiny.fps={status.tiny_fps} tiny.dev_status={status.tiny_dev_status} "
        f"tiny.hdr={status.tiny_hdr} tiny.live={status.tiny_live_stream_mode} "
        f"tiny.fov={status.tiny_fov} tiny.vertical={status.tiny_vertical} "
        f"usb_status={status.tiny_usb_status}"
    )


def run_opencv_probe() -> int:
    # OpenCV index mapping is host-local. On this machine Tiny SE is index 2;
    # keep this probe pinned so it does not open phone/virtual cameras.
    cmd = [
        sys.executable,
        str(ROOT / "explore_opencv.py"),
        "--min-index",
        "2",
        "--max-index",
        "2",
        "--backend",
        "DSHOW",
        "--backend",
        "ANY",
        "--mode",
        "default",
        "--timeout",
        "10",
    ]
    print("\n=== OpenCV default-read probe after SDK diagnostics ===")
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--set-record-100", action="store_true")
    parser.add_argument("--opencv", action="store_true", help="Run default-read OpenCV probe after SDK diagnostics")
    args = parser.parse_args()

    dll = load_wrapper()
    try:
        print(f"Refreshing devices ({args.wait_ms} ms)...")
        count = dll.obsbot_refresh_devices(args.wait_ms)
        print(f"Device count: {count}")
        if count <= 0:
            return 1

        for index in range(count):
            info = ObsbotDeviceInfo()
            ret = dll.obsbot_get_device_info(index, ctypes.byref(info))
            print(f"\n--- Device {index} info ret={ret} ---")
            print(f"  SN: {cstr(info.sn)}")
            print(f"  Name: {cstr(info.name)}")
            print(f"  Version: {cstr(info.version)}")
            print(f"  ProductType: {info.product_type} ({PRODUCT_NAMES.get(info.product_type, '?')})")
            print(f"  DevMode: {info.dev_mode} ({MODE_NAMES.get(info.dev_mode, '?')})")
            print(f"  VideoFriendlyName: {cstr(info.video_friendly_name)}")
            print(f"  VideoPath: {cstr(info.video_path)}")

            formats = (ObsbotVideoFormatInfo * 64)()
            total = dll.obsbot_get_video_formats(index, formats, len(formats))
            print(f"\n  videoFormatInfo total={total}")
            for item in formats[: max(0, min(total, len(formats)))]:
                print(
                    f"    {item.width}x{item.height} fps=[{item.fps_min},{item.fps_max}] "
                    f"{FMT_NAMES.get(item.format, hex(item.format))}"
                )

            print("\n  status:")
            print_status(dll, index, force_query=False)
            print_status(dll, index, force_query=True)

            print("\n  encode getters:")
            print_encode(dll, index, "obsbot_get_record_encode_param", "record")
            print_encode(dll, index, "obsbot_get_output_encode_param", "output")
            print_encode(dll, index, "obsbot_get_live_encode_param", "live")

            print("\n  media operate getters:")
            for stream in STREAMS:
                action = ctypes.c_int32(-1)
                ret = dll.obsbot_get_media_operate_param(index, stream.stream_id, ctypes.byref(action))
                print(
                    f"    {stream.name:<6} id={stream.stream_id:<2} ret={ret:<3} "
                    f"action={action.value}({ACTION_NAMES.get(action.value, '?')})"
                )

            print("\n  mtp/usb read-only probes:")
            usb_mode = ctypes.c_int32(-1)
            ret = dll.obsbot_get_usb_mode(index, ctypes.byref(usb_mode))
            print(f"    get_usb_mode: ret={ret} mode={usb_mode.value}({USB_MODE_NAMES.get(usb_mode.value, '?')})")
            enabled = ctypes.c_int32(-1)
            ret = dll.obsbot_is_mtp_stream_enabled(index, ctypes.byref(enabled))
            print(f"    is_mtp_stream_enabled: ret={ret} enabled={enabled.value}")
            transferring = ctypes.c_int32(-1)
            ret = dll.obsbot_is_mtp_transferring_file(index, ctypes.byref(transferring))
            print(f"    is_mtp_transferring_file: ret={ret} transferring={transferring.value}")

            if args.set_record_100:
                print("\n  setting record encode fps=100 (explicitly requested)...")
                param = ObsbotEncodeParam(width=-1, height=-1, fps=100, bitrate=-1, encode_format=0)
                ret = dll.obsbot_set_record_encode_param(index, ctypes.byref(param), 0)
                print(f"    set_record_encode_param -> {ret}")
                print_status(dll, index, force_query=True)

        if args.opencv:
            run_opencv_probe()
        return 0
    finally:
        dll.obsbot_close()


if __name__ == "__main__":
    raise SystemExit(main())
