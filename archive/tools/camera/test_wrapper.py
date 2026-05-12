"""通过 C wrapper 测试 Tiny SE SDK 功能"""
import ctypes
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WRAPPER_DIR = ROOT.parents[2] / "camera" / "bin"

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

def main():
    os.add_dll_directory(str(WRAPPER_DIR))
    dll = ctypes.CDLL(str(WRAPPER_DIR / "obsbot_c_api.dll"))

    # 函数签名
    dll.obsbot_refresh_devices.argtypes = [ctypes.c_int32]
    dll.obsbot_refresh_devices.restype = ctypes.c_int32

    dll.obsbot_get_device_count.argtypes = []
    dll.obsbot_get_device_count.restype = ctypes.c_int32

    dll.obsbot_get_device_info.argtypes = [ctypes.c_int32, ctypes.POINTER(ObsbotDeviceInfo)]
    dll.obsbot_get_device_info.restype = ctypes.c_int32

    dll.obsbot_get_video_formats.argtypes = [ctypes.c_int32, ctypes.POINTER(ObsbotVideoFormatInfo), ctypes.c_int32]
    dll.obsbot_get_video_formats.restype = ctypes.c_int32

    dll.obsbot_set_record_encode_param.argtypes = [ctypes.c_int32, ctypes.POINTER(ObsbotEncodeParam), ctypes.c_int32]
    dll.obsbot_set_record_encode_param.restype = ctypes.c_int32

    dll.obsbot_get_record_encode_param.argtypes = [ctypes.c_int32, ctypes.POINTER(ObsbotEncodeParam), ctypes.c_int32]
    dll.obsbot_get_record_encode_param.restype = ctypes.c_int32

    # 刷新设备
    print("Refreshing devices (wait 5s)...")
    count = dll.obsbot_refresh_devices(5000)
    print(f"Device count: {count}")

    if count <= 0:
        print("No OBSBOT devices found")
        return

    # 获取设备信息
    for i in range(count):
        info = ObsbotDeviceInfo()
        dll.obsbot_get_device_info(i, ctypes.byref(info))
        sn = info.sn.decode('utf-8', errors='replace')
        name = info.name.decode('utf-8', errors='replace')
        ver = info.version.decode('utf-8', errors='replace')
        vpath = info.video_path.decode('utf-8', errors='replace')
        vname = info.video_friendly_name.decode('utf-8', errors='replace')
        pt_names = {2:"Tiny2", 5:"Meet", 6:"Meet4K", 10:"Meet2", 12:"TinySE", 13:"MeetSE", 18:"Tiny3"}
        print(f"\n--- Device {i} ---")
        print(f"  SN: {sn}")
        print(f"  Name: {name}")
        print(f"  Version: {ver}")
        print(f"  ProductType: {info.product_type} ({pt_names.get(info.product_type, '?')})")
        print(f"  DevMode: {info.dev_mode} (0=UVC, 1=Net, 2=MTP)")
        print(f"  VideoPath: {vpath}")
        print(f"  VideoFriendlyName: {vname}")

        # 获取 videoFormatInfo
        formats = (ObsbotVideoFormatInfo * 100)()
        total = dll.obsbot_get_video_formats(i, formats, 100)
        print(f"\n  videoFormatInfo (total={total}):")
        fmt_names = {200:"I420", 201:"NV12", 300:"YVYU", 301:"YUY2", 302:"UYVY", 400:"MJPEG", 401:"H264", 402:"HEVC"}
        for j in range(min(total, 100)):
            f = formats[j]
            print(f"    {f.width}x{f.height}  fps=[{f.fps_min},{f.fps_max}]  {fmt_names.get(f.format, f'0x{f.format:X}')}")

        # 尝试设置 100fps
        print(f"\n  Setting record encode param (fps=100)...")
        param = ObsbotEncodeParam(width=-1, height=-1, fps=100, bitrate=-1, encode_format=0)
        ret = dll.obsbot_set_record_encode_param(i, ctypes.byref(param), 0)
        print(f"  obsbot_set_record_encode_param -> {ret} (0=OK, -1=ERR, -4=EXCEPTION)")

        # 读取确认
        print(f"\n  Reading back encode param...")
        out = ObsbotEncodeParam()
        ret2 = dll.obsbot_get_record_encode_param(i, ctypes.byref(out), 0)
        print(f"  obsbot_get_record_encode_param -> {ret2}")
        if ret2 >= 0:
            print(f"    width={out.width} height={out.height} fps={out.fps} bitrate={out.bitrate} enc={out.encode_format}")

    dll.obsbot_close()

if __name__ == "__main__":
    main()
