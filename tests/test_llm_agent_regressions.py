"""Regression tests for LLMConfigAgent conversation edge cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_agent import LLMConfigAgent
from agent.models import AthleteProfile, LLMTestConfig


class _FakeRunResult:
    def __init__(self, output):
        self.output = output

    def all_messages(self):
        return ["fake-history"]


class _FakeConfigAgent:
    def __init__(self):
        self.calls = []

    async def run(self, user_message, deps, message_history, instructions):
        self.calls.append(user_message)
        return _FakeRunResult(
            LLMTestConfig(
                reply_message="为你配置纵跳测试参数，以下是设置总结：",
                stop_type="Status change",
                number_of_jumps=5,
                finish_position="Inside area",
            )
        )


class _FakeStreamResult:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def stream_output(self, debounce_by=0.05):
        yield LLMTestConfig(
            reply_message="为你配置纵跳测试参数，以下是设置总结：旧配置",
            stop_type="Status change",
            number_of_jumps=3,
        )

    async def get_output(self):
        return LLMTestConfig(
            reply_message="为你配置纵跳测试参数，以下是设置总结：旧配置",
            stop_type="Status change",
            number_of_jumps=3,
        )

    def all_messages(self):
        return ["fake-stream-history"]


class _FakeStreamAgent:
    def run_stream(self, user_message, deps, message_history, instructions):
        return _FakeStreamResult()


class LLMConfigAgentRegressionTest(unittest.TestCase):
    def test_current_config_table_request_uses_last_config_without_regenerating(self):
        fake_agent = _FakeConfigAgent()
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(lambda http_client, mode="jump": fake_agent)
        try:
            agent = LLMConfigAgent()
            ctx = AthleteProfile(age=30, weight=70, height=170)

            config, reply = agent.chat("普通用户 5 次纵跳", ctx)
            current_config, current_reply = agent.chat("表格形式输出完整配置参数", ctx)
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNotNone(config)
        self.assertIn("共 5 次", reply)
        self.assertIsNone(current_config)
        self.assertIn("| 参数 | 值 |", current_reply)
        self.assertIn("| 跳跃次数 | 5 |", current_reply)
        self.assertNotIn("为你配置纵跳测试参数", current_reply)
        self.assertEqual(fake_agent.calls, ["普通用户 5 次纵跳"] * 3)

    def test_chat_stream_gate_miss_emits_fallback_body_before_timing(self):
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(lambda http_client, mode="jump": _FakeStreamAgent())
        try:
            agent = LLMConfigAgent()
            chunks = []

            config, reply = agent.chat_stream(
                "1+1=",
                AthleteProfile(age=30, weight=70, height=170),
                chunks.append,
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNone(config)
        self.assertTrue(chunks)
        self.assertEqual(chunks[0], "这个问题不涉及测试配置，当前配置保持不变。")
        self.assertIn("⏱", chunks[-1])
        self.assertIn("这个问题不涉及测试配置", reply)

    def test_gait_agent_caches_llm_agent_per_agent_mode(self):
        from agent import llm_agent as llm_agent_module
        from agent.gait_agent import GaitAgent

        class _FakeLLMConfigAgent:
            instances = []

            def __init__(self, mode="jump"):
                self.mode = mode
                self.calls = []
                _FakeLLMConfigAgent.instances.append(self)

            def chat(self, message, ctx):
                self.calls.append((message, ctx))
                return None, f"{self.mode}:{message}"

            def reset(self):
                pass

        original_agent = llm_agent_module.LLMConfigAgent
        llm_agent_module.LLMConfigAgent = _FakeLLMConfigAgent
        try:
            agent = GaitAgent(mode="online")
            ctx = AthleteProfile(age=30, weight=70, height=170)

            _, gait_reply = agent.chat_online(
                "步态", ctx, agent_mode="treadmill_gait"
            )
            _, gait_reply_again = agent.chat_online(
                "继续", ctx, agent_mode="treadmill_gait"
            )
            _, jump_reply = agent.chat_online("纵跳", ctx)
        finally:
            llm_agent_module.LLMConfigAgent = original_agent

        self.assertEqual(gait_reply, "treadmill_gait:步态")
        self.assertEqual(gait_reply_again, "treadmill_gait:继续")
        self.assertEqual(jump_reply, "jump:纵跳")
        self.assertEqual(
            [instance.mode for instance in _FakeLLMConfigAgent.instances],
            ["treadmill_gait", "jump"],
        )


if __name__ == "__main__":
    unittest.main()
