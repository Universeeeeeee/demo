# Camera Module 实施计划：OBSBOT Meet SE 1080p@100fps

## 背景

在光电阵列步态分析系统中集成 OBSBOT Meet SE 摄像头控制。需要：
1. 实时预览（1080p@100fps）
2. PC 本地录制（不依赖机内录制）
3. 分辨率/帧率控制
4. 独立界面窗口，完成后集成到主 ui

## 核心发现

OBSBOT SDK (`libdev.dll`) 是纯控制类 SDK，**没有任何帧回调接口**。视频帧只能通过标准 UVC 管道（OpenCV）获取。

Meet SE 规格中提及 1080p@100fps，但 UVC 是否能直接输出此参数**未知**。

## 阶段 1：勘查—确认可行性

独立脚本，不改任何现有代码。

### 1.1 OpenCV 直接勘查
```python
# camera/explore_opencv.py
```
- 创建 `camera/explore_opencv.py`，逐项尝试：
  - 枚举可用摄像头索引(`0,1,2...`)
  - 尝试 `cv2.CAP_DSHOW` 设置 `1920×1080` + `100fps`
  - 尝试不同 `FOURCC`：`MJPG` / `YUY2` / `I420`
  - 打印实际生效的 `width` / `height` / `fps`
- 输出：`cap.get()` 读出的实际宽高帧率

### 1.2 SDK ctypes 勘查
```python
# camera/explore_sdk.py
```
- 用 `ctypes.CDLL` 加载 `libdev.dll`
- 从 DLL 导出表中定位关键函数（先用 `dumpbin /EXPORTS` 看导出符号）
- 尝试获取 `Devices::get()` 单例指针
- 调用 `getDevList()` → `videoFormatInfo()` 获取设备支持格式列表
- 输出：设备详情 + 所有 `(width, height, fps_min, fps_max, format_)` 条目

### 1.3 结论路由

| 勘查结果 | 后续动作 |
|---------|---------|
| UVC 直接支持 1080p@100fps | **继续阶段 2** |
| UVC **不支持** 1080p@100fps（无论更低帧率是否可行） | **放弃整个方案**，告知用户原因 |

**告知内容如果放弃**：说明 OpenCV/UVC 下 Meet SE 实际无法输出 1080p@100fps（列出实测到的最高参数），SDK 不提供帧数据管道，建议联系厂商确认 OBSBOT Meet SE 的 UVC 规格或改用支持 USB 3.0 UVC 高帧率输出的硬件。

---

## 阶段 2：实现独立摄像头控制模块

全部在 `camera/` 目录下完成，不修改 `ui/` 下任何文件。

### 目录结构（最终）

```
camera/
    camera_module_plan.md       # 本文件
    explore_opencv.py           # 阶段 1
    explore_sdk.py              # 阶段 1
    obsbot_sdk_api.py           # SDK ctypes 封装层
    obsbot_controller.py        # 控制器层（OpenCV + SDK 编排）
    ui_camera_window.py         # 独立 PySide6 窗口（阶段 2 产出）
    requirements.txt            # 依赖
```

### 2.1 `obsbot_sdk_api.py` — SDK ctypes 封装层

**职责**：封装 `libdev.dll` 的纯 C++ 调用，对外暴露 Python 函数。

**架构**：采用惰性初始化 + 单例模式管理 DLL 生命周期

```python
class ObsbotSdk:
    """libdev.dll 的 Python 封装。进程内全局单例。"""
    
    @classmethod
    def instance(cls) -> "ObsbotSdk":
        """首次调用时加载 DLL，返回单例"""
    
    def discover_devices(self) -> list["ObsbotDevice"]:
        """调用 Devices::get().getDevList()，返回设备列表"""
    
    def get_device_by_sn(self, sn: str) -> "ObsbotDevice":
        """按 SN 查找设备"""
    
    def close(self):
        """调用 Devices::close() 释放资源"""


class ObsbotDevice:
    """单个 OBSBOT 设备的代理"""
    
    @property
    def sn(self) -> str
    
    @property
    def product_type(self) -> str
    
    @property
    def video_formats(self) -> list[VideoFormatInfo]:
        """调用 videoFormatInfo()"""
    
    def set_record_resolution(self, res_type: int):
        """调用 cameraSetRecordResolutionR()"""
    
    def set_video_record(self, operation: int):
        """operation: 0=stop, 1=start"""
```

**需要封装的函数清单**（逐步按需，不一次性全包）：

| 函数 | 用途 | 优先级 |
|------|------|--------|
| `Devices::get()` | 获取管理单例 | P0 |
| `Devices::setDevChangedCallback()` | 设备热插拔通知 | P1 |
| `Devices::getDevList()` | 获取设备列表 | P0 |
| `Device::devSn()` | 获取 SN | P0 |
| `Device::productType()` | 获取产品类型 | P0 |
| `Device::devMode()` | 获取模式(UVC/Net/MTP) | P1 |
| `Device::videoFormatInfo()` | 支持格式列表 | P0 |
| `Device::cameraSetRecordResolutionR()` | 设置录制分辨率 | P1 |
| `Device::cameraSetVideoRecordR()` | 启停机内录制 | P1 |
| `Device::cameraStatus()` | 读取状态(含当前分辨率) | P1 |
| `Device::setDevStatusCallbackFunc()` | 状态变更回调 | P2 |
| `Device::enableDevStatusCallback()` | 启用状态回调 | P2 |

