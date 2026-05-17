# gait_agent.py — 门面类（Facade）
# 统一对外接口，根据模式切换规则引擎 / LLM 代理

from __future__ import annotations

from config.test_config import TestConfig
from .models import AthleteProfile
from .rule_engine import RuleEngine


class GaitAgent:
    """
    统一门面 — 用户选择模式，内部路由到对应引擎

    用法:
        agent = GaitAgent(mode="offline")

        # 离线模式：UI 传入 test_type + 用户信息
        config = agent.configure_offline("Jump Test", athlete_ctx)

        # 在线模式：自然语言对话
        agent.switch_mode("online")
        config, reply = agent.chat_online("入门用户，做5次跳跃测试", athlete_ctx)
    """

    def __init__(self, mode: str = "offline"):
        """
        mode:
          "offline" — 规则引擎 (离线/无需联网)
          "online"  — LLM + Pydantic AI (在线/需要联网)
        """
        self.mode = mode
        self._rule_engine = RuleEngine()
        self._llm_agent = None  # 延迟初始化，避免离线模式也导入 pydantic_ai

    @property
    def llm_agent(self):
        """延迟导入 LLMConfigAgent，仅在线模式下才加载"""
        if self._llm_agent is None:
            from .llm_agent import LLMConfigAgent
            self._llm_agent = LLMConfigAgent()
        return self._llm_agent

    def warmup_online(self):
        """初始化在线 Agent，不改变当前模式或对话历史。"""
        self.llm_agent.warmup()

    def switch_mode(self, mode: str):
        """切换模式，首次进入在线模式时确保 Agent 已初始化。"""
        self.mode = mode
        if mode == "online":
            self.warmup_online()
            self.llm_agent.reset()

    # ---- 离线模式：直接配置 ----
    def configure_offline(
        self, test_type: str, ctx: AthleteProfile
    ) -> TestConfig:
        """离线模式：UI 传入 test_type + 用户信息 → 直接返回配置"""
        return self._rule_engine.configure(test_type, ctx)

    # ---- 在线模式：对话式配置 ----
    def chat_online(
        self, message: str, ctx: AthleteProfile
    ) -> tuple[TestConfig | None, str]:
        """在线模式：自然语言对话 → 返回 (配置或None, 回复文字)"""
        return self.llm_agent.chat(message, ctx)

    def chat_online_stream(
        self, message: str, ctx: AthleteProfile, on_chunk
    ) -> tuple[TestConfig | None, str]:
        """在线模式流式版：每收到文本增量回调 on_chunk(text)"""
        return self.llm_agent.chat_stream(message, ctx, on_chunk)

    def reset_chat(self):
        """重置在线对话"""
        if self._llm_agent:
            self._llm_agent.reset()
