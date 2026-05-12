"""快速诊断：SDK 控制函数是否可用。不开启 DirectShow，排除资源竞争。"""
import ctypes, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT.parents[2] / "camera" / "bin"
os.add_dll_directory(str(BIN_DIR))
dll = ctypes.CDLL(str(BIN_DIR / "obsbot_c_api.dll"))

# bind
dll.obsbot_refresh_devices.argtypes = [ctypes.c_int32]
dll.obsbot_refresh_devices.restype = ctypes.c_int32
for name in (
    "obsbot_set_camera_mirror",
    "obsbot_set_ai_mode",
    "obsbot_set_auto_focus",
    "obsbot_set_manual_focus",
    "obsbot_set_fov",
    "obsbot_set_wdr",
):
    fn = getattr(dll, name)
    fn.argtypes = [ctypes.c_int32, ctypes.c_int32]
    fn.restype = ctypes.c_int32
dll.obsbot_set_ai_mode.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
dll.obsbot_close.argtypes = []
dll.obsbot_close.restype = None

# refresh
count = dll.obsbot_refresh_devices(5000)
print(f"refresh_devices -> {count}")
if count <= 0:
    print("FAIL: no devices")
    exit(1)

# test each control
tests = [
    ("mirror=1",         dll.obsbot_set_camera_mirror(0, 1)),
    ("mirror=0",         dll.obsbot_set_camera_mirror(0, 0)),
    ("auto_focus=1",     dll.obsbot_set_auto_focus(0, 1)),
    ("auto_focus=0",     dll.obsbot_set_auto_focus(0, 0)),
    ("fov=0 (86°)",      dll.obsbot_set_fov(0, 0)),
    ("fov=1 (78°)",      dll.obsbot_set_fov(0, 1)),
    ("wdr=0 (off)",      dll.obsbot_set_wdr(0, 0)),
    ("ai_off (0,0)",     dll.obsbot_set_ai_mode(0, 0, 0)),
    ("ai_lower (2,4)",   dll.obsbot_set_ai_mode(0, 2, 4)),
]

print("\n--- control test (no DirectShow) ---")
for label, ret in tests:
    status = "OK" if ret >= 0 else f"ERR({ret})"
    print(f"  {status}  {label}")

dll.obsbot_close()
print("\ndone")
