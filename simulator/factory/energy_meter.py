import math
import random
from .base import Device


class EnergyMeter(Device):
    def __init__(self, device_id: str, base_kw: float = 50.0):
        super().__init__(device_id, "Energy")
        self._phase = random.uniform(0, 2 * math.pi)
        self._base_kw = base_kw
        self._kwh = random.uniform(1000.0, 50000.0)  # pre-existing meter reading
        self._t = 0.0

        self._sync_tags(base_kw, 0.92, 400.0, 0.0)

    def tick(self, elapsed: float) -> None:
        self._t += elapsed

        kw = max(0.0, self._base_kw + 10.0 * math.sin(self._t * 0.02 + self._phase) + random.gauss(0, 2.0))
        voltage = 400.0 + random.gauss(0, 1.5)
        pf = max(0.7, min(1.0, 0.92 + random.gauss(0, 0.01)))
        current = (kw * 1000.0) / (voltage * math.sqrt(3) * pf) if pf > 0 else 0.0

        self._kwh += (kw / 3600.0) * elapsed

        self._sync_tags(kw, pf, voltage, current)

    def _sync_tags(self, kw: float, pf: float, voltage: float, current: float) -> None:
        self._set("ActivePower_kW", round(kw, 2), "kW")
        self._set("EnergyTotal_kWh", round(self._kwh, 3), "kWh")
        self._set("PowerFactor", round(pf, 3))
        self._set("Voltage_V", round(voltage, 1), "V")
        self._set("Current_A", round(current, 2), "A")


def create_energy_meters() -> list[Device]:
    return [
        EnergyMeter("Main_Meter", base_kw=150.0),
        EnergyMeter("Line_A_Meter", base_kw=65.0),
        EnergyMeter("Line_B_Meter", base_kw=55.0),
    ]
