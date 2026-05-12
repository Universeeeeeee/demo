"""Tiny SE SDK 诊断：直接探测 libdev.dll 可用入口"""
import ctypes
import os
import sys
from pathlib import Path

def main():
    sdk_dir = Path(__file__).resolve().parent.parents[2] / "camera" / "sdk" / "libdev_v2.1.0_8" / "windows" / "win64-release"
    dll_path = sdk_dir / "libdev.dll"
    pthread_path = sdk_dir / "w32-pthreads.dll"

    print(f"DLL: {dll_path}  (exists={dll_path.exists()})")
    print(f"pthread: {pthread_path}  (exists={pthread_path.exists()})")

    # 加载 pthread 先
    if pthread_path.exists():
        ctypes.CDLL(str(pthread_path))

    # 加载 libdev
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(sdk_dir))

    try:
        dll = ctypes.WinDLL(str(dll_path))
        print(f"WinDLL 加载: OK")
    except Exception as e:
        print(f"WinDLL 加载失败: {e}")
        return

    # 方法1: 直接用 ctypes 的 __dict__ 看有多少属性
    attrs = [a for a in dir(dll) if not a.startswith('_')]
    print(f"\ndir(dll) 导出的属性数量: {len(attrs)}")
    if attrs:
        print(f"前20个: {attrs[:20]}")

    # 方法2: 用 pefile 详细诊断
    try:
        import pefile
        pe = pefile.PE(str(dll_path))
        exp = pe.DIRECTORY_ENTRY_EXPORT

        print(f"\npefile 导出表:")
        print(f"  符号总数: {len(exp.symbols)}")

        named = [s for s in exp.symbols if s.name]
        ordinal_only = [s for s in exp.symbols if not s.name]
        print(f"  有名称: {len(named)}, 仅 ordinal: {len(ordinal_only)}")

        if named:
            print(f"\n  有名称的符号 (前50):")
            for s in named[:50]:
                print(f"    ord={s.ordinal:4d}  rva=0x{s.address:08X}  name={s.name.decode(errors='replace')}")

        # 按名称搜索关键符号
        keywords = ['get', 'device', 'devices', 'camera', 'set', 'video', 'format', 'record', 'fps', 'obsbot']
        found = set()
        for s in named:
            name = s.name.decode(errors='replace').lower()
            for kw in keywords:
                if kw in name:
                    found.add(s.name.decode(errors='replace'))

        if found:
            print(f"\n  关键词命中 ({len(found)}):")
            for f in sorted(found):
                print(f"    {f}")

        pe.close()
    except ImportError:
        print("\npefile 未安装")
    except Exception as e:
        print(f"\npefile 解析失败: {e}")
        import traceback
        traceback.print_exc()

    # 方法3: 尝试一些常见导出名
    print("\n直接尝试常见导出名:")
    candidates = [
        # C 风格 (extern "C")
        "devices_get",
        "obsbot_devices_get",
        "dev_get_devices",
        "get_devices",
        "get_dev_list",
        "devices_get_dev_list",
        "dev_init",
        "dev_open",
        "dev_close",
        # C++ mangled
        "?_get@Devices@@SAAEAV1@XZ",
        "?get@Devices@@SAAEAV1@XZ",
    ]
    for name in candidates:
        try:
            fn = getattr(dll, name)
            print(f"  {name}: 找到, type={type(fn)}")
            try:
                fn.restype = ctypes.c_void_p
                result = fn()
                print(f"    调用结果: 0x{result:x}" if result else f"    调用结果: NULL/0")
            except Exception as e2:
                print(f"    调用失败: {e2}")
        except AttributeError:
            pass  # not found

    print("\n诊断完成。")

if __name__ == "__main__":
    main()
