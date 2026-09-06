"""Compatibility alias for :mod:`agent.config.models`."""

from __future__ import annotations

import sys

from .config import models as _implementation

sys.modules[__name__] = _implementation
