# SubjectStore UI 集成计划

## Summary
将 `SubjectStore` 接入主 UI 流程：SetupView 顶部增受试者选择区（可选），测试结束自动存档，支持加载上次参数。

## 数据流

```
SetupView                            MainWindow
  │                                    │
  │ 选受试者(可选)                      │
  │ 点"加载上次参数"                    │
  │   → store.get_last_session()       │
  │   → ParamPanel.set_config() 回填   │
  │                                    │
  │ 点"准备就绪"                        │
  │   → emit ready_signal(             │
  │       SessionSetup(config,         │
  │                    subject_id,     │
  │                    subject))       │
  │                                    │ _on_ready(setup)
  │                                    │   self._active_config = setup.config
  │                                    │   self._subject_id   = setup.subject_id
  │                                    │   self._subject      = setup.subject
  │                                    │   controller.prepare(setup.config)
  │                                    │
  │                                    │            test runs...
  │                                    │
  │                                    │ _on_session_finished(report)
  │                                    │   if self._subject_id is not None
  │                                    │      and self._active_config is not None:
  │                                    │     h = (self._subject.height_cm
  │                                    │          if self._subject else None)
  │                                    │     w = (self._subject.weight_kg
  │                                    │          if self._subject else None)
  │                                    │     try:
  │                                    │       store.record_session(
  │                                    │         subject_id, config, report,
  │                                    │         height_cm=h, weight_kg=w)
  │                                    │     except Exception:
  │                                    │       log.exception("archive failed")
  │                                    │   report_view.load_report(report)
```

受试者不选 → `subject_id=None` → 现有流程完整保留，不存档。

## Key Changes

### 1. `ui/views/setup_view.py` — 定义 `SessionSetup` + 顶部受试者区域

`SessionSetup` 是 UI 事件载荷，不是持久化概念，定义在 `setup_view.py` 顶部：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class SessionSetup:
    config: TestConfig
    subject_id: int | None = None
    subject: SubjectProfile | None = None
```

顶部加受试者横条：
- `QLineEdit` 搜索框 — `textChanged` 触发 `store.search_subjects()`，结果填入下拉
- `QComboBox` 结果列表 — 每行显示 `display_name` + `display_labels` 摘要；用 `itemData(Qt.UserRole)` 存储 `SubjectSearchResult`，靠 id 定位，不靠 display text 反查
- "新建" 按钮 — 弹出简易对话框：姓名（必填）、出生年份（默认 1990）、训练水平（下拉，默认 intermediate）。调用 `create_subject()` 后，`search_subjects(display_name)` 按 id 找到 `SubjectSearchResult`，加入下拉并选中（itemData 统一为 `SubjectSearchResult`，不混用 `SubjectProfile`）
- "加载上次参数" 按钮 — 调用 `store.get_last_session(subject_id)`：
  - `None` → 弹出提示"该用户尚无测试记录"，不改 ParamPanel
  - 有值 → `TestConfig.from_dict(json.loads(session.config_json))`，`ParamPanel.set_config()` 回填

`ready_signal` 改为 `Signal(object)`，emit `SessionSetup(config, subject_id, subject)`。

`__init__` 签名：`def __init__(self, subject_store: SubjectStore | None = None, parent=None)`，MainWindow 注入。

### 2. `ui/main_window.py` — 持有 Store，处理存档

`__init__`:
```python
import logging
log = logging.getLogger(__name__)

try:
    self._subject_store = SubjectStore()
except Exception:
    log.exception("SubjectStore init failed, subject features disabled")
    self._subject_store = None
self._setup_view = SetupView(subject_store=self._subject_store)
self._active_config: TestConfig | None = None
self._subject_id: int | None = None
self._subject: SubjectProfile | None = None
```

`SetupView.__init__` 签名：
```python
def __init__(self, subject_store: SubjectStore | None = None, parent=None):
```
若 `subject_store is None`，隐藏受试者区域，旧流程完整可用。

`_on_ready(setup)`:
```python
self._active_config = setup.config
self._subject_id = setup.subject_id
self._subject = setup.subject
self._exec_view.reset()
self._exec_view.configure(setup.config)
self._controller.prepare(setup.config)
self._go_to_execution()
```

`_on_session_finished(report)`:
```python
if self._subject_id is not None and self._active_config is not None:
    h = self._subject.height_cm if self._subject else None
    w = self._subject.weight_kg if self._subject else None
    try:
        self._subject_store.record_session(
            subject_id=self._subject_id,
            config=self._active_config,
            report=report,
            height_cm=h,
            weight_kg=w,
        )
    except Exception:
        log.exception("Failed to archive session")
self._report_view.load_report(report)
self._go_to_report()
```

`_go_to_setup()`:
```python
self._subject_id = None
self._subject = None
self._active_config = None
# ... rest of existing logic
```

### 3. `ui/session_controller.py` — 不改

SessionController 已有 `self._config` 属性（line 174），但 `_on_ready` 已通过 `self._active_config = setup.config` 保存了确定值，不需要从 Controller 回读。SessionController 不碰数据库。

## 不变的部分
- `ParamPanel`、`TestConfig`、`TestReport` — 不改
- `SessionController` 信号和生命周期 — 不改
- `ReportView`、`ExecutionView` — 不改
- 离线/在线 Agent 流程 — 不改
- `agent_test_ui.py`（独立测试工具）— 不改

## 新建受试者对话框（MVP 最小版）

三个字段：姓名（必填）、出生年份（必填，默认 1990）、训练水平（下拉，默认 intermediate）。`create_subject()` 返回 id 后自动选中新受试者。

## 身高体重快照规则

`record_session()` 的身高体重取自 `self._subject.height_cm` / `self._subject.weight_kg`（即 subjects 表中该受试者最近存档值）。如果为 None，传 None，session 不更新 subjects 表的测量值。不在主 UI 额外加输入框。

## Test Plan

- 自动化：
  ```bash
  python -m py_compile ui/main_window.py ui/views/setup_view.py
  python tests/test_subject_store.py
  ```
- 手工验收：
  1. 不选受试者 → 现有 Jump Test 流程完整可用，无报错
  2. data/ 目录不可写 → 主窗口正常启动，受试者区域隐藏，旧流程可用
  3. 新建受试者 → 出现在搜索列表 → 可选择
  4. 选择受试者 → 加载上次参数 → ParamPanel 回填正确
  5. 新受试者点击"加载上次参数" → 弹出"尚无测试记录"，ParamPanel 不变
  6. 完成测试 → 再次进入同一受试者 → 最近记录在搜索列表中可见
  7. 数据库不可写时 → `log.exception` 记录，不影响切到 ReportView

## Assumptions
- `MainWindow` 是 `SubjectStore` 的唯一持有者
- MVP 只做 `LIKE` 搜索，不做拼音
- `SessionSetup` 定义在 `setup_view.py`，它是 UI 层概念不是持久化层概念
