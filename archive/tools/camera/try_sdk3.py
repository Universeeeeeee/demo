"""全函数 argtypes 显式声明的 SDK 测试"""
import ctypes, os, struct, time
from pathlib import Path

SDK = Path(__file__).resolve().parent.parents[2] / "camera" / "sdk" / "libdev_v2.1.0_8" / "windows" / "win64-release"

def make_string(data: bytes) -> bytes:
    """构造 MSVC std::string SSO: 32 bytes total"""
    assert len(data) <= 15
    buf = bytearray(32)
    buf[0:len(data)] = data
    struct.pack_into('Q', buf, 16, len(data))  # size
    struct.pack_into('Q', buf, 24, 15)          # capacity
    return bytes(buf)

def main():
    os.add_dll_directory(str(SDK))
    ctypes.CDLL(str(SDK / "w32-pthreads.dll"))
    dll = ctypes.WinDLL(str(SDK / "libdev.dll"))
    print("DLL loaded\n")

    # Devices::get() — static, no params
    fn = getattr(dll, "?get@Devices@@SAAEAV1@XZ")
    fn.restype = ctypes.c_void_p
    devices = fn()
    print(f"Devices::get() -> 0x{devices:X}")
    time.sleep(5)

    # getDevNum — member, this only
    fn = getattr(dll, "?getDevNum@Devices@@QEAA_KXZ")
    fn.argtypes = [ctypes.c_void_p]
    fn.restype = ctypes.c_size_t
    print(f"getDevNum() -> {fn(devices)}")

    # getDevBySn — member, takes const string&, returns shared_ptr (16 bytes in RAX:RDX)
    sn_raw = make_string(b"RMOWCYHA081RCB")
    sn_buf = (ctypes.c_char * 32).from_buffer_copy(sn_raw)
    fn = getattr(dll, "?getDevBySn@Devices@@QEAA?AV?$shared_ptr@VDevice@@@std@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@3@@Z")
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]  # this, const string&
    fn.restype = ctypes.c_void_p  # RAX = Device*
    dev = fn(devices, ctypes.byref(sn_buf))
    print(f"getDevBySn -> Device* = 0x{dev:X}")

    if not dev:
        print("FAIL: Device pointer null")
        return

    # productType
    fn = getattr(dll, "?productType@Device@@QEAA?AW4ObsbotProductType@@XZ")
    fn.argtypes = [ctypes.c_void_p]
    fn.restype = ctypes.c_int
    pt = fn(dev)
    names = {2:"Tiny2", 12:"TinySE", 13:"MeetSE", 18:"Tiny3"}
    print(f"productType = {pt} ({names.get(pt, '?')})")

    # videoFormatInfo — returns vector by value (>16 bytes, hidden ptr)
    fn = getattr(dll, "?videoFormatInfo@Device@@QEAA?AV?$vector@VVideoFormatInfo@Device@@V?$allocator@VVideoFormatInfo@Device@@@std@@@std@@XZ")
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]  # hidden ret, this
    fn.restype = None
    vfi = (ctypes.c_char * 24)()
    fn(vfi, dev)
    v_start = ctypes.cast(vfi, ctypes.POINTER(ctypes.c_void_p))[0]
    v_end = ctypes.cast(ctypes.c_void_p(ctypes.addressof(vfi) + 8), ctypes.POINTER(ctypes.c_void_p))[0]
    if v_start and v_end and v_end > v_start:
        n = (v_end - v_start) // 24
        print(f"\nvideoFormatInfo: {n} formats")
        fmt_names = {200:"I420", 201:"NV12", 300:"YVYU", 301:"YUY2", 302:"UYVY", 400:"MJPEG", 401:"H264"}
        for j in range(min(n, 30)):
            off = j * 24
            w = ctypes.cast(ctypes.c_void_p(v_start + off), ctypes.POINTER(ctypes.c_int32))[0]
            h = ctypes.cast(ctypes.c_void_p(v_start + off + 4), ctypes.POINTER(ctypes.c_int32))[0]
            fmin = ctypes.cast(ctypes.c_void_p(v_start + off + 8), ctypes.POINTER(ctypes.c_int32))[0]
            fmax = ctypes.cast(ctypes.c_void_p(v_start + off + 12), ctypes.POINTER(ctypes.c_int32))[0]
            fmt = ctypes.cast(ctypes.c_void_p(v_start + off + 16), ctypes.POINTER(ctypes.c_int32))[0]
            print(f"  {w}x{h}  fps=[{fmin},{fmax}]  {fmt_names.get(fmt, f'0x{fmt:X}')}")
    else:
        print(f"videoFormatInfo: 解析失败 (start=0x{v_start:X}, end=0x{v_end:X})")

    # cameraSetRecordEncodeParamR — 设置 fps
    print("\n--- 设置 100fps ---")
    fn = getattr(dll, "?cameraSetRecordEncodeParamR@Device@@QEAAHAEBUDevMediaEncodeParam@1@_N@Z")
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]  # this, &param, night
    fn.restype = ctypes.c_int
    param = (ctypes.c_int32 * 5)(-1, -1, 100, -1, 0)  # width, height, fps, bitrate, encode_fmt
    r = fn(dev, param, False)
    print(f"setEncode(fps=100) -> {r} (0=OK)")

    # 读取确认
    fn = getattr(dll, "?cameraGetRecordEncodeParamR@Device@@QEAAHAEAUDevMediaEncodeParam@1@_N@Z")
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
    fn.restype = ctypes.c_int
    getp = (ctypes.c_int32 * 5)()
    r2 = fn(dev, getp, False)
    print(f"getEncode -> {r2}: w={getp[0]} h={getp[1]} fps={getp[2]} br={getp[3]} enc={getp[4]}")

    # cameraSetRecordResolutionR
    print("\n--- 设置录制分辨率 ---")
    fn = getattr(dll, "?cameraSetRecordResolutionR@Device@@QEAAHW4DevVideoResType@1@@Z")
    fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
    fn.restype = ctypes.c_int
    for v, l in [(0x24,"1080P60"), (0x34,"720P60"), (0x21,"1080P30")]:
        print(f"  setRecordResolution({l}) -> {fn(dev, v)}")

    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
