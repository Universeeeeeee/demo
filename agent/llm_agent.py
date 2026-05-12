# llm_agent.py — LLM 代理（在线模式）
# 使用 Pydantic AI + DeepSeek LLM 进行智能参数配置
#
# 数据流:
#   用户自然语言 + PatientContext
#     → Pydantic AI (Union[LLMTestConfig, ChatResponse])
#     → LLM 自主选择: 自然语言回复 或 结构化配置
#     → 配置路径: LLMTestConfig → TestConfig → ParamSchema 校验
#     → 返回 (TestConfig | None, 回复文字)

from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path
from typing import Union, Callable

from dotenv import load_dotenv
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from config.test_config import TestConfig
from config.param_schema import get_schema
from .models import PatientContext, LLMTestConfig, ChatResponse


def _init_model() -> OpenAIChatModel:
    """初始化 DeepSeek 模型，从 .env 加载配置"""
    dotenv_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=dotenv_path)

    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")

    if not base_url or not api_key:
        raise RuntimeError(
            f"缺少 OPENAI_BASE_URL 或 OPENAI_API_KEY，"
            f"请检查 .env 配置 (查找路径: {dotenv_path})"
        )

    return OpenAIChatModel(
        'deepseek-v4-flash',
        provider=OpenAIProvider(
            base_url=base_url,
            api_key=api_key,
        ),
    )


# ---- System Prompt ----
SYSTEM_PROMPT = """\
你是 IronJump 步态分析系统的参数配置助手。回复使用 Markdown 格式。
你有两种回复方式：
1. ChatResponse — 自然语言：打招呼、解释参数、追问
2. LLMTestConfig — 结构化配置：用户给出足够测试需求时生成

决策规则：
- 闲聊/打招呼 → ChatResponse
- 需求不具体 → ChatResponse 追问
- 明确测试需求后 → LLMTestConfig，reply_message 中解释配置

❗ 宁可多问，不要猜测。必要参数（如停止方式、跳跃次数）必须从用户处明确获得。

配置情景指引：
- 用户说"跳N次" → stop_type="Status change"
- 用户说"测X分钟" → stop_type="End of Time"
- 未指定 → stop_type="External impulse"（默认手动停止）
- 纵跳模式默认双脚起跳，starting_foot="Not defined"，reply_message 中说"双脚跳跃"不要写"未指定"

沉默规则：
底层滤波参数（min_contact_time, min_flight_time, max_flight_time）由 LLM 根据患者信息自动设置，
不要在 reply_message 中提及、解释或展示这些参数，除非用户主动追问。

患者触发值（静默设置，不向用户解释）：
- 老年人(>60): min_contact_time>=80, number_of_jumps<=3
- 术后康复: min_contact_time>=100, number_of_jumps<=3
- 儿童(<12): min_contact_time>=40
- 采样率硬件固定 1000Hz
"""


