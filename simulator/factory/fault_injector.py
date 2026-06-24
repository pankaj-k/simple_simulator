import logging
import random

logger = logging.getLogger(__name__)


class FaultInjector:
    """
    Randomly degrades individual tag quality to Bad and later recovers it.

    Call inject(elapsed) once per tick after all device.tick() calls.
    It mutates tag.quality in place; connectors read that field when writing.

    Probability math: with default fault_prob=0.001 and a 2s tick,
    each tag has a 0.2% chance of going Bad per tick.  Across ~40 tags
    you can expect the first fault within roughly 25 seconds of starting.
    """

    def __init__(
        self,
        devices,
        fault_prob: float = 0.001,
        min_bad_seconds: float = 2.0,
        max_bad_seconds: float = 120.0,
    ):
        self._devices = devices
        self._fault_prob = fault_prob
        self._min_bad = min_bad_seconds
        self._max_bad = max_bad_seconds
        self._remaining: dict[tuple, float] = {}  # (device_id, tag_name) → seconds left

    def inject(self, elapsed: float) -> None:
        for device in self._devices:
            for tag_name, tag in device.get_tags().items():
                key = (device.device_id, tag_name)
                if key in self._remaining:
                    self._remaining[key] -= elapsed
                    if self._remaining[key] <= 0:
                        del self._remaining[key]
                        tag.quality = "Good"
                        logger.info(
                            "Quality RECOVERED  %-20s  %s",
                            device.device_id, tag_name,
                        )
                elif random.random() < self._fault_prob * elapsed:
                    duration = random.uniform(self._min_bad, self._max_bad)
                    self._remaining[key] = duration
                    tag.quality = "Bad"
                    logger.warning(
                        "Quality FAULT      %-20s  %-30s  (%.0fs)",
                        device.device_id, tag_name, duration,
                    )
