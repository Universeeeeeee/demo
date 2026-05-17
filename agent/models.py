# models.py — Agent 共享数据结构
# 两种模式（规则引擎 / LLM）的统一输出为 config.test_config.TestConfig
# 本文件仅保留 Agent 特有的输入/输出模型

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---- LLM 自然语言回复模型 ----

class ChatResponse(BaseModel):
    """LLM 选择自然语言回复时使用（非结构化配置）。

    用于打招呼、解释参数含义、追问用户信息等场景。
    与 LLMTestConfig 组成 Union result_type，LLM 自主选择输出哪种。
    """
    message: str = Field(
        description="自然语言回复: 打招呼、解释参数、追问用户、或确认信息"
    )


# ---- LLM 结构化输出模型 ----

class LLMTestConfig(BaseModel):
    """Pydantic AI 结构化输出专用。

    每个 Field 的 description / Literal / ge / le 会自动编码进 JSON Schema，
    发送给 LLM 作为输出约束。LLM 只看 schema，不看 Python 代码。

    此类仅在 llm_agent.py 内部使用，对外通过 .to_test_config() 转换为
    系统通用的 TestConfig dataclass。
    """

    # ---- 对话内容 ----
    reply_message: str = Field(
        default="配置完成",
        description="回复用户的自然语言消息（例如：总结配置参数，或者回答用户的特定问题）"
    )

    # ---- Layer 1: 测试类型 ----
    test_type: Literal["Jump Test"] = Field(
        default="Jump Test",
        description="测试类型，当前仅支持 Jump Test",
    )

    # ---- Layer 2: 主配置参数 ----
    stop_type: Literal["Status change", "End of Time", "External impulse"] = Field(
        default="External impulse",
        description="停止方式: External impulse=手动停止(默认), Status change=按跳跃次数自动停止, End of Time=按时间自动停止",
    )
    number_of_jumps: Optional[int] = Field(
        default=None, ge=1, le=99,
        description="跳跃次数, 仅 stop_type='Status change' 时需要, 范围1-99",
    )
    test_length: Optional[str] = Field(
        default=None,
        description="测试时长, 仅 stop_type='End of Time' 时需要, 必须使用 mm:ss 格式(如 02:00 表示2分钟)",
    )
    start_type: Literal["Status change", "External impulse"] = Field(
        default="Status change",
        description="启动方式: Status change=踩上踏板即开始",
    )
    start_position: Literal["Inside area", "Outside area"] = Field(
        default="Inside area",
        description="起始位置: 用户从踏板上还是踏板外开始",
    )
    starting_foot: Literal["Right", "Left", "Not defined"] = Field(
        default="Not defined",
        description="起跳脚: 通常选择 Not defined",
    )
    finish_position: Literal["Inside area", "Outside area"] = Field(
        default="Inside area",
        description="结束位置: 仅 stop_type='Status change' 时需要, 通常与 start_position 一致",
    )

    # ---- Layer 3: 滤波参数 ----
    min_contact_time: int = Field(
        default=60, ge=0, le=500,
        description="最小接触时间(ms), 低于此值的触地视为无效. 年长者建议80+, 入门用户建议100+",
    )
    min_flight_time: int = Field(
        default=0, ge=0, le=500,
        description="最小腾空时间(ms), 低于此值的腾空合并到接触时间, 0=禁用",
    )
    max_flight_time: int = Field(
        default=0, ge=0, le=5000,
        description="最大腾空时间(ms), 超过此值的腾空直接丢弃, 0=禁用",
    )

    # ---- 格式校验 ----

    @field_validator("test_length")
    @classmethod
    def normalize_test_length(cls, v: Optional[str]) -> Optional[str]:
        """将 LLM 可能输出的各种时间格式统一为 mm:ss。

        处理的非标准格式:
          - "2m" / "2min" → "02:00"
          - "120s" / "120sec" → "02:00"
          - "2:00" → "02:00" (补零)
        """
        if v is None:
            return v

        v = v.strip()

        # 已经是 mm:ss 格式
        if re.match(r"^\d{2}:\d{2}$", v):
            return v

        # m:ss 格式 (缺少前导零)
        m = re.match(r"^(\d{1}):(\d{2})$", v)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"

        # "Xm" / "Xmin" 格式 → mm:00
        m = re.match(r"^(\d+)\s*(?:m|min|minutes?)$", v, re.IGNORECASE)
        if m:
            mins = int(m.group(1))
            return f"{mins:02d}:00"

        # "Xs" / "Xsec" 格式 → 转换为 mm:ss
        m = re.match(r"^(\d+)\s*(?:s|sec|seconds?)$", v, re.IGNORECASE)
        if m:
            total_sec = int(m.group(1))
            return f"{total_sec // 60:02d}:{total_sec % 60:02d}"

        # 无法识别的格式，按原样返回（后续 ParamSchema 会校验）
        return v

    # ---- 转换 ----

    def to_test_config(self):
        """转换为系统通用的 TestConfig dataclass。

        exclude_none=True 确保 None 字段不传入，
        exclude={"reply_message"} 排除 LLM 专用字段。
        """
        from config.test_config import TestConfig
        return TestConfig(**self.model_dump(exclude_none=True, exclude={"reply_message"}))


# ---- Agent 输入模型 ----

@dataclass
class AthleteProfile:
    """用户运动档案 — 供规则引擎和 LLM 使用"""
    age: int
    weight: float
    height: float
    level: str = "intermediate"     # beginner / intermediate / advanced
    focus_side: str = ""            # "" / "left" / "right" / "both"
    device_channels: int = 8
    history: list[dict] = field(default_factory=list)

