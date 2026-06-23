import math
import random
from .base import Device


class ProcessTank(Device):
    def __init__(self, device_id: str, base_temp: float = 75.0, base_pressure: float = 2.5):
        super().__init__(device_id, "Process")
        self._phase = random.uniform(0, 2 * math.pi)
        self._base_temp = base_temp
        self._base_pressure = base_pressure
        self._level = random.uniform(40.0, 80.0)
        self._flow_rate = random.uniform(100.0, 200.0)
        self._t = 0.0

        self._sync_tags()

    def tick(self, elapsed: float) -> None:
        self._t += elapsed

        temp = (
            self._base_temp
            + 5.0 * math.sin(self._t * 0.05 + self._phase)
            + random.gauss(0, 0.2)
        )
        pressure = (
            self._base_pressure
            + 0.3 * math.sin(self._t * 0.065 + self._phase)
            + random.gauss(0, 0.02)
        )
        pressure = max(0.0, pressure)

        self._flow_rate = max(50.0, self._flow_rate + random.gauss(0, 3.0))
        drain = (self._flow_rate / 3600.0) * elapsed
        self._level = max(10.0, min(95.0, self._level - drain + random.gauss(0, 0.05)))
        if self._level < 20.0:
            self._level += 5.0  # inlet valve opens

        heater_on = temp < self._base_temp

        self._set("Temperature_C", round(temp, 2), "°C")
        self._set("Pressure_bar", round(pressure, 3), "bar")
        self._set("Level_pct", round(self._level, 1), "%")
        self._set("FlowRate_L_min", round(self._flow_rate, 1), "L/min")
        self._set("HeaterOn", heater_on, datatype="bool")

    def _sync_tags(self) -> None:
        self._set("Temperature_C", self._base_temp, "°C")
        self._set("Pressure_bar", self._base_pressure, "bar")
        self._set("Level_pct", round(self._level, 1), "%")
        self._set("FlowRate_L_min", round(self._flow_rate, 1), "L/min")
        self._set("HeaterOn", True, datatype="bool")


def create_process_tanks() -> list[Device]:
    return [
        ProcessTank("Reactor_Tank_01", base_temp=82.0, base_pressure=3.1),
        ProcessTank("Reactor_Tank_02", base_temp=65.0, base_pressure=1.8),
    ]
