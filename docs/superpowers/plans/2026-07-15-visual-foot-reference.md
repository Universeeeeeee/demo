# Visual Foot Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个可独立调用的视觉左右脚参考模块，为带绝对单调时间戳的触地事件输出 `left`、`right`、`both` 或 `unknown`，首版不改变原项目的光栅算法和报告链路。

**Architecture:** `vision/` 是独立包，内部包含纯数据契约、事件窗口调度器、事件级分类器、MediaPipe VIDEO 适配器和基于标准线程的独立 Service。调用方只需提交未镜像相机帧和触地事件，并订阅结果；原项目仅在两个相机采集类上增加兼容的带时间戳分析信号，不接入引擎、processor、主 UI 或报告。

**Tech Stack:** Python 3.11、PySide6 + qtpy、OpenCV、NumPy、MediaPipe Tasks Pose Landmarker Full、pytest/pytest-qt；目标运行环境为 Windows 10/11 x64 CPU，开发环境为 macOS。

## Global Constraints

- `vision/` 不 import `engine`、`ui`、`config`、`hardware` 或报告模块；相机模块也不 import `vision`。
- 不修改 `GaitEngine`、`TreadmillProcessor`、任何 accumulator、报告模型、主窗口或执行页。
- 服务公共边界只有 `start()`、`submit_frame()`、`submit_touch_event()`、`decision_ready`、`status_changed`、`stop()`；调用方不创建服务即等同关闭视觉。
- 不在相机 UI 回调、USB 回调或任何光栅处理链中执行 MediaPipe 推理。
- 全部时间使用 `time.perf_counter()` 同一单调时钟域；仅在配置边界进行毫秒换算。
- MediaPipe VIDEO 输入转换成整数毫秒后必须严格递增；相等时间戳跳过，不倒放、不重放。
- 分析帧必须未镜像；预览镜像不能改变视觉左右语义。
- 队列和缓存有界。模型、资源、依赖、窗口、时间戳、积压或推理异常都只产生 `unknown`/不可用状态，不影响相机原接口。
- 首版默认值只是可运行起点：`pre_event_ms=120`、`post_event_ms=80`、`inference_interval_ms=33`、`decision_timeout_ms=200`、`min_confidence=0.90`。Windows 数据验证前不得称为已标定参数。
- 不提交 MediaPipe 模型二进制；从调用方提供的本地 Full `.task` 路径加载。Windows 发行包后续必须显式包含模型。
- 首版不实现高置信融合、A/B 映射修正、光栅事件延迟结算、用户开关或报告落库；这些属于独立模块验证后的薄适配阶段。

---

### Task 1: 定义独立数据契约和事件级分类器（已完成）

**Files:**
- Create: `vision/__init__.py`
- Create: `vision/foot_reference.py`
- Create: `tests/test_foot_reference.py`

- [x] **Step 1: 写失败测试**

覆盖四类枚举、配置校验、低可见度拒识、明显单脚触地、双脚近同时稳定、窗口内矛盾拒识。测试只构造标准化关键点，不依赖 MediaPipe 和 Qt。

```python
def test_classifier_rejects_low_visibility():
    result = classify_event(7, 1.25, [pose_sample(visibility=0.2)])
    assert result.label is FootLabel.UNKNOWN
    assert result.reason == "landmarks_not_visible"
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_foot_reference.py -q`

Expected: FAIL，`vision.foot_reference` 尚不存在。

- [x] **Step 3: 实现最小公共类型**

```python
class FootLabel(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class VisionConfig:
    pre_event_ms: int = 120
    post_event_ms: int = 80
    inference_interval_ms: int = 33
    decision_timeout_ms: int = 200
    min_confidence: float = 0.90

@dataclass(frozen=True)
class VisionDecision:
    event_id: int
    label: FootLabel
    confidence: float
    reason: str
    event_time_s: float
```

同时定义标准化 `Landmark`、`FootPoseSample` 和 `FrameSample`。分类器仅消费左右髋、膝、踝、脚跟和 foot-index 时序；以关键点质量、脚部纵向位置、事件附近速度、左右分离度和窗口一致性共同决定结果。门限不满足即拒识。

- [x] **Step 4: 运行测试**

Run: `python -m pytest tests/test_foot_reference.py -q`

Expected: PASS。

### Task 2: 实现毫秒窗口、全局顺序游标和缓存复用（已完成）

**Files:**
- Create: `vision/event_scheduler.py`
- Create: `tests/test_vision_event_scheduler.py`

- [x] **Step 1: 写失败测试**

覆盖事件排序、等待窗口右边界、重叠窗口不重复推理、整数毫秒相等时只提交一次、迟到/过期/积压事件输出 `unknown`、`reset()` 清空 session 状态。

