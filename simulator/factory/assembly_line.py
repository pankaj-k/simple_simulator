import random
from enum import Enum
from .base import Device


class MachineState(str, Enum):
    RUNNING = "RUNNING"
    IDLE = "IDLE"
    FAULT = "FAULT"


class Machine(Device):
    _FAULT_PROB = 0.002  # probability per tick of a random fault

    def __init__(self, device_id: str):
        super().__init__(device_id, "Assembly")
        self._state = MachineState.RUNNING
        self._state_timer = 0.0
        self._part_count = 0
        self._cycle_time = random.gauss(45.0, 2.0)
        self._cycle_acc = 0.0
        self._tool_wear = random.uniform(10.0, 40.0)

        self._sync_tags()

    def tick(self, elapsed: float) -> None:
        self._state_timer += elapsed

        if self._state == MachineState.RUNNING:
            self._cycle_acc += elapsed
            if self._cycle_acc >= self._cycle_time:
                self._part_count += 1
                self._cycle_acc = 0.0
                self._cycle_time = random.gauss(45.0, 2.0)
                self._tool_wear = min(100.0, self._tool_wear + random.uniform(0.1, 0.3))

            if self._tool_wear >= 95.0:
                self._state = MachineState.IDLE
                self._state_timer = 0.0
                self._tool_wear = 0.0  # maintenance resets wear

            elif random.random() < self._FAULT_PROB:
                self._state = MachineState.FAULT
                self._state_timer = 0.0

        elif self._state == MachineState.FAULT:
            if self._state_timer >= 30.0:
                self._state = MachineState.IDLE
                self._state_timer = 0.0

        elif self._state == MachineState.IDLE:
            if self._state_timer >= 10.0:
                self._state = MachineState.RUNNING
                self._state_timer = 0.0

        self._sync_tags()

    @property
    def is_running(self) -> bool:
        return self._state == MachineState.RUNNING

    def _sync_tags(self) -> None:
        self._set("State", self._state.value, datatype="string")
        self._set("PartCount", self._part_count, "parts", "int")
        self._set("CycleTime_sec", round(self._cycle_time, 1), "s")
        self._set("ToolWear_pct", round(self._tool_wear, 1), "%")
        self._set("Alarm", self._state == MachineState.FAULT, datatype="bool")


def create_assembly_line() -> list[Device]:
    return [Machine("CNC_01"), Machine("CNC_02"), Machine("Robot_Arm_01")]
