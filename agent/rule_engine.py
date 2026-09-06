"""Compatibility alias for :mod:`agent.config.rule_engine`."""

from __future__ import annotations

import sys

from .config import rule_engine as _implementation

sys.modules[__name__] = _implementation
