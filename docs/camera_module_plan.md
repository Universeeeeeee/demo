# Camera Module Plan: Meet SE 1080p@100fps + UI

## 前置结论

**SDK 是控制类 SDK，没有任何帧回调接口**（搜索了 `onFrame`/`frameCallback`/`getFrame`/`grabFrame`/`videoCallback` 等，全部零匹配）。视频帧只能通过标准 UVC 管道获取（即 OpenCV）。因此架构必然为：

```
OBSBOT Meet SE
    │
    ├── UVC 视频流 ──→ OpenCV (预览 + 本地录制)
    │
    └── libdev.dll ──→ ctypes 封装层 (设备查询 + 参数配置)
```

SDK 的价值在于：查询设备能力 (`videoFormatInfo()`)、配置输出格式、控制机内录制。**预览和 PC 端录制不依赖 SDK。**

## 阶段 1：勘查 — 确认 1080p@100fps 是否可达

这是最关键的一步，在写 UI 之前必须完成。

### 1.1 纯 OpenCV 勘查
用 `cv2.VideoCapture` 打开 Meet SE，遍历所有 DirectShow 格式，打印支持的 1080p 分辨率及对应帧率。代码如下：

```python
import cv2

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Windows 必须用 CAP_DSHOW
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap.set(cv2.CAP_PROP_FPS, 100)
# 读出的实际值：
w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)    # 期望 1920
h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)   # 期望 1080
fps = cap.get(cv2.CAP_PROP_FPS)          # 期望 100
print(f"Actual: {w}x{h} @ {fps}fps")

# 也遍历所有格式（使用 cv2.CAP_PROP_FOURCC + 不同 FourCC）
# 重点测 MJPEG (cv2.VideoWriter_fourcc('M','J','P','G'))
# 因为 1080p@100fps 未压缩 YUY2 带宽约 3.2Gbps，逼近 USB 3.0 上限，
# MJPEG 压缩后才可能在 UVC 上稳定传输
```

**这一阶段不要改任何现有代码，独立脚本即可。**

### 1.2 SDK 勘查（ctypes）
加载 `camera/sdk/libdev_v2.1.0_8/windows/win64-release/libdev.dll`，调用：
- `Devices::get().getDevList()` — 确认找到 Meet SE
- `Device::videoFormatInfo()` — 拿到设备真正支持的分辨率/帧率/编码格式列表
- `Device::devMode()` — 确认当前是 UVC 模式
- `Device::usb_status` / USB 模式 — 确认 100fps 是否需要特定模式

ctypes 封装只做最薄的 C 函数桥接，**不引入额外抽象层**。能避开 C++ 对象直接调 C 导出函数的优先（`dev_get_log_handler` 这类全局函数可以直接调），C++ 成员函数需要手动构造对象指针。

```python
import ctypes

dll = ctypes.CDLL("camera/sdk/libdev_v2.1.0_8/windows/win64-release/libdev.dll")
# 按需逐步封装：先 dev_get_log_handler → 再 Devices::get() → 再 getDevList()
```

### 1.3 结论路由

| 勘查结果 | 后续方案 |
|---------|---------|
| A. UVC 直接支持 1080p@100fps | 纯 OpenCV 方案，SDK 可选（仅用于设备查询） |
| B. 需要 SDK 切换 USB 模式后才能达到 | OpenCV + SDK 配置 + 重新枚举设备 |
| C. 100fps 仅在 MTP 模式下提供，UVC 下不可用 | 无法实现实时预览 100fps，退而求其次 |

**阶段 1 输出**：一份简短报告（支持的格式列表 + 实际可达的最高参数），阶段 2 根据这份报告决定走哪条路径。

## 阶段 2：实现 `camera/` 模块

基于阶段 1 结论实现。目录结构：

