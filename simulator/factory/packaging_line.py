import random
from .base import Device


class PackagingLine(Device):
    def __init__(self, device_id: str, feeder_machines=None):
        super().__init__(device_id, "Packaging")
        self._feeders = feeder_machines or []
        self._running = True
        self._speed = 1.5           # m/min; max 2.0
        self._total_produced = 0
        self._total_rejected = 0
        self._base_reject_rate = random.uniform(0.01, 0.04)
        self._uptime = 0.0
        self._elapsed = 0.0

        self._sync_tags()

    def _supply_factor(self) -> float:
        """Fraction of feeder machines currently running. 1.0 if no feeders configured."""
        if not self._feeders:
            return 1.0
        return sum(1 for m in self._feeders if m.is_running) / len(self._feeders)

    @property
    def _oee(self) -> float:
        if self._elapsed < 1.0:
            return 0.0
        availability = self._uptime / self._elapsed
        performance = self._speed / 2.0
        quality = 1.0 - self._base_reject_rate
        return round(availability * performance * quality * 100.0, 1)

    def tick(self, elapsed: float) -> None:
        self._elapsed += elapsed
        supply = self._supply_factor()

        if supply == 0.0:
            # No parts coming in — forced stop regardless of line state
            self._running = False
        elif self._running and random.random() < 0.001:
            # Random micro-stoppage
            self._running = False
        elif not self._running and random.random() < 0.05 * supply:
            # Recovery is harder with low supply — fewer parts to restart with
            self._running = True

        # Reduced supply means rushed/incomplete parts → higher reject rate
        effective_reject = min(0.30, self._base_reject_rate + (1.0 - supply) * 0.10)

        if self._running:
            self._uptime += elapsed
            self._speed = max(0.5, min(2.0, self._speed + random.gauss(0, 0.02)))
            units = max(0, int(self._speed * 60 * elapsed / 60))
            rejects = int(units * effective_reject)
            self._total_produced += units
            self._total_rejected += rejects
            throughput = round(self._speed * 60)
        else:
            throughput = 0

        self._set("Running",               self._running,         datatype="bool")
        self._set("ConveyorSpeed_m_min",   round(self._speed, 2), "m/min")
        self._set("Throughput_units_hr",   throughput,            "units/hr", "int")
        self._set("TotalProduced",         self._total_produced,  "units",    "int")
        self._set("RejectCount",           self._total_rejected,  "units",    "int")
        self._set("OEE_pct",               self._oee,             "%")
        self._set("SupplyFactor_pct",      round(supply * 100),   "%",        "int")

    def _sync_tags(self) -> None:
        self._set("Running",             self._running, datatype="bool")
        self._set("ConveyorSpeed_m_min", self._speed,   "m/min")
        self._set("Throughput_units_hr", 0,             "units/hr", "int")
        self._set("TotalProduced",       0,             "units",    "int")
        self._set("RejectCount",         0,             "units",    "int")
        self._set("OEE_pct",             0.0,           "%")
        self._set("SupplyFactor_pct",    100,           "%",        "int")


def create_packaging_lines(feeder_machines=None) -> list[Device]:
    return [PackagingLine("Packaging_Line_01", feeder_machines=feeder_machines)]
