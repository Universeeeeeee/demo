"""Tiny SE SDK 直调：尝试调用关键函数"""
import ctypes
import os
import time
from pathlib import Path

def get_fn(dll, mangled_name, restype, *argtypes):
    """Get a ctypes callable from a mangled C++ export name."""
    addr = ctypes.cast(getattr(dll, mangled_name), ctypes.c_void_p).value
    proto = ctypes.CFUNCTYPE(restype, *argtypes)
    return proto(addr)

def main():
    sdk_dir = Path(__file__).resolve().parent.parents[2] / "camera" / "sdk" / "libdev_v2.1.0_8" / "windows" / "win64-release"
    dll_path = str(sdk_dir / "libdev.dll")
    pthread_path = str(sdk_dir / "w32-pthreads.dll")

    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(sdk_dir))

    ctypes.CDLL(pthread_path)
    dll = ctypes.WinDLL(dll_path)
    print("DLL loaded: OK\n")

    # 1. Devices::get() — static, returns Devices& (pointer)
    Devices_get = get_fn(dll, "?get@Devices@@SAAEAV1@XZ", ctypes.c_void_p)
    devices = Devices_get()
    print(f"Devices::get() -> 0x{devices:X}")

    # 等待设备检测线程完成（参考 OBSBOT_Sample 里的 sleep_for(3000)）
    print("等待设备检测...")
    time.sleep(5)

    # 2. getDevNum() — member, returns size_t
    Devices_getDevNum = get_fn(dll, "?getDevNum@Devices@@QEAA_KXZ", ctypes.c_size_t, ctypes.c_void_p)
    count = Devices_getDevNum(devices)
    print(f"getDevNum() -> {count}")

    if count == 0:
        print("SDK 未检测到 OBSBOT 设备")
        return

    print(f"\n=== 发现 {count} 个 OBSBOT 设备 ===\n")

    # 3. getDevList — 返回 std::list<shared_ptr<Device>> by value
    # MSVC x64: 隐藏 this 前插入返回缓冲区指针
    # 函数实际: void getDevList(list_buf* __ret, Devices* __this)
    Devices_getDevList = get_fn(dll,
        "?getDevList@Devices@@QEAA?AV?$list@V?$shared_ptr@VDevice@@@std@@V?$allocator@V?$shared_ptr@VDevice@@@std@@@2@@std@@XZ",
        None, ctypes.c_void_p, ctypes.c_void_p)

    # std::list MSVC x64 layout (Release): { _List_node* head; size_t size; } = 16 bytes
    list_buf = (ctypes.c_char * 24)()
    Devices_getDevList(list_buf, devices)

    head = ctypes.cast(list_buf, ctypes.POINTER(ctypes.c_void_p))[0]
    print(f"list head: 0x{head:X}")

    if not head:
        print("空列表(可能是 ABI 不匹配)")
        return

    # 遍历链表
    # 节点布局: { next(8), prev(8), shared_ptr<Device>(16) }
    current = head
    device_ptrs = []
    for _ in range(count + 1):
        node = (ctypes.c_char * 32)()
        ctypes.memmove(node, ctypes.c_void_p(current), 32)
        next_ptr = ctypes.cast(node, ctypes.POINTER(ctypes.c_void_p))[0]
        dev_ptr = ctypes.cast(
            ctypes.c_void_p(ctypes.addressof(node) + 16),
            ctypes.POINTER(ctypes.c_void_p)
        )[0]

        if next_ptr == head:
            break
        if dev_ptr and dev_ptr != 0xDDDDDDDDDDDDDDDD:
            device_ptrs.append(dev_ptr)
        current = next_ptr

    print(f"遍历到 {len(device_ptrs)} 个设备\n")

    if not device_ptrs:
        print("未能获取设备指针（STL 布局解析失败，换方案）")
        return

    for i, dev in enumerate(device_ptrs):
        print(f"--- 设备 {i} (Device* = 0x{dev:X}) ---")

        # devSn — 返回 std::string by value (MSVC x64: hidden ptr first)
        Device_devSn = get_fn(dll,
            "?devSn@Device@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@XZ",
            None, ctypes.c_void_p, ctypes.c_void_p)
        sn_buf = (ctypes.c_char * 32)()
        Device_devSn(sn_buf, dev)
        sn = sn_buf.raw.decode('utf-8', errors='replace').split('\x00')[0]
        print(f"  SN: {sn}")

        # devName — 返回 const string& (即内部指针)
        Device_devName = get_fn(dll,
            "?devName@Device@@QEAAAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@XZ",
            ctypes.c_void_p, ctypes.c_void_p)
        name_ptr = Device_devName(dev)
        if name_ptr:
            name_data = (ctypes.c_char * 64)()
            ctypes.memmove(name_data, name_ptr, 64)
            name = name_data.raw.decode('utf-8', errors='replace').split('\x00')[0]
            print(f"  Name: {name}")

        # productType — 返回 int
        Device_productType = get_fn(dll,
            "?productType@Device@@QEAA?AW4ObsbotProductType@@XZ",
            ctypes.c_int, ctypes.c_void_p)
        pt = Device_productType(dev)
        names = {2:"Tiny2", 5:"Meet", 6:"Meet4K", 10:"Meet2", 12:"TinySE", 13:"MeetSE", 18:"Tiny3"}
        print(f"  ProductType: {pt} ({names.get(pt, '?')})")

        # videoFormatInfo — 返回 vector<VideoFormatInfo> by value
        Device_videoFormatInfo = get_fn(dll,
            "?videoFormatInfo@Device@@QEAA?AV?$vector@VVideoFormatInfo@Device@@V?$allocator@VVideoFormatInfo@Device@@@std@@@std@@XZ",
            None, ctypes.c_void_p, ctypes.c_void_p)
        vfi_buf = (ctypes.c_char * 24)()
        Device_videoFormatInfo(vfi_buf, dev)

        # std::vector MSVC x64 layout: { ptr(8), ptr(8), ptr(8) } = start, end, capacity
        v_start = ctypes.cast(vfi_buf, ctypes.POINTER(ctypes.c_void_p))[0]
        v_end = ctypes.cast(
            ctypes.c_void_p(ctypes.addressof(vfi_buf) + 8),
            ctypes.POINTER(ctypes.c_void_p)
        )[0]

        if v_start and v_end and v_end > v_start:
            elem_size = 24  # VideoFormatInfo: width(4)+height(4)+fps_min(4)+fps_max(4)+format(4) + padding
            total_bytes = v_end - v_start
            n = total_bytes // elem_size
            print(f"  videoFormatInfo: {n} 个格式")
            for j in range(min(n, 20)):
                off = j * elem_size
                w = ctypes.cast(
                    ctypes.c_void_p(v_start + off), ctypes.POINTER(ctypes.c_int32)
                )[0]
                h = ctypes.cast(
                    ctypes.c_void_p(v_start + off + 4), ctypes.POINTER(ctypes.c_int32)
                )[0]
                fps_min = ctypes.cast(
                    ctypes.c_void_p(v_start + off + 8), ctypes.POINTER(ctypes.c_int32)
                )[0]
                fps_max = ctypes.cast(
                    ctypes.c_void_p(v_start + off + 12), ctypes.POINTER(ctypes.c_int32)
                )[0]
                fmt = ctypes.cast(
                    ctypes.c_void_p(v_start + off + 16), ctypes.POINTER(ctypes.c_int32)
                )[0]
                fmt_names = {200:"I420", 201:"NV12", 202:"YV12", 300:"YVYU", 301:"YUY2", 302:"UYVY", 400:"MJPEG", 401:"H264", 402:"HEVC"}
                print(f"    {w}x{h}  fps=[{fps_min},{fps_max}]  {fmt_names.get(fmt, f'fourcc={fmt}')}")
        else:
            print(f"  videoFormatInfo: 空 (v_start=0x{v_start:X}, v_end=0x{v_end:X})")

        # 测试: cameraSetRecordEncodeParamR — 尝试设置 fps=100
        # DevMediaEncodeParam: width(4), height(4), fps(4), bitrate(4), encode_format(4)
        print(f"\n  尝试设置录制编码参数 (100fps)...")
        Device_setEncode = get_fn(dll,
            "?cameraSetRecordEncodeParamR@Device@@QEAAHAEBUDevMediaEncodeParam@1@_N@Z",
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)

        # DevMediaEncodeParam 布局: width=-1, height=-1, fps=100, bitrate=-1, encode_format=0
        param = (ctypes.c_int32 * 5)(-1, -1, 100, -1, 0)  # -1 = keep current
        result = Device_setEncode(dev, param, False)
        print(f"  cameraSetRecordEncodeParamR(fps=100) -> {result} (0=OK, -1=ERR)")

        # 再试 cameraSetRecordResolutionR — 用 DevVideoResType 枚举
        # DevVideoResType list: 1080P60=0x24, 1080P120 (if exists)
        print(f"\n  尝试设置录制分辨率...")
        Device_setRes = get_fn(dll,
            "?cameraSetRecordResolutionR@Device@@QEAAHW4DevVideoResType@1@@Z",
            ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
        # Check if there's a 1080P120 type... let's try some values
        for res_type, label in [(0x24, "1080P60"), (0x2C, "1080P59.94"), (0x21, "1080P30")]:
            r = Device_setRes(dev, res_type)
            print(f"  cameraSetRecordResolutionR({label}) -> {r}")

    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
