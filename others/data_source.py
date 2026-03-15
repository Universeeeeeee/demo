"""
使用说明（目标与思路）
---------------------------------
本脚本用于：从 USB 设备在线录制“一段典型步态原始数据”，并保存到本地文件，
方便后续在无设备环境下离线复现/调试（软硬件解耦）。

实现要点：
- 通过环境变量配置设备参数（VID/PID/超时/块大小/录制时长/保存文件）。
- 参考 demo/receive.py 的 CyUsbInterface 设备封装，装载 DLL 并打开设备。
- 采用设备对象的自动读取线程 + 回调，持续收集原始字节流。
- 按“时长（如指定）或最大字节数”停止，默认需手动 Ctrl+C 结束；保存为 .npz：
  - raw: uint8 一维数组（拼接后的连续原始字节）   
  - meta: JSON 字符串，包含采集配置、起止时间、总字节数等元数据

注意：
- 本脚本不解析业务帧，仅记录“设备发出的原始字节流”。后续离线回放/解析可直接载入 raw。
- DLL 默认路径与 receive.py 保持一致，可通过 DAYU_DLL 覆盖。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from typing import List

import numpy as np

# 为了直接复用 receive.py 中的 CyUsbInterfaceDevice，这里做兼容导入
try:
    # 作为包运行（例如从项目根运行 python -m demo.data_source）
    from .receive import CyUsbInterfaceDevice  # type: ignore
except Exception:
    # 作为脚本运行（例如在项目根运行 python demo/data_source.py）
    from receive import CyUsbInterfaceDevice  # type: ignore


# ---------------------- 配置项与工具函数 ----------------------
def _parse_int(env_name: str, default: int) -> int:
    """从环境变量解析整数，支持 0x 前缀的十六进制表示。"""
    v = os.getenv(env_name)
    if not v:
        return default
    try:
        return int(v, 0)
    except Exception:
        return default


def _default_output_path() -> str:
    """根据时间生成一个默认输出文件名（npz）。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.getenv("DAYU_SAVE", f"gait_capture_{ts}.npz")


# ---------------------- 核心逻辑：录制函数 ----------------------
def record_gait_segment(
    *,
    dll_path: str,
    vid: int,
    pid: int,
    timeout_ms: int,
    chunk_size: int,
    duration_s: float,
    max_bytes: int,
    out_file: str,
) -> str:
    """
    录制一段原始数据字节流并保存。

    参数：
      - dll_path: CyUsbInterface.dll 路径
      - vid/pid: 设备识别
      - timeout_ms: 读取超时（同时影响自动读取线程）
      - chunk_size: 读取块大小（建议与固件端点尺寸匹配）
    - duration_s: 录制时长（<=0 表示不按时长限制，需 Ctrl+C 手动结束）
      - max_bytes: 最大录制字节数（<=0 表示不设字节上限）
      - out_file: 输出 .npz 路径

    返回：实际写入的文件路径。
    """

    # 1) 先尝试装载 DLL 并自检导出符号
    try:
        probe = ctypes.WinDLL(dll_path)
        getattr(probe, "InitDevice")
    except Exception as e:
        raise RuntimeError(f"无法装载 CyUsbInterface DLL: {dll_path}. 错误: {e}")

    # 2) 打开设备
    dev = CyUsbInterfaceDevice(dll_path)
    if not dev.open(vid, pid):
        raise RuntimeError("打开设备失败。请检查连接、VID/PID、驱动安装以及 Python 与 DLL 位数匹配。")

    # 3) 设备体检与初始化（尽量容错，不作为硬错误）
    try:
        dev.dll.set_timeout(timeout_ms)
    except Exception:
        pass
    try:
        # 可选：复位设备，具体是否需要视固件实现
        dev.dll.reset_device()
    except Exception:
        pass
    try:
        # 可选：给固件发启动命令帧（若固件忽略也无妨）
        dev.dll.send_command_frame(0x01)
        dev.dll.send_command_frame(0x02)
    except Exception:
        pass

    # 4) 采集准备：注册“原始字节回调”，由自动读取线程驱动
    chunks: List[bytes] = []
    total = 0
    last_print = time.time()
    start_ts = time.time()
    stop_by_time = duration_s and duration_s > 0
    stop_by_size = max_bytes and max_bytes > 0

    def _on_bytes(data: bytes):
        nonlocal total, last_print
        if not data:
            return
        chunks.append(data)
        total += len(data)
        # 控制台轻量进度：每 1s 打印一次累计字节
        now = time.time()
        if now - last_print >= 1.0:
            print(f"已接收 {total} 字节…")
            last_print = now

    dev.set_on_bytes(_on_bytes)

    # 启动设备采集（如果固件不需要也会容错）
    try:
        dev.start_capture()
    except Exception:
        pass

    # 启动自动读取线程
    ret = dev.start_auto_read(chunk_size)
    if ret != 0:
        try:
            dev.close()
        except Exception:
            pass
        raise RuntimeError(f"启动自动读取失败，返回码: {ret}")

    print("开始录制… 按 Ctrl+C 可提前停止。")
    try:
        while True:
            # 时间停止条件
            if stop_by_time and (time.time() - start_ts) >= duration_s:
                print("录制到达设定时长，准备停止…")
                break
            # 大小停止条件
            if stop_by_size and total >= max_bytes:
                print("录制到达设定字节上限，准备停止…")
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("收到中断，准备停止…")
    finally:
        # 退出处理：停止线程/采集，并解除回调
        try:
            dev.set_on_bytes(None)
        except Exception:
            pass
        try:
            dev.stop_auto_read()
        except Exception:
            pass
        try:
            dev.stop_capture()
        except Exception:
            pass
        try:
            dev.close()
        except Exception:
            pass

    end_ts = time.time()

    # 5) 合并并保存
    raw = b"".join(chunks) if chunks else b""
    arr = np.frombuffer(raw, dtype=np.uint8)
    meta = {
        "dll": dll_path,
        "vid": f"0x{vid:04X}",
        "pid": f"0x{pid:04X}",
        "timeout_ms": int(timeout_ms),
        "chunk_size": int(chunk_size),
        "start_ts": float(start_ts),
        "end_ts": float(end_ts),
        "duration_s": float(end_ts - start_ts),
        "bytes_total": int(len(arr)),
        "host": {
            "platform": sys.platform,
            "python": sys.version.split(" ")[0],
        },
    }

    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    np.savez(out_file, raw=arr, meta=json.dumps(meta, ensure_ascii=False))
    print(f"已保存：{out_file}（{len(arr)} 字节）")
    return out_file


