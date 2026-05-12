# Tiny SE 摄像头控制功能实现计划

## 目标

将 SDK 中的图像控制 + AI 追踪功能封装为 Python 可用接口，集成到 `tinyse_camera.py`。

## 架构

```
obsbot_c_api.dll (C++)
    ├── 已有: obsbot_refresh_devices / get_device_info / get_video_formats
    ├── 已有: obsbot_set_record_encode_param / get_record_encode_param
    ├── 已有: obsbot_get_camera_status / get_usb_mode / set_usb_mode
    │
    └── 新增 8 个 C ABI:
        obsbot_set_mirror          (index, 0/1)
        obsbot_set_ai_mode         (index, mode, sub_mode)   ← 下半身追踪入口
        obsbot_set_auto_focus      (index, 0/1)
        obsbot_set_manual_focus    (index, 0-100)
        obsbot_set_exposure_comp   (index, discrete_val)
        obsbot_set_anti_flicker    (index, freq)
        obsbot_set_fov             (index, fov_type)
        obsbot_set_wdr             (index, wdr_mode)
            │
            │ ctypes
            ▼
camera/tinyse_camera.py
    ├── TinySeCameraCapture  (已有)  采集 + 录制 + 预览
    ├── TinySeCameraControl  (新增)  SDK 参数控制层
    └── TinySeCameraWidget   (修改)  添加控制面板
```

## 1. C wrapper 新增接口 (`obsbot_c_api.h`)

```c
// 镜像: 0=正常, 1=水平镜像
int32_t obsbot_set_camera_mirror(int32_t index, int32_t mirror);

// AI 模式: mode=AiWorkModeType, sub_mode=AiSubModeType
// 下半身追踪: mode=1(AiWorkModeHuman), sub_mode=5(AiSubModeLowerBody)
int32_t obsbot_set_ai_mode(int32_t index, int32_t mode, int32_t sub_mode);

// 对焦: auto=1 自动, auto=0 手动 (配合 set_manual_focus)
int32_t obsbot_set_auto_focus(int32_t index, int32_t auto_mode);
int32_t obsbot_set_manual_focus(int32_t index, int32_t focus_val);

// 曝光补偿: 离散白名单 0-18
int32_t obsbot_set_exposure_compensation(int32_t index, int32_t ev_index);

// 抗频闪: 0=60Hz, 1=50Hz
int32_t obsbot_set_anti_flicker(int32_t index, int32_t freq);

// 视野: 0=86°, 1=78°, 2=65°
int32_t obsbot_set_fov(int32_t index, int32_t fov_type);

// WDR/HDR: 0=Off, 1=DOL2to1, 2=Sensor
int32_t obsbot_set_wdr(int32_t index, int32_t wdr_mode);
```

每个函数内部结构一致：
```cpp
auto dev = get_device(index);
if (!dev) return OBSBOT_ERR_NO_DEVICE;
return dev->cameraSetXxxR(xxx);
```

## 2. Python 控制层 (`TinySeCameraControl`)

新增类，位于 `tinyse_camera.py`，与 `TinySeCameraCapture` 并列：

```python
class TinySeCameraControl:
    """Tiny SE SDK 参数控制（镜像/追踪/对焦/曝光/白平衡/FOV/HDR）"""
    
    def __init__(self, dll_path, device_index=0):
        # 加载 DLL，绑定所有控制函数签名
    
    # ── 镜像 ──
    def set_mirror(self, on: bool):
        """硬件镜像，替代 cv2.flip"""
    
    # ── AI 追踪 ──
    def set_ai_lower_body_tracking(self):
        """激活下半身追踪: AiWorkModeHuman + AiSubModeLowerBody"""
    
    def set_ai_off(self):
        """关闭 AI 追踪"""
    
    # ── 对焦 ──
    def set_auto_focus(self, on: bool):
    def set_manual_focus(self, value: int):
        """value: 0~100"""
    
    # ── 曝光 ──
    def set_exposure_compensation(self, ev_index: int):
        """离散白名单枚举"""
    
    # ── 其他 ──
    def set_anti_flicker(self, freq: int):  # 0=60Hz, 1=50Hz
    def set_fov(self, fov: int):            # 0=86°, 1=78°, 2=65°
    def set_wdr(self, on: bool):
    def close(self):
```

**关键设计约束**：
- `TinySeCameraControl` 独立于 `TinySeCameraCapture`——采集链不依赖控制层
- 控制命令非阻塞，不等待 SDK 回复（fire-and-forget）
- 在 `TinySeCameraWidget` 的 `_on_start` 中同时初始化 control 对象
- `_on_stop` 中调用 `control.close()`

## 3. UI 集成

`TinySeCameraWidget` 增加一个折叠控制面板（`MSectionItem`）：

```
┌─ 摄像头控制 ──────────────────────────────────┐
│  镜像: [✓]          FOV: [86° ▼]              │
│  AI 追踪: [▼ 下半身]   [激活]                  │
│  对焦: [● 自动] [○ 手动: 50 ▬]               │
│  曝光补偿: [0 ▼]     抗频闪: [50Hz ▼]         │
│  HDR: [  ]                                    │
└────────────────────────────────────────────────┘
```

按钮/滑块与 `TinySeCameraControl` 方法绑定。

## 4. 文件改动清单

| 文件 | 改动 | 行数(估) |
|------|------|---------|
| `obsbot_sdk_wrapper/obsbot_c_api.h` | 新增 8 个函数声明 | +30 |
| `obsbot_sdk_wrapper/obsbot_c_api.cpp` | 新增 8 个函数实现 | +80 |
| `camera/tinyse_camera.py` | 新增 `TinySeCameraControl` 类 | +90 |
| `camera/tinyse_camera.py` | `TinySeCameraWidget` 增加控制面板 | +50 |

编译：
```powershell
cmake --build camera\obsbot_sdk_wrapper\build --config Release
```

## 5. 验证

1. 编译通过
2. `python camera/tinyse_camera.py` → 弹出窗口 → 预览正常
3. 点击"镜像" → 画面镜像（硬件翻转）
4. 点击"下半身追踪" → 摄像头云台跟随走路动作
5. 手动对焦滑块拖动 → 画面清晰度变化
6. 录制同时操作控制面板 → 不丢帧、不崩溃
