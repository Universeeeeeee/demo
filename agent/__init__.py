"""Agent package exports."""

from .models import AthleteProfile, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig

__all__ = [
    "AthleteProfile",
    "GaitAgent",
    "LLMTreadmillGaitConfig",
    "LLMTreadmillRunningConfig",
]


def __getattr__(name: str):
    if name == "GaitAgent":
        from .gait_agent import GaitAgent
        return GaitAgent
    raise AttributeError(name)