# ---------------------- 脚本入口 ----------------------
def main():
    # 解析可选的命令行参数（全部有环境变量和默认兜底，可完全省略）
    parser = argparse.ArgumentParser(description="录制一段步态原始数据到 .npz，用于离线复现")
    parser.add_argument("--seconds", type=float, default=None, help="录制秒数（优先于 DAYU_DURATION，<=0 表示不用时长限制）")
    parser.add_argument("--max-bytes", type=int, default=None, help="最大录制字节数（<=0 表示不限）")
    parser.add_argument("--outfile", type=str, default=None, help="输出文件路径（默认 gait_capture_YYYYmmdd_HHMMSS.npz）")
    args = parser.parse_args()

    DLL_PATH = os.getenv(
        "DAYU_DLL",
        r"E:\OptoJump\dayu_demo\Newtongxin\CyUsbInterface\output\CyUsbInterface.dll",
    )
    VID = _parse_int("DAYU_VID", 0x04B4)
    PID = _parse_int("DAYU_PID", 0x1004)
    READ_TIMEOUT_MS = _parse_int("DAYU_TIMEOUT", 200)
    CHUNK_SIZE = _parse_int("DAYU_CHUNK", 2048)

    # 时长优先级：仅命令行；未指定则不限制，需 Ctrl+C 手动结束
    duration_s = float(args.seconds) if args.seconds is not None else 0.0

    # 最大字节数：命令行 > 环境变量 > 默认不限
    env_max = os.getenv("DAYU_MAX_BYTES")
    max_bytes = int(args.max_bytes) if args.max_bytes is not None else (_parse_int("DAYU_MAX_BYTES", 0) if env_max else 0)

    out_file = args.outfile or _default_output_path()

    print(f"Loaded DLL: {DLL_PATH} (flavor: CyUsbInterface)")
    duration_text = f"{duration_s}s" if duration_s > 0 else "manual"
    print(
        f"Config: VID=0x{VID:04X} PID=0x{PID:04X} TIMEOUT={READ_TIMEOUT_MS}ms CHUNK={CHUNK_SIZE} DURATION={duration_text} MAX_BYTES={max_bytes or '∞'}"
    )

    try:
        saved = record_gait_segment(
            dll_path=DLL_PATH,
            vid=VID,
            pid=PID,
            timeout_ms=READ_TIMEOUT_MS,
            chunk_size=CHUNK_SIZE,
            duration_s=duration_s,
            max_bytes=max_bytes,
            out_file=out_file,
        )
        print("完成。")
        return 0
    except Exception as e:
        print("录制失败：", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

