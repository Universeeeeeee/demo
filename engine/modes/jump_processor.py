"""
jump_processor.py — Jump Test mode processor

Wraps SingleFootDetector and maintains jump statistics (air_times,
contact_times, cycle_times) used to build the final JumpTestReport.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from config.test_config import TestConfig
from config.test_report import (
    G,
    JumpTestReport,
    _cadences,
    _jump_heights,
    _max_or_zero,
    _mean,
    _min_or_zero,
    _population_std,
    _positive_values,
)
from ..single_foot_tracker import SingleFootDetector, LedFrame, FootEvent

log = logging.getLogger(__name__)


class JumpProcessor:
    """Mode processor for Jump Test (vertical jump analysis).

    Owns the SingleFootDetector and accumulates jump statistics.
    """

    name = "jump"
    display_mode = "纵跳"

    def __init__(self, config: TestConfig) -> None:
        self._config = config

        # ---- 检测器 ----
        self._detector = SingleFootDetector(
            touch_ratio_threshold=0.12,
            lift_ratio_threshold=0.05,
            confirm_samples=2,
        )

        # ---- 纵跳统计 ----
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time: Optional[float] = None
        self.last_lift_time: Optional[float] = None
        self.cycle_times: List[float] = []
        self.air_times: List[float] = []
        self.contact_times: List[float] = []

    def reset(self) -> None:
        """Reset all jump statistics and detector."""
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self.cycle_times.clear()
        self.air_times.clear()
        self.contact_times.clear()
        self._detector = SingleFootDetector(
            touch_ratio_threshold=0.12,
            lift_ratio_threshold=0.05,
            confirm_samples=2,
        )

    def process_raw_frame(
        self, contact_bits: List[int], rel_time: float, abs_time: float
    ) -> List[object]:
        """Process one frame using SingleFootDetector.

        Returns list of FootEvent objects to be re-emitted by GaitEngine.
        """
        frame = LedFrame(timestamp=rel_time, bits=contact_bits)
        events: List[object] = []
        for ev in self._detector.consume(frame):
            self._accumulate_hop_stats(ev)
            events.append(ev)
        return events

    def _accumulate_hop_stats(self, ev: FootEvent) -> None:
        """Accumulate jump statistics from a FootEvent.

        Filtering rules per OptoJump manual 4.2.2.2:
          - min_contact_time: contact below this threshold is merged into
            associated flight time.
          - min_flight_time: flight below this threshold is merged into
            associated contact time.
          - max_flight_time: flight above this threshold is discarded.
        """
        ev._air_time = None
        ev._contact_time = None
        ev._hop_height = None

        cfg = self._config

        if ev.kind.lower() == "touch":
            self.touch_count += 1
            if self.last_lift_time is not None:
                air_time = ev.time - self.last_lift_time
                if air_time > 0:
                    if cfg.max_flight_time > 0 and air_time * 1000 > cfg.max_flight_time:
                        log.debug("air_time %.1fms > max_flight_time %dms, discarded",
                                  air_time * 1000, cfg.max_flight_time)
                    elif cfg.min_flight_time > 0 and air_time * 1000 < cfg.min_flight_time:
                        log.debug("air_time %.1fms < min_flight_time %dms, merged to contact",
                                  air_time * 1000, cfg.min_flight_time)
                        if self.contact_times:
                            self.contact_times[-1] += air_time
                    else:
                        self.air_times.append(air_time)
                        ev._air_time = air_time
                        ev._hop_height = 0.5 * G * (air_time / 2) ** 2
                        ev._contact_time = self.contact_times[-1] if self.contact_times else None
            if self.last_touch_time is not None and self.touch_count > 2:
                cycle = ev.time - self.last_touch_time
                if cycle > 0:
                    self.cycle_times.append(cycle)
            self.last_touch_time = ev.time

        elif ev.kind.lower() == "lift":
            self.lift_count += 1
            if self.last_touch_time is not None and self.lift_count > 1:
                contact_time = ev.time - self.last_touch_time
                if contact_time > 0:
                    if cfg.min_contact_time > 0 and contact_time * 1000 < cfg.min_contact_time:
                        log.debug("contact_time %.1fms < min_contact_time %dms, merged to flight",
                                  contact_time * 1000, cfg.min_contact_time)
                        if self.air_times:
                            self.air_times[-1] += contact_time
                    else:
                        self.contact_times.append(contact_time)
            self.last_lift_time = ev.time

    def build_report(
        self, reason: str, export_frames: tuple, export_timestamps: tuple
    ) -> JumpTestReport:
        """Build the JumpTestReport from accumulated statistics."""
        air = _positive_values(self.air_times)
        contact = _positive_values(self.contact_times)
        cycle = _positive_values(self.cycle_times)

        heights = _jump_heights(air)
        cadence_values = _cadences(cycle)
        avg_air = _mean(air)
        avg_contact = _mean(contact)
        avg_cycle = _mean(cycle)

        return JumpTestReport(
            touch_count=self.touch_count,
            lift_count=self.lift_count,
            air_times=air,
            contact_times=contact,
            cycle_times=cycle,
            avg_jump_height=_mean(heights),
            max_jump_height=_max_or_zero(heights),
            avg_air_time=avg_air,
            max_air_time=_max_or_zero(air),
            avg_contact_time=avg_contact,
            avg_cadence=60.0 / avg_cycle if avg_cycle > 0 else None,
            finish_reason=reason,
            jump_heights=heights,
            cadences=cadence_values,
            min_jump_height=_min_or_zero(heights),
            std_jump_height=_population_std(heights),
            min_air_time=_min_or_zero(air),
            std_air_time=_population_std(air),
            min_contact_time=_min_or_zero(contact),
            max_contact_time=_max_or_zero(contact),
            std_contact_time=_population_std(contact),
            export_frames=export_frames,
            export_timestamps=export_timestamps,
        )
