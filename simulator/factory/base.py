from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Tag:
    name: str
    value: Any
    unit: str = ""
    datatype: str = "float"  # float | int | bool | string


class Device(ABC):
    def __init__(self, device_id: str, area: str):
        self.device_id = device_id
        self.area = area
        self._tags: dict[str, Tag] = {}

    @abstractmethod
    def tick(self, elapsed: float) -> None:
        """Advance simulation by elapsed seconds."""

    def get_tags(self) -> dict[str, Tag]:
        return self._tags

    def _set(self, name: str, value: Any, unit: str = "", datatype: str = "float") -> None:
        if name in self._tags:
            self._tags[name].value = value
        else:
            self._tags[name] = Tag(name, value, unit, datatype)