```python
def test_overlapping_windows_reuse_inference_results():
    scheduler.add_frames(frames_at_ms(0, 300, step=20))
    scheduler.add_event(event_id=1, event_time_s=0.150)
    scheduler.add_event(event_id=2, event_time_s=0.180)
    decisions = scheduler.process_ready(fake_infer, fake_classify, now_s=0.300)
    assert fake_infer.timestamps == sorted(set(fake_infer.timestamps))
    assert {item.event_id for item in decisions} == {1, 2}
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_vision_event_scheduler.py -q`

Expected: FAIL，模块不存在。

- [x] **Step 3: 实现有界 session 状态**

`EventWindowScheduler` 暴露 `add_frame(frame, captured_at_s)`、`add_event(event_id, event_time_s)`、`process_ready(infer_pose, classify_event, now_s)` 和 `reset()`。帧按时间保留；事件按 `(event_time_s, event_id)` 排序；姿态缓存以 VIDEO 整数毫秒为键；只对推理游标之后的新采样调用 `infer_pose`。

- [x] **Step 4: 运行测试**

Run: `python -m pytest tests/test_vision_event_scheduler.py -q`

Expected: PASS。

### Task 3: 实现延迟导入的 MediaPipe Tasks VIDEO 适配器（已完成）

**Files:**
- Create: `vision/mediapipe_pose.py`
- Create: `tests/test_mediapipe_pose_adapter.py`
- Modify: `requirements.txt`

- [x] **Step 1: 用假 MediaPipe API 写失败测试**

验证 `RunningMode.VIDEO`、`num_poses=1`、关闭分割、BGR→RGB、严格递增毫秒、关键点标准化、缺依赖/模型/推理异常的明确错误。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_mediapipe_pose_adapter.py -q`

Expected: FAIL，适配器不存在。

- [x] **Step 3: 实现最小适配接口**

```python
adapter = MediaPipePoseAdapter(model_path)
adapter.open()
sample = adapter.infer_bgr(frame, timestamp_ms)
adapter.close()
```

模块导入时不 import `mediapipe`；只在 `open()` 中延迟加载。缺依赖、缺模型或创建失败抛出 `VisionUnavailableError`，由 Service 转为不可用状态而不是终止进程。

- [x] **Step 4: 更新依赖声明**

在 `requirements.txt` 增加 `mediapipe`，不添加 PyTorch/CUDA。精确版本必须等 Windows Python 3.11 安装和 PyInstaller 验证后再固定，不能依据当前 macOS Python 3.13 环境猜测。

- [x] **Step 5: 运行测试**

Run: `python -m pytest tests/test_mediapipe_pose_adapter.py -q`

Expected: PASS，且无需本机实际安装 MediaPipe。

### Task 4: 只给相机采集类增加兼容的未镜像时间戳接口

**Files:**
- Modify: `camera/logi_camera.py`
- Modify: `camera/tinyse_camera.py`
- Create: `tests/test_camera_analysis_frames.py`

- [x] **Step 1: 写失败测试**

验证两个采集类都公开 `analysis_frame_ready(frame, captured_at_s)`；时间戳在成功读取/解码后立即取自 `time.perf_counter()`；分析帧内容不受预览镜像开关影响；现有 `frame_ready` 仍存在。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_camera_analysis_frames.py -q`

Expected: FAIL，新信号不存在。

- [x] **Step 3: 实现兼容信号**

保留现有 `frame_ready(np.ndarray)`、预览和录制行为。新增 `analysis_frame_ready = Signal(object, float)`，先发原始未镜像 BGR 帧和采集时间，再在原有显示/录制分支进行镜像。相机模块不 import `vision`。

- [ ] **Step 4: 运行相机相关测试**

Run: `python -m pytest tests/test_camera_analysis_frames.py tests/test_embedded_camera_panel.py -q`

Expected: PASS，现有相机 UI 测试不回归。

### Task 5: 实现独立线程 Service 公共 API（已完成）

**Files:**
- Create: `vision/service.py`
- Create: `tests/test_vision_service.py`

- [x] **Step 1: 写失败测试**

使用假适配器验证启动/停止/reset、帧和事件入口、有界队列、模型不可用状态、异常后 `unknown`、决策保留原始 `event_id/event_time_s`，以及 Service 不 import 原项目模块。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_vision_service.py -q`

Expected: FAIL，Service 不存在。

- [x] **Step 3: 实现稳定公共边界**

```python
service = FootVisionService(config, model_path)
service.decision_ready.connect(on_decision)
service.status_changed.connect(on_status)
service.start()
service.submit_frame(frame, captured_at_s)
service.submit_touch_event(event_id, event_time_s)
service.stop()
```

Service 使用标准库 `threading.Thread`，在线程内持有 scheduler 和 adapter；核心 `vision/` 因此不依赖 Qt。`submit_frame()` 和 `submit_touch_event()` 只写入由锁保护的有界 deque，Worker 循环批量取走，推理只在该线程完成。`decision_ready` 和 `status_changed` 使用提供 `.connect()`/`.disconnect()` 的轻量事件钩子，使 Qt signal 可以直接连接 Service 的普通 Python 方法。停止顺序为停止接收、拒识尚未完成事件、关闭 landmarker、清缓存、退出线程。重复 `start/stop` 必须安全。

- [x] **Step 4: 运行服务测试**

Run: `python -m pytest tests/test_vision_service.py -q`

Expected: PASS。

### Task 6: 增加 Windows 独立诊断程序（代码已完成，待 Windows 真机运行）

**Files:**
- Create: `tools/vision_diagnostic.py`
- Create: `tests/test_vision_diagnostic.py`

- [x] **Step 1: 写失败测试**

验证诊断程序只依赖 `camera` 和 `vision` 的公开接口；支持选择 `logi`/`tinyse`、指定 Full `.task` 模型路径、用空格键提交带当前 `perf_counter` 时间戳的模拟触地事件、显示最新四类结果，并把事件时间、结果时间、标签、置信度、原因和延迟写入 CSV。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_vision_diagnostic.py -q`

