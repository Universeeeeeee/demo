import ctypes
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class StepResult:
    step: str
    ok: bool
    detail: str


def run_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return process.returncode, process.stdout, process.stderr
    except Exception as ex:  # pylint: disable=broad-except
        return -1, "", repr(ex)


def sdk_paths() -> Tuple[Path, Path, Path, Path, Path]:
    base = Path(__file__).resolve().parent.parents[2] / "camera" / "sdk" / "libdev_v2.1.0_8"
    win_release = base / "windows" / "win64-release"
    dll = win_release / "libdev.dll"
    pthread = win_release / "w32-pthreads.dll"
    include = base / "include"
    return base, win_release, dll, pthread, include


def get_exports_with_tools(dll_path: Path) -> Tuple[bool, str, str]:
    candidates = [
        ["dumpbin", "/EXPORTS", str(dll_path)],
        ["link", "/dump", "/exports", str(dll_path)],
    ]
    for cmd in candidates:
        code, out, err = run_cmd(cmd)
        if code == 0 and out:
            return True, out, " ".join(cmd)
        if code == 0 and err:
            return True, err, " ".join(cmd)
    # fallback: pefile (纯 Python，不需要编译工具)
    try:
        import pefile

        pe = pefile.PE(str(dll_path))
        lines = []
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if exp.name:
                ordinal = exp.ordinal
                rva = exp.address
                lines.append(f"    {ordinal:4}    {rva:8X}  {exp.name.decode()}")
        pe.close()
        if lines:
            header = f"ordinal  RVA      name\n{'=' * 30}"
            text = f"{header}\n" + "\n".join(lines)
            return True, text, "pefile (fallback)"
    except ImportError:
        pass
    except Exception:
        pass
    return False, "", ""


def parse_exports(text: str) -> List[str]:
    exports: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        # dumpbin 典型: ordinal hint RVA name
        # pefile fallback: ordinal RVA name
        m = re.match(r"^(\d+)\s+(?:[0-9A-Fa-f]+\s+)?([0-9A-Fa-f]+)\s+(.+)$", s)
        if m:
            name = m.group(3).strip()
            if name and name != "[NONAME]":
                exports.add(name)
    return sorted(exports)


def classify_exports(exports: List[str]) -> Dict:
    c_exports = [x for x in exports if not x.startswith("?")]
    cpp_exports = [x for x in exports if x.startswith("?")]
    return {
        "total": len(exports),
        "c_exports_count": len(c_exports),
        "cpp_exports_count": len(cpp_exports),
        "hints": {
            "Devices_get_like": [x for x in exports if re.search(r"Devices.*get", x, re.IGNORECASE)],
            "getDevList_like": [x for x in exports if re.search(r"getDevList", x, re.IGNORECASE)],
            "videoFormatInfo_like": [x for x in exports if re.search(r"videoFormatInfo", x, re.IGNORECASE)],
        },
    }


def load_dll(win_release_dir: Path, dll_path: Path):
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(win_release_dir))
    return ctypes.WinDLL(str(dll_path))


def try_c_entry_chain(dll, exports: List[str]) -> Tuple[str, List[str]]:
    diagnostics: List[str] = []
    lower_map = {name.lower(): name for name in exports}

    get_candidates = [
        lower_map.get("devices_get"),
        lower_map.get("obsbot_devices_get"),
        lower_map.get("devs_get"),
    ]
    get_candidates = [x for x in get_candidates if x]

    if not get_candidates:
        diagnostics.append("未发现可直接识别的 C 入口：devices_get/obsbot_devices_get/devs_get")
        return "fail", diagnostics

    get_name = get_candidates[0]
    try:
        fn_get = getattr(dll, get_name)
        fn_get.argtypes = []
        fn_get.restype = ctypes.c_void_p
        manager_ptr = fn_get()
        if not manager_ptr:
            diagnostics.append(f"{get_name} 调用返回空指针")
            return "fail", diagnostics
        diagnostics.append(f"{get_name} 调用成功，manager_ptr=0x{manager_ptr:x}")
    except Exception as ex:  # pylint: disable=broad-except
        diagnostics.append(f"{get_name} 调用异常: {ex!r}")
        return "fail", diagnostics

    list_name = lower_map.get("devices_getdevlist") or lower_map.get("obsbot_devices_getdevlist")
    if not list_name:
        diagnostics.append("未发现可直接识别的 C 入口：devices_getdevlist/obsbot_devices_getdevlist")
        return "fail", diagnostics

    diagnostics.append(f"发现 {list_name}（但 STL 返回值无法跨 ctypes 安全解析，需 C wrapper 桥接）")

    fmt_name = lower_map.get("device_videoformatinfo") or lower_map.get("obsbot_device_videoformatinfo")
    if fmt_name:
        diagnostics.append(f"发现潜在格式接口: {fmt_name}")

    return "needs_wrapper", diagnostics


