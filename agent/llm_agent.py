"""Compatibility alias for :mod:`agent.config.agent`."""

from __future__ import annotations

import sys

from .config import agent as _implementation

sys.modules[__name__] = _implementation
