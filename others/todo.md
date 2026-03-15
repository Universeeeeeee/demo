任务开发文档：实时步态分析前端 (2data_show.py)
1. 任务目标
新建 2data_show.py，要求：

界面层：完全复用 1data_show.py 的 UI 布局、dayu_widgets 样式及 pyqtgraph 图表配置。

数据层：完全迁移 start_test.py 的数据处理逻辑，包括 UsbWorker 异步采集和 GaitAnalyzer 定期批处理策略。

对接点：将 GaitAnalyzer 计算出的 stride_cm（步幅）、height_cm（跳高）等结果实时推送到 UI 的柱状图和日志栏中。

2. 核心架构逻辑
Worker 线程：使用 start_test.py 中的 UsbWorker，负责连接硬件并发出 led_bits_signal。

主界面缓存：保留 _led_samples 队列（deque），按 _analysis_interval（如 2 秒）触发分析。

分析引擎：使用 GaitAnalyzer.process() 对样本快照进行批处理计算。

3. 待办事项 (To-Do List)
3.1 环境与依赖迁移
[ ] 拷贝 start_test.py 中的所有硬件相关导入（receive, Gait_cal 等）。

[ ] 在 __init__ 中初始化硬件配置参数（DLL 路径、VID、PID）。

3.2 界面与逻辑嫁接
[ ] 初始化分析器：在 __init__ 中实例化 self.gait_analyzer = GaitAnalyzer()。

[ ] 重写启动逻辑：将 on_start_clicked 改为启动 UsbWorker 线程，而非 QTimer 回放。

[ ] 实现数据接收：连接 led_bits_signal 到 _on_led_bits_received 函数。

3.3 数据处理与可视化同步
[ ] 样本累积：实现 _on_led_bits_received，将实时位图存入 self._led_samples。

[ ] 定时分析：实现 _perform_gait_analysis，每隔固定时间调用分析器并获取 result 对象。

[ ] 更新图表：从 result.cycles 中提取最新的数值，调用 1data_show.py 原有的 _update_charts() 进行绘图。

3.4 模式切换适配
[ ] 点击 mode_combo 切换模式时，同步更新 gait_analyzer 的内部配置。

4. 关键技术约束
禁止流式重构：严禁修改 GaitAnalyzer 的调用方式，必须维持“积攒样本 -> 一次性 process”的批处理策略。

UI 稳定性：所有图表更新必须在主线程执行，确保 pyqtgraph 不会因为多线程冲突闪退。