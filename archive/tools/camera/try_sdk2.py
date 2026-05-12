"""shared_ptr 16字节走 RAX:RDX 返回，不用 hidden pointer"""
import ctypes
import os
import struct
import time
from pathlib import Path

def get_fn(dll, mangled_name, restype, *argtypes):
    addr = ctypes.cast(getattr(dll, mangled_name), ctypes.c_void_p).value
    return ctypes.CFUNCTYPE(restype, *argtypes)(addr)

def make_string(data: bytes) -> bytes:
    assert len(data) <= 15
    buf = bytearray(32)
    buf[0:len(data)] = data
    struct.pack_into('Q', buf, 16, len(data))
    struct.pack_into('Q', buf, 24, 15)
    return bytes(buf)

def main():
sdk_dir = Path(__file__).resolve().parent.parents[2] / "camera" / "sdk" / "libdev_v2.1.0_8" / "windows" / "win64-release"
    dll_path = str(sdk_dir / "libdev.dll")

    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(sdk_dir))
    ctypes.CDLL(str(sdk_dir / "w32-pthreads.dll"))
    dll = ctypes.WinDLL(dll_path)
    print("DLL loaded\n")

    Devices_get = get_fn(dll, "?get@Devices@@SAAEAV1@XZ", ctypes.c_void_p)
    devices = Devices_get()
    print(f"Devices::get() -> 0x{devices:X}")
    time.sleep(5)

    # getDevBySn: shared_ptr<Device> 返回在 RAX:RDX (16 bytes)
    # 签名为: shared_ptr getDevBySn(Devices* this, const string& sn)
    # RAX = Device* 就是我们要的值
    Device_getDevBySn = get_fn(dll,
        "?getDevBySn@Devices@@QEAA?AV?$shared_ptr@VDevice@@@std@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@3@@Z",
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    sn_str = make_string(b"RMOWCYHA081RCB")
    dev = Device_getDevBySn(devices, sn_str)
    print(f"getDevBySn -> Device* = 0x{dev:X}\n")

    if not dev or dev > 0x7FFFFFFFFFFF:
        print(f"获取 Device 指针异常 (0x{dev:X})")
        return

    # productType
    Device_productType = get_fn(dll,
        "?productType@Device@@QEAA?AW4ObsbotProductType@@XZ",
        ctypes.c_int, ctypes.c_void_p)
    pt = Device_productType(dev)
    names = {2:"Tiny2", 12:"TinySE", 13:"MeetSE", 18:"Tiny3"}
    print(f"ProductType: {pt} ({names.get(pt, '?')})")

    # videoFormatInfo — vector<VideoFormatInfo> 是 24 bytes, > 16, 走 hidden ptr
    Device_vfi = get_fn(dll,
        "?videoFormatInfo@Device@@QEAA?AV?$vector@VVideoFormatInfo@Device@@V?$allocator@VVideoFormatInfo@Device@@@std@@@std@@XZ",
        None, ctypes.c_void_p, ctypes.c_void_p)
    vfi_buf = (ctypes.c_char * 24)()
    Device_vfi(vfi_buf, dev)

    v_start = ctypes.cast(vfi_buf, ctypes.POINTER(ctypes.c_void_p))[0]
    v_end = ctypes.cast(ctypes.c_void_p(ctypes.addressof(vfi_buf) + 8), ctypes.POINTER(ctypes.c_void_p))[0]

    if v_start and v_end and v_end > v_start:
        elem_size = 24
        n = (v_end - v_start) // elem_size
        print(f"\nvideoFormatInfo: {n} formats")
        for j in range(min(n, 30)):
            off = j * elem_size
            w = ctypes.cast(ctypes.c_void_p(v_start + off), ctypes.POINTER(ctypes.c_int32))[0]
            h = ctypes.cast(ctypes.c_void_p(v_start + off + 4), ctypes.POINTER(ctypes.c_int32))[0]
            fmin = ctypes.cast(ctypes.c_void_p(v_start + off + 8), ctypes.POINTER(ctypes.c_int32))[0]
            fmax = ctypes.cast(ctypes.c_void_p(v_start + off + 12), ctypes.POINTER(ctypes.c_int32))[0]
            fmt = ctypes.cast(ctypes.c_void_p(v_start + off + 16), ctypes.POINTER(ctypes.c_int32))[0]
            fmt_names = {200:"I420", 201:"NV12", 300:"YVYU", 301:"YUY2", 302:"UYVY", 400:"MJPEG", 401:"H264"}
            print(f"  {w}x{h}  fps=[{fmin},{fmax}]  {fmt_names.get(fmt, f'0x{fmt:X}')}")
    else:
        print(f"videoFormatInfo: 解析失败 (start=0x{v_start:X}, end=0x{v_end:X})")

    # cameraSetRecordEncodeParamR
    print("\n--- 设置 100fps ---")
    Device_setEncode = get_fn(dll,
        "?cameraSetRecordEncodeParamR@Device@@QEAAHAEBUDevMediaEncodeParam@1@_N@Z",
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)

    param = (ctypes.c_int32 * 5)(-1, -1, 100, -1, 0)
    r = Device_setEncode(dev, param, False)
    print(f"cameraSetRecordEncodeParamR(fps=100) -> {r} (0=OK)")

    # 读取确认
    Device_getEncode = get_fn(dll,
        "?cameraGetRecordEncodeParamR@Device@@QEAAHAEAUDevMediaEncodeParam@1@_N@Z",
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
    get_param = (ctypes.c_int32 * 5)()
    r2 = Device_getEncode(dev, get_param, False)
    print(f"cameraGetRecordEncodeParamR -> {r2}")
    print(f"  width={get_param[0]} height={get_param[1]} fps={get_param[2]} bitrate={get_param[3]} enc={get_param[4]}")

    # 同时试 cameraSetRecordResolutionR
    print("\n--- 设置录制分辨率 ---")
    Device_setRes = get_fn(dll,
        "?cameraSetRecordResolutionR@Device@@QEAAHW4DevVideoResType@1@@Z",
        ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    for res_val, lbl in [(0x24, "1080P60"), (0x2C, "1080P59.94"), (0x21, "1080P30")]:
        rr = Device_setRes(dev, res_val)
        print(f"  cameraSetRecordResolutionR({lbl}) -> {rr}")

    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