def build_next_actions(last_step: str) -> List[str]:
    if last_step == "load_fail":
        return [
            "确认 Python 与 libdev.dll 同为 64 位",
            "确认 w32-pthreads.dll 在同目录并被加载",
            "使用 Dependencies 检查缺失运行时依赖",
        ]
    if last_step == "no_exports":
        return [
            "安装 Visual Studio Build Tools（含 dumpbin/link）或改用 llvm-objdump 导出符号",
            "若无法导出符号，优先运行 SDK 自带 OBSBOT_Sample.exe 验证 SDK 环境",
        ]
    return [
        "优先方案：写一个 C wrapper DLL（extern \"C\"）桥接 Devices/Device C++ API",
        "wrapper 返回纯 C 结构体数组（设备列表 + videoFormatInfo 列表）供 ctypes 调用",
        "如厂商可提供 C API 版本 SDK，优先替换",
    ]


def main() -> None:
    report: Dict = {
        "platform": platform.platform(),
        "python_arch": platform.architecture()[0],
        "steps": [],
        "summary": "",
        "next_actions": [],
    }

    steps: List[StepResult] = []
    base, win_release, dll, pthread, include = sdk_paths()

    files_ok = all(p.exists() for p in [base, win_release, dll, pthread, include])
    steps.append(StepResult("检查 SDK 文件结构", files_ok, f"sdk_base={base}"))
    if not files_ok:
        report["steps"] = [asdict(s) for s in steps]
        report["summary"] = "失败：SDK 路径或文件缺失"
        report["next_actions"] = ["确认 camera/sdk/libdev_v2.1.0_8 目录完整解压"]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    try:
        dll_handle = load_dll(win_release, dll)
        steps.append(StepResult("ctypes 加载 libdev.dll", True, "加载成功"))
    except Exception as ex:  # pylint: disable=broad-except
        steps.append(StepResult("ctypes 加载 libdev.dll", False, repr(ex)))
        report["steps"] = [asdict(s) for s in steps]
        report["summary"] = "失败：DLL 无法加载"
        report["next_actions"] = build_next_actions("load_fail")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    dump_ok, dump_text, dump_cmd = get_exports_with_tools(dll)
    if not dump_ok:
        steps.append(StepResult("导出表扫描", False, "未找到可用的 dumpbin/link 或导出失败"))
        report["steps"] = [asdict(s) for s in steps]
        report["summary"] = "失败：无法获取 DLL 导出表"
        report["next_actions"] = build_next_actions("no_exports")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    exports = parse_exports(dump_text)
    steps.append(StepResult("导出表扫描", True, f"命令={dump_cmd}, 导出数量={len(exports)}"))

    call_status, call_diag = try_c_entry_chain(dll_handle, exports)
    call_ok = call_status in ("ok", "needs_wrapper")
    steps.append(
        StepResult(
            "调用链尝试(Devices::get -> getDevList -> videoFormatInfo)",
            call_ok,
            " | ".join(call_diag),
        )
    )

    report["steps"] = [asdict(s) for s in steps]
    report["exports"] = classify_exports(exports)

    if call_status == "ok":
        report["summary"] = "成功：已获取设备列表和 videoFormatInfo（可进入阶段 2）"
        report["next_actions"] = ["进入 obsbot_sdk_api.py 封装"]
    elif call_status == "needs_wrapper":
        report["summary"] = "条件成功：已确认关键 C 入口符号存在，但 getDevList/videoFormatInfo 需 C wrapper 桥接。"
        report["next_actions"] = build_next_actions("chain_fail")
    else:
        report["summary"] = (
            "未打通：当前无法稳定调用 getDevList/videoFormatInfo。"
            "结论可直接执行：需要 C wrapper 或厂商提供 C API。"
        )
        report["next_actions"] = build_next_actions("chain_fail")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
