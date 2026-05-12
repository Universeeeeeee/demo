"""
速度诊断 v5 — 直接测试 LLMConfigAgent.chat() 完整链路
用 pydantic_ai conda 环境跑: D:/conda/envs/pydantic_ai/python.exe agent/diagnose_speed.py
"""

import os, time, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

dotenv_path = Path(__file__).resolve().parent.parent / '.env'
from dotenv import load_dotenv
load_dotenv(dotenv_path=dotenv_path)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import GaitAgent, PatientContext

print("=" * 60)
print("完整复现 agent_test_ui.py 的 LLM 调用链路")
print("=" * 60)

agent = GaitAgent(mode="online")
ctx = PatientContext(age=24, weight=70, height=170, condition="healthy")

# 第 1 轮
print("\n>>> 第1轮: \"你好，纵跳测试\"")
t0 = time.perf_counter()
config1, reply1 = agent.chat_online("你好，纵跳测试", ctx)
e1 = time.perf_counter() - t0
print(f"  总耗时: {e1:.1f}s  |  config: {'有' if config1 else '无'}")

# 第 2 轮
print(f"\n>>> 第2轮: \"24岁成年人，跳10次，其他默认\"")
t0 = time.perf_counter()
config2, reply2 = agent.chat_online("24岁成年人，跳10次，其他默认", ctx)
e2 = time.perf_counter() - t0
print(f"  总耗时: {e2:.1f}s  |  config: {'有' if config2 else '无'}")

# 第 3 轮
print(f"\n>>> 第3轮: \"请输出主要参数\"")
t0 = time.perf_counter()
config3, reply3 = agent.chat_online("请输出主要参数", ctx)
e3 = time.perf_counter() - t0
print(f"  总耗时: {e3:.1f}s  |  config: {'有' if config3 else '无'}")

print()
print("=" * 60)
print(f"  第1轮 (ChatResponse):      {e1:.1f}s")
print(f"  第2轮 (LLMTestConfig+采样): {e2:.1f}s")
print(f"  第3轮 (ChatResponse):      {e3:.1f}s")
print("=" * 60)
print()
print("对比用户数据:")
print("  10.6s / 20.9s / 15.1s")
print("  如果我这边也是 3~5s 一圈 → 差距在 API 响应")
print("  如果我这边也 10~20s     → 差距在代码")
