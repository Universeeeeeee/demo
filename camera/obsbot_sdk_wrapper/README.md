# OBSBOT C API wrapper — 当前状态

## 目标

用 C wrapper DLL 桥接 OBSBOT C++ SDK，使 Python ctypes 可调用设备控制 API。
核心原理：STL 类型（`std::string`/`std::vector`/`std::shared_ptr`）留在 C++ 侧，
对外暴露纯 C 结构体和函数。

## 编译环境

已安装并验证可用：

| 工具 | 路径 |
|------|------|
| cmake 4.3.2 | `C:\Program Files\CMake\bin\cmake.exe` |
| MSVC 19.44 | `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe` |
| Windows SDK | 10.0.26100.0 |

激活环境：
```cmd
"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
```

编译命令：
```powershell
cmake -S camera\obsbot_sdk_wrapper -B camera\obsbot_sdk_wrapper\build -G "Visual Studio 17 2022" -A x64
cmake --build camera\obsbot_sdk_wrapper\build --config Release
```

运行产物输出到：`camera\bin\obsbot_c_api.dll`（含 `libdev.dll` + `w32-pthreads.dll`）

## 代码结构

```
obsbot_sdk_wrapper/
├── obsbot_c_api.h       # C 头文件：结构体 + 函数声明
├── obsbot_c_api.cpp     # 实现：g_devices 缓存 + C↔C++ 桥接
├── CMakeLists.txt       # 构建配置
└── README.md            # 你正在看的这个文件
```

## 关键实现细节（已踩坑修复）

### obsbot_refresh_devices 时序

**修复前**：先 sleep，再调 `Devices::get()`。但 `Devices::get()` 才触发设备检测线程，导致 sleep 期间什么都没发生。

**修复后**（`obsbot_c_api.cpp:48-61`）：
```cpp
Devices::get();  // 先触发检测线程
sleep(wait_ms);  // 等待线程完成
auto list = Devices::get().getDevList();  // 获取结果
```

### 其他函数

- `obsbot_get_device_info(index)` — 用 `g_devices[index]` 缓存，按索引取设备信息
- `obsbot_get_video_formats(index)` — 填 C 数组，返回总数
- `obsbot_set_record_encode_param(index)` — 直接透传 `DevMediaEncodeParam`
- `obsbot_get_record_encode_param(index)` — 读回参数（Tiny SE 上此函数返回 -1，可能不支持）

## Python 测试脚本

测试脚本：`camera/test_wrapper.py`

工作方式：
1. `obsbot_refresh_devices(5000)` — 5 秒等检测
2. `obsbot_get_device_info(0)` — 获取 SN/名称/固件版本/产品类型
3. `obsbot_get_video_formats(0)` — 列出设备支持的格式
4. `obsbot_set_record_encode_param(0, fps=100)` — 尝试设置 100fps

## Tiny SE 实测结果（2026-04-30）

### 设备信息

| 项 | 值 |
|----|-----|
| SN | RMOWCYHA081RCB |
| Name | OBSBOT_RMOWCYHA081RCB |
| Version | 6.4.3.4 |
| ProductType | 12 (TinySE) |
| DevMode | 0 (UVC) |
| VideoFriendlyName | OBSBOT Tiny SE StreamCamera |

### videoFormatInfo（共 4 个格式）

| 分辨率 | 帧率范围 | 编码 |
|--------|---------|------|
| **1920×1080** | **[15, 100]** | **MJPEG** |
| 1280×720 | [15, 120] | MJPEG |
| 640×360 | [15, 30] | YUY2 |
| 640×480 | [15, 30] | YUY2 |

**关键结论：Tiny SE 硬件支持 1080p@100fps MJPEG。**

### set_record_encode_param(fps=100)

- 返回 `0` (OK) — **SDK 接受了 100fps 参数**
- 但 `get_record_encode_param` 返回 `-1` (ERR) — Tiny SE 可能不支持此 getter，或参数未实际写入

## 未完成：验证 UVC 实际输出

SDK 设完 fps 后，需要验证 UVC 端实际输出是否变为 1080p@100fps。

已知障碍：
- OpenCV DSHOW 后端：设 FOURCC 会卡死 Tiny SE 驱动
- OpenCV MSMF 后端：Tiny SE 打不开
- OpenCV DSHOW 默认模式：640×480 @ 1fps（极不稳定）

**建议尝试路径**：
1. SDK 设完 fps=100 后 → OpenCV DSHOW 打开，**不设 FOURCC/宽高/帧率**，只 `cap.read()` 测实测帧率和分辨率
2. 如果 DSHOW 仍崩 → 试 `cv2.CAP_ANY` 或 DSHOW 的 `cv2.CAP_PROP_MODE_RAW` 
3. 如果 OpenCV 完全不可用 → 考虑用 Windows Media Foundation API 直接拉流

## 环境

- Python: `D:/conda/envs/dayu/python.exe` (64-bit)
- OpenCV: 已安装，DSHOW/MSMF 后端均可用
- ctypes: 标准库
- SDK DLL: `camera/sdk/libdev_v2.1.0_8/windows/win64-release/libdev.dll`