```
camera/
    obsbot_sdk.py      # ctypes 封装层（仅 SDK 需要的函数）
                        # - load_dll()
                        # - get_devices()
                        # - get_video_formats(dev)
                        # - set_usb_mode(dev, mode)  [按需]
                        # - get_camera_status(dev)
    obsbot_control.py   # 高层控制接口
                        # - discover()
                        # - get_device_info()
                        # - configure_format(res, fps)
                        # - start_record / stop_record  [机内录制]

ui/
    camera.py           # 改造现有文件，增加：
                        # - 设备选择下拉框
                        # - 分辨率/帧率控制（从 videoFormatInfo 列表选择）
                        # - 录制按钮（OpenCV VideoWriter，PC 本地录制）
                        # - 相机参数面板（可选，后期加）
```

### 2.1 `camera/obsbot_sdk.py` — ctypes 封装

核心原则：
- 只封装本项目实际用到的函数，不追求全面
- 每个函数封装时处理参数转换、错误码、返回类型
- 日志回调 `dev_set_log_handler` 优先封装，方便排查 DLL 调用问题
- C++ 类成员函数需用 C 风格 wrapper 或直接通过虚函数表调用（由阶段 1 勘查决定）

### 2.2 `ui/camera.py` — 改造

在现有基础上增加：

```
┌────────────────────────────────────────────┐
│  Camera                              [×]   │
├────────────────────────────────────────────┤
│                                            │
│   设备: [OBSBOT Meet SE (SN:xxx) ▼]       │  ← 新增：SDK 设备发现
│   分辨率: [1920×1080 ▼]  帧率: [100 ▼]    │  ← 新增：格式控制
│                                            │
│   ┌────────────────────────────────┐       │
│   │                                │       │  ← OpenCV 预览窗口（嵌入 Qt）
│   │        Live Preview            │       │
│   │                                │       │
│   └────────────────────────────────┘       │
│                                            │
│   [Start Preview]  [⏺ Record]  [⏹ Stop]  │  ← 预览 + 录制按钮
│                                            │
│   FPS: 99.7  录制时间: 00:01:23           │  ← 状态栏
│                                            │
└────────────────────────────────────────────┘
```

关键实现点：
1. **预览**：现有 `Camera._camera_loop` 逻辑保留，帧显示到嵌入的 QLabel/QWidget 而非独立 OpenCV 窗口
2. **录制**：`cv2.VideoWriter` + MJPEG fourcc 写入本地文件，在帧循环中写入
3. **分辨率/帧率切换**：停预览 → 设置参数 → 重开预览（OpenCV 不支持热切换）
4. **设备选择**：优先 SDK 精确识别（按 SN 匹配 `videoFriendlyName`），fallback 用摄像头索引

## 关键风险

1. **1080p@100fps 可能在 UVC 下不可达**。SDK 的 `kEvtInfoHDRWith100Fps` 事件暗示 100fps 可能与 HDR 模式绑定，而 HDR 模式下 UVC 协商的格式可能不同。**阶段 1 必须优先验证这一点。**

2. **SDK 是 C++ DLL，ctypes 只能调用 C 导出函数**。如果 SDK 只导出了 C++ 修饰名（mangled names），需要用 `dumpbin /EXPORTS` 或 Dependency Walker 获取真实导出符号。C++ 类成员函数在 ctypes 中调用比较棘手，可能需要写一个极薄的 C wrapper DLL。

3. **OpenCV + Windows DirectShow**：`cv2.CAP_DSHOW` 对高帧率 MJPEG 的支持取决于 DirectShow 滤镜链。如果 Meet SE 的 UVC 描述符没有正确暴露 100fps MJPEG，OpenCV 可能无法协商到该格式。

## 实施顺序

```
Step 1: 勘查脚本（1.1 + 1.2）→ 报告结论
Step 2: 根据结论决定是否用 SDK，实现 camera/obsbot_sdk.py
Step 3: 改造 ui/camera.py 为完整控制面板（设备选择 + 格式控制 + 录制）
Step 4: 实测 1080p@100fps 录制效果，调整编码参数
```
