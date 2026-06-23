import random
from .base import Device


class PackagingLine(Device):
    def __init__(self, device_id: str):
        super().__init__(device_id, "Packaging")
        self._running = True
        self._speed = 1.5           # m/min; max 2.0
        self._total_produced = 0
        self._total_rejected = 0
        self._reject_rate = random.uniform(0.01, 0.04)
        self._uptime = 0.0
        self._elapsed = 0.0

        self._sync_tags()

    @property
    def _oee(self) -> float:
        if self._elapsed < 1.0:
            return 0.0
        availability = self._uptime / self._elapsed
        performance = self._speed / 2.0
        quality = 1.0 - self._reject_rate
        return round(availability * performance * quality * 100.0, 1)

    def tick(self, elapsed: float) -> None:
        self._elapsed += elapsed

        # Random short stoppages and restarts
        if self._running and random.random() < 0.001:
            self._running = False
        elif not self._running and random.random() < 0.05:
            self._running = True

        if self._running:
            self._uptime += elapsed
            self._speed = max(0.5, min(2.0, self._speed + random.gauss(0, 0.02)))
            units = max(0, int(self._speed * 60 * elapsed / 60))
            rejects = int(units * self._reject_rate)
            self._total_produced += units
            self._total_rejected += rejects
            throughput = round(self._speed * 60)
        else:
            throughput = 0

        self._set("Running", self._running, datatype="bool")
        self._set("ConveyorSpeed_m_min", round(self._speed, 2), "m/min")
        self._set("Throughput_units_hr", throughput, "units/hr", "int")
        self._set("TotalProduced", self._total_produced, "units", "int")
        self._set("RejectCount", self._total_rejected, "units", "int")
        self._set("OEE_pct", self._oee, "%")

    def _sync_tags(self) -> None:
        self._set("Running", self._running, datatype="bool")
        self._set("ConveyorSpeed_m_min", self._speed, "m/min")
        self._set("Throughput_units_hr", 0, "units/hr", "int")
        self._set("TotalProduced", 0, "units", "int")
        self._set("RejectCount", 0, "units", "int")
        self._set("OEE_pct", 0.0, "%")


def create_packaging_lines() -> list[Device]:
    return [PackagingLine("Packaging_Line_01")]
