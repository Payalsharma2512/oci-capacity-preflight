from __future__ import annotations

from src.capacity.models import Operation


class StaticUsageProvider:
    def __init__(self, usage: dict[tuple[str, str, str], float]):
        self.usage = usage

    def current_usage(self, operation: Operation, metric: str) -> float:
        return self.usage.get((operation.service, operation.compartment_id, metric), 0.0)


class OciUsageProvider:
    """Extension placeholder for service-specific usage APIs and Monitoring queries."""

    def current_usage(self, operation: Operation, metric: str) -> float:
        raise NotImplementedError("Wire a service-specific usage provider for this metric.")