def _create_agent() -> Agent:
    """创建 Pydantic AI Agent 实例。"""
    model = _init_model()

    agent = Agent(
        model=model,
        deps_type=PatientContext,
        output_type=Union[LLMTestConfig, ChatResponse],
        instructions=SYSTEM_PROMPT,
        retries=1,
        # v4-flash 默认开启 thinking(reasoner)，而 reasoner 不支持 tool_choice（Pydantic AI 结构化输出必须依赖它）
        # 根据 DeepSeek 官网，需通过 extra_body 显式关闭
        model_settings={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    # ---- 工具注册 ----

    @agent.tool
    def get_patient_history(ctx: RunContext[PatientContext]) -> str:
        """获取该患者最近的测试记录，用于参考之前的配置"""
        if not ctx.deps.history:
            return "该患者无历史测试记录"
        recent = ctx.deps.history[-3:]
        return "\n".join(
            f"- {h.get('date','')}: {h.get('test_type','')}, "
            f"jumps={h.get('number_of_jumps','')}, "
            f"min_contact={h.get('min_contact_time','')}ms"
            for h in recent
        )

    @agent.tool
    def get_device_capabilities(ctx: RunContext[PatientContext]) -> str:
        """获取当前连接设备的能力参数"""
        return (
            f"设备通道数: {ctx.deps.device_channels}\n"
            f"采样率: 1000Hz (硬件固定)\n"
            f"当前支持的测试类型: Jump Test"
        )

    return agent


class LLMConfigAgent:
    """
    LLM 配置 Agent — 支持多轮对话，管理对话历史。

    延迟初始化: Agent 实例在首次调用 chat() 时才创建，
    避免仅导入此模块就触发 .env 加载和网络连接。
    """

    # ---- ClarifyGPT 配置 ----
    N_SAMPLES = 3         # 总采样次数（含首次）
    MIN_CONFIG_COUNT = 2  # 至少需要几份 LLMTestConfig 才算有效
    CRITICAL_FIELDS = ["stop_type", "number_of_jumps", "test_length"]
    FIELD_LABELS = {
        "stop_type": "停止方式",
        "number_of_jumps": "跳跃次数",
        "test_length": "测试时长",
    }

    def __init__(self):
        self._agent: Agent | None = None
        self._schema = get_schema()
        self.message_history = None

    def _ensure_agent(self):
        """延迟创建 Agent，首次调用时才初始化。"""
        if self._agent is None:
            self._agent = _create_agent()

    def warmup(self):
        """预热: 提前初始化 Agent，省去首次 chat() 的初始化耗时（~6s）。"""
        self._ensure_agent()

    def _snapshot_before_last_output(self) -> list:
        """获取不包含最后一条 ModelResponse 的 history 快照。

        pydantic-ai 的 message_history 可能包含:
          [..., ModelRequest, (ToolReturn...), ModelResponse]
        需要精确去掉最后一条 ModelResponse，保留之前的全部内容。
        """
        from pydantic_ai.messages import ModelResponse

        if not self.message_history:
            return []
        for i in range(len(self.message_history) - 1, -1, -1):
            if isinstance(self.message_history[i], ModelResponse):
                return list(self.message_history[:i])
        return list(self.message_history)

    def _cluster_configs(
        self, configs: list[LLMTestConfig],
    ) -> list[list[LLMTestConfig]]:
        """按关键字段值聚类 — N 份配置按 (stop_type, jumps, ...) 分组。

        一组 = 需求清晰、LLM 结论一致；多组 = 需求有歧义。
        """
        groups: dict[tuple, list[LLMTestConfig]] = {}
        for c in configs:
            key = tuple(getattr(c, f) for f in self.CRITICAL_FIELDS)
            groups.setdefault(key, []).append(c)
        return list(groups.values())

    def _find_disagreements(
        self, configs: list[LLMTestConfig],
    ) -> dict[str, set]:
        """对比 N 份配置的关键字段，返回不一致的字段及其值集合。

        当前所有字段均为 int/str/Literal，直接用 == 比较。
        若未来新增 float 字段，需改用 math.isclose()。
        """
        disagreements = {}
        for field_name in self.CRITICAL_FIELDS:
            values = {getattr(c, field_name) for c in configs}
            if len(values) > 1:
                disagreements[field_name] = values
        return disagreements

    def _generate_clarification(self, disagreements: dict[str, set]) -> str:
        """将分歧字段翻译成自然语言追问（模板方式）。"""
        parts = ["我对以下参数不太确定，请您明确一下："]
        for field, values in disagreements.items():
            label = self.FIELD_LABELS.get(field, field)
            vals_str = " 或 ".join(str(v) for v in sorted(str(x) for x in values))
            parts.append(f"- {label}: 应该是 {vals_str}？")
        return "\n".join(parts)

    def _format_config_reply_markdown(
        self,
        config: TestConfig,
        raw_reply: str,
    ) -> str:
        """LLM 自然语言回复末尾追加 Markdown 配置摘要表格。"""
        d = config.to_dict()
        rows = [
            ("停止", d.get("stop_type", "")),
            ("次数", d.get("number_of_jumps", "—")),
            ("起跳脚", d.get("starting_foot", "")),
        ]
        table = "| 参数 | 值 |\n|---|---|\n"
        for k, v in rows:
            table += f"| {k} | {v} |\n"
        return raw_reply + "\n\n" + table

    async def _verify_config(
        self,
        first_output: LLMTestConfig,
        user_message: str,
        ctx: PatientContext,
        timing: list[str] | None = None,
    ) -> tuple[LLMTestConfig | None, str | None]:
        """ClarifyGPT: 并行采样 + 聚类验证。

        所有 N 个样本平等，无主从之分。分三步：
        1. 并行采样 N-1 次（与首次同级，共同组成 N 个 peer）
        2. 按关键字段值聚类
        3. 1 组 → 随机选一个返回；多组 → 生成追问
        """
        if timing is None:
            timing = []
        snapshot = self._snapshot_before_last_output()

        async def _sample():
            t0 = time.perf_counter()
            result = await self._agent.run(
                user_message, deps=ctx, message_history=snapshot
            )
            elapsed = time.perf_counter() - t0
            return result, elapsed

        tasks = [_sample() for _ in range(self.N_SAMPLES - 1)]
        gather_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集所有 peer（首次 + 并行采样），彼此平等
        peers: list[LLMTestConfig] = [first_output]
        chat_count = 0

        for i, item in enumerate(gather_results):
            if isinstance(item, Exception):
                chat_count += 1
                continue
            result, elapsed = item
            print(f"[Timing] 并行采样 peer #{i + 1}: {elapsed:.1f}s")
            timing.append(f"peer{i+1}={elapsed:.1f}s")
            output = result.output
            if isinstance(output, LLMTestConfig):
                peers.append(output)
            else:
                chat_count += 1

        if len(peers) < self.MIN_CONFIG_COUNT:
            return None, (
                f"信息可能不够充分"
                f"（{chat_count}/{self.N_SAMPLES - 1} 次采样选择了追问而非生成配置）。"
                f"请补充更多测试需求信息。"
            )

        # 聚类 — ClarifyGPT 核心：按输出一致性分组
        clusters = self._cluster_configs(peers)

        if len(clusters) == 1:
            # 全部一致 — 组内任一可代表整体
            return random.choice(clusters[0]), None

        # 多组 = 需求有歧义 — 生成追问
        disagreements = self._find_disagreements(peers)
        return None, self._generate_clarification(disagreements)

    def _finalize(
        self,
        config: TestConfig | None,
        message: str,
        t_start: float,
        timing: list[str],
        label: str,
        stream_callback: Callable[[str], None] | None = None,
    ) -> tuple[TestConfig | None, str]:
        """统一的收尾：计时 + hint 拼接。消除 ChatResponse/LLMTestConfig/追问 三条分支的重复。"""
        total = time.perf_counter() - t_start
        print(f"[Timing] chat() 总计: {total:.1f}s ({label})")
        hint = f"\n\n⏱ {total:.1f}s ({', '.join(timing)})"
        if stream_callback:
            stream_callback(hint)
        return config, message + hint

    async def _process_output(
        self,
        output: Union[LLMTestConfig, ChatResponse],
        user_message: str,
        ctx: PatientContext,
        t_start: float,
        timing: list[str],
        stream_callback: Callable[[str], None] | None = None,
    ) -> tuple[TestConfig | None, str]:
        """处理 LLM 输出——流式和非流式共享。"""
        if isinstance(output, ChatResponse):
            return self._finalize(None, output.message, t_start, timing, "ChatResponse",
                                  stream_callback)

        if isinstance(output, LLMTestConfig):
            verified, clarify_msg = await self._verify_config(
                output, user_message, ctx, timing,
            )
            if clarify_msg:
                return self._finalize(None, clarify_msg, t_start, timing, "追问",
                                      stream_callback)

            config = verified.to_test_config()
            values = config.to_dict()
            values.setdefault("test_macro_type", "Performance")
            errors = self._schema.validate(config.test_type, values)
            if errors:
                return None, f"配置参数不合法: {'; '.join(errors)}"
            normalized_reply = self._format_config_reply_markdown(
                config=config, raw_reply=verified.reply_message,
            )
            return self._finalize(config, normalized_reply, t_start, timing, "配置成功",
                                  stream_callback)

        return None, f"未知的输出类型: {type(output).__name__}"

    def chat(
        self, user_message: str, ctx: PatientContext
    ) -> tuple[TestConfig | None, str]:
        """
        一轮对话（同步接口，内部用 asyncio.run 统一事件循环以支持并行采样）。

        Returns:
            (config, reply_text):
            - LLM 生成了完整配置: config 有值, reply_text 是配置摘要
            - LLM 自然语言回复/追问: config 为 None, reply_text 是回复内容
        """
        self._ensure_agent()

        t_start = time.perf_counter()
        timing: list[str] = []

        async def _flow() -> tuple[TestConfig | None, str]:
            t0 = time.perf_counter()
            result = await self._agent.run(
                user_message, deps=ctx, message_history=self.message_history,
            )
            timing.append(f"1st={time.perf_counter() - t0:.1f}s")
            print(f"[Timing] 首次 LLM 调用: {timing[-1]}")
            self.message_history = result.all_messages()
            return await self._process_output(
                result.output, user_message, ctx, t_start, timing,
            )

        try:
            return asyncio.run(_flow())
        except Exception as e:
            print(f"[Timing] chat() 总计: {time.perf_counter() - t_start:.1f}s (失败)")
            return None, f"配置生成失败: {e}"

    def chat_stream(
        self, user_message: str, ctx: PatientContext,
        on_chunk: Callable[[str], None],
    ) -> tuple[TestConfig | None, str]:
        """
        流式版 chat()——每收到文本增量即回调 on_chunk(text)。

        用 stream_output() 而非 stream_text()，因为 Union 结构化输出走 tool_call，
        stream_text() 拿不到任何文本。改为监听 partial 对象，从中提取 message/reply_message 增量。
        """
        self._ensure_agent()

        t_start = time.perf_counter()
        timing: list[str] = []

        async def _flow_stream() -> tuple[TestConfig | None, str]:
            t0 = time.perf_counter()
            async with self._agent.run_stream(
                user_message, deps=ctx, message_history=self.message_history,
            ) as result:
                prev = ""
                async for partial in result.stream_output(debounce_by=0.05):
                    if isinstance(partial, ChatResponse):
                        current = partial.message or ""
                    elif isinstance(partial, LLMTestConfig):
                        current = partial.reply_message or ""
                    else:
                        continue
                    if current and len(current) > len(prev):
                        delta = current[len(prev):]
                        on_chunk(delta)
                        prev = current

                timing.append(f"1st={time.perf_counter() - t0:.1f}s")
                print(f"[Timing] 首次 LLM 调用(流式): {timing[-1]}")

                output = await result.get_output()
                self.message_history = result.all_messages()
            return await self._process_output(
                output, user_message, ctx, t_start, timing, on_chunk,
            )

        try:
            return asyncio.run(_flow_stream())
        except Exception as e:
            print(f"[Timing] chat_stream() 总计: {time.perf_counter() - t_start:.1f}s (失败)")
            return None, f"配置生成失败: {e}"

    def reset(self):
        """清空对话历史，开始新会话。"""
        self.message_history = None
