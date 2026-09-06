"""Regression tests for LLMConfigAgent conversation edge cases."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_agent import LLMConfigAgent
from agent.models import (
    AthleteProfile,
    ChatResponse,
    LLMTestConfig,
    LLMTreadmillRunningConfig,
)


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
    def __init__(self, output):
        self.output = output

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def stream_output(self, debounce_by=0.05):
        yield self.output

    async def get_output(self):
        return self.output

    def all_messages(self):
        return ["fake-stream-history"]


class _FakeSequenceAgent:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def run(self, user_message, deps, message_history, instructions):
        self.calls.append(user_message)
        return _FakeRunResult(self.outputs.pop(0))


class _FakeSequenceStreamAgent(_FakeSequenceAgent):
    def __init__(self, stream_output, run_outputs):
        super().__init__(run_outputs)
        self.stream_output = stream_output
        self.stream_calls = []

    def run_stream(self, user_message, deps, message_history, instructions):
        self.stream_calls.append(user_message)
        return _FakeStreamResult(self.stream_output)


def _running_config():
    return LLMTreadmillRunningConfig(
        reply_message="跑步机配置完成",
        stop_type="End of Time",
        test_length="60s",
        treadmill_speed=6.0,
        direction="Opposite side",
    )


class LLMConfigAgentRegressionTest(unittest.TestCase):
    def test_treadmill_running_config_is_saved_for_current_config_query(self):
        agent = LLMConfigAgent(mode="treadmill_running")
        verified = LLMTreadmillRunningConfig(
            reply_message="跑步机配置完成",
            stop_type="End of Time",
            test_length="1min",
            treadmill_speed=6.0,
            direction="Opposite side",
        )

        config, reply = agent._finalize_config_output(
            verified,
            time.perf_counter(),
            [],
        )
        current_config, current_reply = agent.chat(
            "当前配置是什么",
            AthleteProfile(age=30, weight=70, height=170),
        )

        self.assertIsNotNone(config)
        self.assertNotIn("配置参数不合法", reply)
        self.assertIsNone(current_config)
        self.assertIn("| treadmill_speed | 6.0 |", current_reply)
        self.assertIn("| 测试时长 | 01:00 |", current_reply)

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

    def test_gate_miss_structured_output_is_reused_for_config_verification(self):
        message = "你好，我想进行跑步测试，速度6.0，倒计时60s，方向是opposite side"
        fake_agent = _FakeSequenceAgent(
            [_running_config(), _running_config(), _running_config()]
        )
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(
            lambda http_client, mode="jump": fake_agent
        )
        try:
            agent = LLMConfigAgent(mode="treadmill_running")
            self.assertFalse(agent._is_config_request(message))

            config, reply = agent.chat(
                message,
                AthleteProfile(age=30, weight=70, height=170),
            )
            _, current_reply = agent.chat(
                "当前配置是什么",
                AthleteProfile(age=30, weight=70, height=170),
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNotNone(config)
        self.assertEqual(fake_agent.calls, [message] * 3)
        self.assertIn("gate=miss→config-verify", reply)
        self.assertNotIn("不涉及测试配置", reply)
        self.assertIn("| treadmill_speed | 6.0 |", current_reply)
        self.assertIn("| 测试时长 | 01:00 |", current_reply)
        self.assertIn("| direction | Opposite side |", current_reply)

    def test_gate_miss_does_not_accept_one_isolated_config_sample(self):
        message = "1+1="
        fake_agent = _FakeSequenceAgent(
            [
                _running_config(),
                ChatResponse(message="这是普通聊天。"),
                ChatResponse(message="这是普通聊天。"),
            ]
        )
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(
            lambda http_client, mode="jump": fake_agent
        )
        try:
            agent = LLMConfigAgent(mode="treadmill_running")
            config, reply = agent.chat(
                message,
                AthleteProfile(age=30, weight=70, height=170),
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNone(config)
        self.assertEqual(fake_agent.calls, [message] * 3)
        self.assertIn("这是普通聊天。", reply)

    def test_gate_miss_chat_response_stays_on_single_call_path(self):
        message = "你好"
        fake_agent = _FakeSequenceAgent([ChatResponse(message="你好！")])
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(
            lambda http_client, mode="jump": fake_agent
        )
        try:
            agent = LLMConfigAgent(mode="treadmill_running")
            config, reply = agent.chat(
                message,
                AthleteProfile(age=30, weight=70, height=170),
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNone(config)
        self.assertEqual(fake_agent.calls, [message])
        self.assertIn("你好！", reply)
        self.assertIn("gate=miss→chat", reply)

    def test_filter_disagreement_does_not_prompt_and_profile_rule_wins(self):
        message = "帮我配置5次纵跳"
        outputs = [
            LLMTestConfig(
                stop_type="Status change",
                number_of_jumps=5,
                min_contact_time=value,
            )
            for value in (10, 200, 450)
        ]
        fake_agent = _FakeSequenceAgent(outputs)
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(
            lambda http_client, mode="jump": fake_agent
        )
        try:
            agent = LLMConfigAgent(mode="jump")
            config, reply = agent.chat(
                message,
                AthleteProfile(
                    age=65, weight=70, height=170, level="beginner"
                ),
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNotNone(config)
        self.assertEqual(config.min_contact_time, 100)
        self.assertNotIn("不太确定", reply)

    def test_user_intent_disagreement_requires_clarification(self):
        message = "帮我配置纵跳"
        fake_agent = _FakeSequenceAgent(
            [
                LLMTestConfig(stop_type="Status change", number_of_jumps=5),
                LLMTestConfig(stop_type="Status change", number_of_jumps=6),
                LLMTestConfig(stop_type="Status change", number_of_jumps=5),
            ]
        )
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(
            lambda http_client, mode="jump": fake_agent
        )
        try:
            agent = LLMConfigAgent(mode="jump")
            config, reply = agent.chat(
                message,
                AthleteProfile(age=30, weight=70, height=170),
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNone(config)
        self.assertIn("跳跃次数", reply)

    def test_chat_stream_gate_miss_verifies_config_and_emits_summary_once(self):
        message = "你好，我想进行跑步测试，速度6.0，倒计时60s，方向是opposite side"
        fake_agent = _FakeSequenceStreamAgent(
            _running_config(),
            [_running_config(), _running_config()],
        )
        original_make_agent = LLMConfigAgent._make_agent
        LLMConfigAgent._make_agent = staticmethod(
            lambda http_client, mode="jump": fake_agent
        )
        try:
            agent = LLMConfigAgent(mode="treadmill_running")
            chunks = []

            config, reply = agent.chat_stream(
                message,
                AthleteProfile(age=30, weight=70, height=170),
                chunks.append,
            )
        finally:
            LLMConfigAgent._make_agent = original_make_agent

        self.assertIsNotNone(config)
        self.assertEqual(fake_agent.stream_calls, [message])
        self.assertEqual(fake_agent.calls, [message] * 2)
        self.assertEqual(
            "".join(chunks).count("为你配置Treadmill Running Test参数"),
            1,
        )
        self.assertIn("⏱", chunks[-1])
        self.assertIn("gate=miss→config-verify", reply)
        self.assertNotIn("不涉及测试配置", reply)

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
