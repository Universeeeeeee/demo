# Iron_Jump

Iron_Jump 是一套兼容 OptoJump 工作方式的运动测试与分析系统，面向纵跳、跑步机步态和跑步测试场景。系统通过两侧红外光栅采集脚部遮挡信号，实时识别触地、离地和步态事件，并提供测试配置、过程可视化、结果报告与历史记录管理。

> 项目目前处于原型验证阶段，适合研发、算法验证和受控测试，不应直接用于医疗诊断或临床决策。

## 主要功能

- 纵跳测试：触地时间、腾空时间和跳跃表现分析。
- 跑步机测试：步态与跑步模式的接触、腾空及相关指标分析。
- 实时可视化：双侧 96 LED 状态和测试指标展示。
- 测试报告：结果汇总、历史记录查询和 Excel 导出。
- 受试者管理：个人资料和测试记录持久化。
- 相机支持：普通 USB 相机及 OBSBOT Tiny SE 预览与录像。
- 智能配置：可选的自然语言参数配置，以及不依赖在线模型的规则模式。

## 系统组成

```text
红外光栅（1000 Hz）
  → USB 数据采集
  → 触地 / 离地与步态事件识别
  → 实时界面
  → 测试报告与历史记录
```

## 运行环境

- Python 3.11
- Windows 10/11：连接 USB 光栅、加载 `CyUsbInterface.dll` 和使用 Tiny SE DirectShow 采集时必需。
- macOS/Linux：可用于部分界面、算法和自动化测试开发，但不能直接使用 Windows DLL 硬件链路。
- 两根 96 LED 红外光栅；采样率固定为 1000 Hz。
- OBSBOT Tiny SE 为可选设备。

项目主要使用 PySide6、NumPy、OpenCV、Pydantic、SQLite、pyqtgraph 和 openpyxl。完整 Python 依赖见 [`requirements.txt`](requirements.txt)。界面还依赖 `dayu_widgets`；该源码目录不随仓库提交，需要在运行环境中单独准备。

## 安装

```bash
git clone git@github.com:Universeeeeeee/Iron_Jump.git
cd Iron_Jump

python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

macOS/Linux：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

如需使用在线智能配置，在项目根目录创建 `.env`：

```dotenv
OPENAI_BASE_URL=<兼容 OpenAI API 的服务地址>
OPENAI_API_KEY=<API 密钥>
```

不配置上述变量时，硬件采集、规则算法和不依赖在线模型的功能仍可独立开发与测试。

## 使用方法

启动主程序：

```bash
python ui/main_window.py
```

启动智能配置测试界面（不需要硬件）：

```bash
python agent/agent_test_ui.py
```

直接测试 USB 通信：

```bash
python hardware/receive.py
```

运行自动化测试：

```bash
python -m pytest -q
```

## 当前状态与限制

- 已接入 Jump Test、Treadmill Gait Test 和 Treadmill Running Test。
- 当前仅支持一对一米段、每侧 96 LED 的光栅；多米段级联尚未实现。
- 跑步机算法仍需要更多真实设备和人工真值对照。
- `External impulse` 以及 Sprint、Tapping、Reaction Times、Static Test 等模式尚未完整实现。
- 在线智能配置需要兼容 OpenAI API 的模型服务；规则模式可离线运行。

## 文档

- [系统架构](docs/architecture.md)
- [当前开发计划](plan.md)

## 目录概览

```text
hardware/    USB 通信与协议解析
engine/      运动事件与步态分析引擎
config/      测试参数和报告数据模型
ui/          PySide6 桌面界面
data/        受试者和测试记录
agent/       智能配置与规则引擎
camera/      USB 相机与 Tiny SE 支持
tools/       诊断工具
tests/       自动化测试
```
