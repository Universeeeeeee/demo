"""Compatibility alias for :mod:`agent.config.service`."""

from __future__ import annotations

import sys

from .config import service as _implementation

sys.modules[__name__] = _implementation
