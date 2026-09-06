"""Test-configuration Agent business package."""

from .models import AthleteProfile, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig

__all__ = [
    "AthleteProfile",
    "ConfigService",
    "LLMTreadmillGaitConfig",
    "LLMTreadmillRunningConfig",
]


def __getattr__(name: str):
    if name == "ConfigService":
        from .service import ConfigService

        return ConfigService
    raise AttributeError(name)
