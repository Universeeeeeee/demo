"""Limited Tiny SE MTP feasibility probe.

This script intentionally does not reverse engineer any private frame protocol.
It only checks whether the SDK/Windows expose an MTP mode and whether the SDK
reports an MTP stream flag after switching.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

from diagnose_tiny_se import (
    MODE_NAMES,
    PRODUCT_NAMES,
    USB_MODE_NAMES,
    ObsbotCameraStatusInfo,
    ObsbotDeviceInfo,
    bind,
    cstr,
)


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
CAMERA_DIR = PROJECT_ROOT / "camera"
WRAPPER_DIR = CAMERA_DIR / "bin"
WRAPPER_DLL = WRAPPER_DIR / "obsbot_c_api.dll"

TINY_SE_PRODUCT_TYPE = 12
USB_MODE_UVC_UAC = 1
USB_MODE_MTP = 4


def load_wrapper() -> ctypes.CDLL:
    if not WRAPPER_DLL.exists():
        raise FileNotFoundError(f"wrapper DLL not found: {WRAPPER_DLL}")
    os.add_dll_directory(str(WRAPPER_DIR))
    dll = ctypes.CDLL(str(WRAPPER_DLL))
    bind(dll)
    return dll


def refresh(dll: ctypes.CDLL, wait_ms: int) -> int:
    count = dll.obsbot_refresh_devices(wait_ms)
    print(f"SDK device count: {count}")
    return count


def find_tiny_se(dll: ctypes.CDLL, count: int) -> int | None:
    for index in range(max(0, count)):
        info = ObsbotDeviceInfo()
        ret = dll.obsbot_get_device_info(index, ctypes.byref(info))
        if ret != 0:
            continue
        if info.product_type == TINY_SE_PRODUCT_TYPE or "Tiny SE" in cstr(info.video_friendly_name):
            return index
    return None


def print_device_snapshot(dll: ctypes.CDLL, index: int) -> None:
    info = ObsbotDeviceInfo()
    ret = dll.obsbot_get_device_info(index, ctypes.byref(info))
    print(f"\nTiny SE device info ret={ret}")
    print(f"  SN: {cstr(info.sn)}")
    print(f"  Name: {cstr(info.name)}")
    print(f"  ProductType: {info.product_type} ({PRODUCT_NAMES.get(info.product_type, '?')})")
    print(f"  DevMode: {info.dev_mode} ({MODE_NAMES.get(info.dev_mode, '?')})")
    print(f"  VideoFriendlyName: {cstr(info.video_friendly_name)}")
    print(f"  VideoPath: {cstr(info.video_path)}")

    status = ObsbotCameraStatusInfo()
    ret = dll.obsbot_get_camera_status(index, ctypes.byref(status), 1)
    print(f"  cameraStatus ret={ret}: tiny.fps={status.tiny_fps} tiny.live={status.tiny_live_stream_mode}")

    usb_mode = ctypes.c_int32(-1)
    ret = dll.obsbot_get_usb_mode(index, ctypes.byref(usb_mode))
    print(f"  get_usb_mode ret={ret}: {usb_mode.value} ({USB_MODE_NAMES.get(usb_mode.value, '?')})")

    enabled = ctypes.c_int32(-1)
    ret = dll.obsbot_is_mtp_stream_enabled(index, ctypes.byref(enabled))
    print(f"  is_mtp_stream_enabled ret={ret}: {enabled.value}")

    transferring = ctypes.c_int32(-1)
    ret = dll.obsbot_is_mtp_transferring_file(index, ctypes.byref(transferring))
    print(f"  is_mtp_transferring_file ret={ret}: {transferring.value}")


def print_windows_mtp_devices() -> None:
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            "Get-PnpDevice -PresentOnly | "
            "Where-Object { $_.FriendlyName -match 'OBSBOT|Tiny|MTP|Portable|WPD' -or $_.InstanceId -match 'VID_3564|PID_FEFF' } | "
            "Select-Object Status,Class,FriendlyName,InstanceId | Format-Table -AutoSize"
        ),
    ]
    print("\nWindows PnP devices matching OBSBOT/MTP:")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    text = (proc.stdout or proc.stderr).strip()
    print(text if text else "  (none)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--switch-mtp", action="store_true", help="Actually request USB mode MTP")
    parser.add_argument(
        "--enable-mtp-stream",
        action="store_true",
        help="After switching/refreshing, call setMtpStreamEnabled(true). This is off by default.",
    )
    parser.add_argument(
        "--restore-uvc",
        action="store_true",
        help="At the end, request USB mode UVC+UAC if SDK can still see Tiny SE.",
    )
    parser.add_argument("--post-switch-wait-ms", type=int, default=8000)
    args = parser.parse_args()

    dll = load_wrapper()
    try:
        print("=== Baseline SDK snapshot ===")
        count = refresh(dll, args.wait_ms)
        index = find_tiny_se(dll, count)
        if index is None:
            print("Tiny SE not found by SDK.")
            print_windows_mtp_devices()
            return 1
        print_device_snapshot(dll, index)
        print_windows_mtp_devices()

        if not args.switch_mtp:
            print("\nNo mode switch requested. Use --switch-mtp for the limited MTP test.")
            return 0

        print("\n=== Requesting USB mode MTP ===")
        ret = dll.obsbot_set_usb_mode(index, USB_MODE_MTP)
        print(f"set_usb_mode(MTP=4) -> {ret}")
        dll.obsbot_close()

        print(f"Waiting {args.post_switch_wait_ms} ms for USB re-enumeration...")
        time.sleep(max(0, args.post_switch_wait_ms) / 1000.0)
        print_windows_mtp_devices()

        print("\n=== Post-switch SDK snapshot ===")
        dll = load_wrapper()
        count = refresh(dll, args.wait_ms)
        index = find_tiny_se(dll, count)
        if index is None:
            print("Tiny SE is not visible to SDK after MTP request.")
            print("This suggests no SDK-visible realtime MTP stream endpoint in this state.")
            return 2

        print_device_snapshot(dll, index)

        if args.enable_mtp_stream:
            print("\n=== Requesting MTP stream enable ===")
            ret = dll.obsbot_set_mtp_stream_enabled(index, 1)
            print(f"set_mtp_stream_enabled(true) -> {ret}")
            time.sleep(2.0)
            print_device_snapshot(dll, index)

        if args.restore_uvc:
            print("\n=== Requesting USB mode UVC+UAC restore ===")
            ret = dll.obsbot_set_usb_mode(index, USB_MODE_UVC_UAC)
            print(f"set_usb_mode(UVC+UAC=1) -> {ret}")
            time.sleep(max(0, args.post_switch_wait_ms) / 1000.0)
            print_windows_mtp_devices()

        return 0
    finally:
        try:
            dll.obsbot_close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
