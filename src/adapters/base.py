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

    def describe_operations(self) -> list[dict[str, Any]]:
        return []

    def validate_request(self, payload: dict[str, Any]) -> None:
        return None

    def calculate_capacity_impact(self, payload: dict[str, Any]) -> dict[str, float]:
        return Operation.from_dict(payload).requested_delta

    def resolve_constraints(self, *_args, **_kwargs) -> dict[str, dict[str, str]]:
        return self.limit_mapping()

    def get_remediation(self, limit_name: str) -> dict[str, str]:
        return {"action": "REVIEW_CAPACITY", "reason": f"Review capacity for {self.service}.{limit_name}."}

    def supports_limit(self, limit_name: str) -> bool:
        return limit_name in set(self.limit_mapping().get(self.service, {}).values())