Expected: FAIL，诊断入口不存在。

- [x] **Step 3: 实现最小诊断入口**

```powershell
python tools/vision_diagnostic.py --camera tinyse --model C:\Iron_Jump\models\pose_landmarker_full.task --output vision-results.csv
```

诊断窗口显示相机状态、模型状态、帧率、队列深度、最近一次事件标签和端到端延迟。空格键模拟光栅 touch，`Q` 安全退出。该工具不得 import engine、processor、报告或主 UI，也不得把手动事件测试描述成光栅同步已经验证。

- [x] **Step 4: 运行测试**

Run: `python -m pytest tests/test_vision_diagnostic.py -q`

Expected: PASS。

### Task 7: 固定包边界和公开调用示例（已完成）

**Files:**
- Modify: `vision/__init__.py`
- Create: `vision/README.md`
- Create: `tests/test_vision_package_boundary.py`

- [x] **Step 1: 写失败测试**

检查 `vision` 公共导出只包含配置、标签、决策、服务和异常；扫描 `vision/*.py`，禁止 import `engine`、`ui`、`hardware`、`config`；导入 `vision` 时不得加载 MediaPipe。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_vision_package_boundary.py -q`

Expected: FAIL，公共边界未完成。

- [x] **Step 3: 写最小调用文档**

`vision/README.md` 只说明模型路径、服务生命周期、如何连接相机的 `analysis_frame_ready`、如何提交光栅触地事件、四类结果语义和回退规则。不写引擎融合代码，不承诺未验证精度。

- [x] **Step 4: 运行边界测试**

Run: `python -m pytest tests/test_vision_package_boundary.py -q`

Expected: PASS。

### Task 8: 回归检查与 Windows 验收关卡

**Files:**
- Modify: `plan.md`
- Create only after real validation: `docs/vision/windows-validation.md`

- [ ] **Step 1: Mac 自动化回归**

Run: `python -m pytest tests/test_foot_reference.py tests/test_vision_event_scheduler.py tests/test_mediapipe_pose_adapter.py tests/test_camera_analysis_frames.py tests/test_vision_service.py tests/test_vision_diagnostic.py tests/test_vision_package_boundary.py tests/test_embedded_camera_panel.py -q`

Expected: PASS。若当前 shell 不是项目 Python 3.11 或缺 PySide6/dayu_widgets，应切换项目环境重跑；不能把 Anaconda Python 3.13 的缺包当作模块失败。

- [x] **Step 2: 差异和耦合检查**

Run: `git diff --check && rg -n "from (engine|ui|hardware|config)|import (engine|ui|hardware|config)" vision`

Expected: `git diff --check` 退出码 0；`rg` 无匹配。确认本轮除 `vision/`、对应测试、`requirements.txt`、两种相机采集类和计划文档外没有新增修改。

- [ ] **Step 3: Windows 10/11 x64 真机安装和模型检查**

在 Python 3.11 clean venv 安装依赖，确认 Full `.task` 能创建 VIDEO landmarker；记录精确版本后固定 `requirements.txt`。失败时不得改用旧 `mp.solutions.pose` 静默绕过。

- [ ] **Step 4: Windows CPU 性能检查**

先用 `tools/vision_diagnostic.py` 的手动事件验证相机、模型、窗口和结果输出，再用一个后续薄适配器同时输入真实相机帧和光栅事件；记录队列深度、拒识原因以及包含 `post_event_ms` 的 P50/P95/P99。P95 目标不超过 200ms；达不到时先降低视觉采样率，再评估 Full→Lite，不降低光栅采样率。

- [ ] **Step 5: 真人标签验收**

用独立人工标注视频按受试者、机位和 session 分组统计覆盖率与已输出标签精确率，单列交叉步、外侧踩踏、踉跄、遮挡和近同时触地。完成前只能声明“独立软件链路完成”，不能声明“左右脚识别准确”。

- [ ] **Step 6: 验证通过后另立融合计划**

融合计划只能增加薄适配层：把相机信号和光栅 touch 事件送入 Service，再按高置信结果更新映射；不得把 MediaPipe、窗口调度或分类逻辑复制进 engine/UI。