**C++ 类成员函数的 ctypes 处理策略**：
- 优先查找 DLL 中的 `extern "C"` 导出函数（无 mangling）
- 如果只有 C++ 导出（mangled names），用 `ctypes.CFUNCTYPE` 定义虚函数表调用
- 实在不行才写 C wrapper helper DLL

### 2.2 `obsbot_controller.py` — 控制器层

**职责**：封装 OpenCV 摄像头操作 + SDK 设备配置，对外提供简洁的控制接口。

```python
class CameraController(QObject):
    """摄像头控制器。管理 OpenCV 设备的整个生命周期。"""
    
    # --- 信号 ---
    frame_received = Signal(np.ndarray)      # 新帧信号 → UI 渲染
    status_updated = Signal(dict)             # fps, 录制时长等统计
    
    # --- 设备管理 ---
    def list_cameras(self) -> list[CameraInfo]
    def open_device(self, camera_info: CameraInfo, format: VideoFormatInfo)
    def close_device(self)
    
    # --- 预览控制 ---
    def start_preview(self)
    def stop_preview(self)
    def restart_with_format(self, format: VideoFormatInfo)  # 热切换格式
    
    # --- 录制控制 ---
    def start_recording(self, output_path: str = None)
    def stop_recording(self) -> str  # 返回录制文件路径
    
    # --- 内部 ---
    def _capture_loop(self)        # 消费者线程，循环读取 + 信号发射
    def _update_fps_stats(self)    # 实时帧率统计
    
    
class VideoFormatInfo(NamedTuple):
    width: int
    height: int
    fps: int
    fourcc: str           # 如 "MJPG"
    is_uvc: bool          # UVC 原生支持还是需要 SDK 换模
```

**线程模型**：
```
主线程 (Qt GUI)
    ↑ frame_received 信号
    ↓ 控制调用 (open/start/stop)

Capture 线程 (while running 循环)
    cap.read() → 发射信号 → cv2.imwrite() 到 VideoWriter
```

**录制实现**：
```python
# 用 OpenCV VideoWriter，用帧率统计信息作为编码帧率参考
fourcc = cv2.VideoWriter_fourcc(*'MJPG')
writer = cv2.VideoWriter(filepath, fourcc, actual_fps, (w, h))
# 注意：100fps 写入 MJPEG 需要注意磁盘 IO 是否跟得上
```

### 2.3 `ui_camera_window.py` — 独立 PySide6 窗口

**职责**：独立的摄像头控制窗口，通过 `CameraController` 驱动。

```python
class CameraWindow(QMainWindow):
    """
    独立摄像头控制窗口。
    可单独运行 (`if __name__ == "__main__"`)，
    也可作为 QWidget 嵌入主界面（留好接口）。
    """
    
    def __init__(self, parent=None):
        self.controller = CameraController()
        self._init_ui()
        self._connect_signals()
```

**界面布局**：

```
┌──────────────────────────────────────────────────────┐
│  OBSBOT Camera Control                        [×]    │
├──────────────────────────────────────────────────────┤
│  ┌─ 设备 ─────────────────────────────────────────┐  │
│  │  设备: [OBSBOT Meet SE (SN:xxx)        ▼]     │  │
│  │  状态: ● 已连接  模式: UVC                     │  │
│  └────────────────────────────────────────────────┘  │
│  ┌─ 视频格式 ──────────────────────────────────────┐  │
│  │  分辨率: [1920×1080          ▼]  帧率: [100 ▼]  │  │
│  │  格式: [MJPEG ▼]                                │  │
│  │  [应用格式]                                      │  │  ← 停预览 → 重开
│  └────────────────────────────────────────────────┘  │
│  ┌─ 预览 ──────────────────────────────────────────┐  │
│  │                                                  │  │
│  │            [live preview area]                   │  │  ← QLabel.setPixmap
│  │                                                  │  │
│  └────────────────────────────────────────────────┘  │
│  ┌─ 控制 ──────────────────────────────────────────┐  │
│  │  [▶ 开始预览]  [⏺ 开始录制]  [■ 停止]         │  │
│  │  实时帧率: 99.7 fps  录制: 00:01:23             │  │
│  │  分辨率: 1920×1080  丢帧: 0.3%                  │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

**信号连接**：
```python
# 从控制器到 UI
controller.frame_received.connect(self._on_frame)
controller.status_updated.connect(self._update_status)

# 从 UI 到控制器
# 按钮点击直接调用 controller 方法
```

**嵌入接口**：
```python
# 在其他界面显示时：
window = CameraWindow(parent=main_window)
window.show()

# 获取预览帧（如果需要给步态分析传递画面）：
controller.frame_received.connect(gait_analysis.process_frame)
```

---

## 实施顺序

```
Step 1: explore_opencv.py   独立运行，输出实际 UVC 能力
Step 2: explore_sdk.py      独立运行，输出 SDK 发现的格式列表
Step 3: (如 1.3 结论为可行)
         → obsbot_sdk_api.py    SDK ctypes 封装
         → obsbot_controller.py OpenCV+SDK 编排层
         → ui_camera_window.py  独立窗口
Step 4: 集成（后续任务）：嵌入到主 ui，与 gait 等模块联动
```

## 验证方式

1. `explore_opencv.py` → 打印实际生效的宽/高/fps
2. `explore_sdk.py` → 打印设备 SN + 支持格式列表
3. `python camera/ui_camera_window.py` → 弹出独立窗口
   - 显示实时预览画面
   - 录制按钮生成可正常播放的 `.avi` 文件
   - 切换格式后预览立即生效
4. 停止预览后资源完全释放（`cap.release()` + 线程结束）
