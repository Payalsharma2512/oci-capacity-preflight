from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.capacity.models import Operation


class ServiceAdapter(ABC):
    service: str

    @abstractmethod
    def operation_from_payload(self, payload: dict[str, Any]) -> Operation:
        raise NotImplementedError

    @abstractmethod
    def limit_mapping(self) -> dict[str, dict[str, str]]:
        raise NotImplementedError

    def supports_limit(self, limit_name: str) -> bool:
        return limit_name in set(self.limit_mapping().get(self.service, {}).values())
