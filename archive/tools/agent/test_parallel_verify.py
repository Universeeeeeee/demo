"""P0+P1+P2 集成验证 — 完整对话流程计时"""
import time, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
dotenv_path = Path(__file__).resolve().parent.parent / '.env'
from dotenv import load_dotenv
load_dotenv(dotenv_path=dotenv_path)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import GaitAgent, PatientContext

agent = GaitAgent(mode="online")
ctx = PatientContext(age=24, weight=70, height=170, condition="healthy")

# 预热
agent.switch_mode("online")

# 第1轮: 问候
print(">>> 第1轮 (问候)")
t0 = time.perf_counter()
_, r1 = agent.chat_online("你好，我想配置纵跳测试", ctx)
print(f"  {time.perf_counter()-t0:.1f}s\n")

# 第2轮: 生成配置（触发并行验证）
print(">>> 第2轮 (生成配置 + 并行验证)")
t0 = time.perf_counter()
config, r2 = agent.chat_online("24岁成年男性，跳10次，其他默认", ctx)
print(f"  {time.perf_counter()-t0:.1f}s")
print(f"  stop_type={config.to_dict().get('stop_type')}, jumps={config.to_dict().get('number_of_jumps')}")

# 第3轮: 追问
print(f"\n>>> 第3轮 (追问)")
t0 = time.perf_counter()
_, r3 = agent.chat_online("请输出主要参数", ctx)
print(f"  {time.perf_counter()-t0:.1f}s")
