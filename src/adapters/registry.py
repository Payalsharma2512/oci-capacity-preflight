from __future__ import annotations

from src.adapters.base import ServiceAdapter
from src.adapters.compute import ComputeAdapter


class ServiceAdapterRegistry:
    def __init__(self, adapters: list[ServiceAdapter] | None = None):
        self._adapters = {adapter.service: adapter for adapter in (adapters or [ComputeAdapter()])}

    def get(self, service: str) -> ServiceAdapter | None:
        return self._adapters.get(service.lower())

    def services(self) -> list[str]:
        return sorted(self._adapters)

    def merged_limit_mapping(self) -> dict[str, dict[str, str]]:
        mapping: dict[str, dict[str, str]] = {}
        for adapter in self._adapters.values():
            mapping.update(adapter.limit_mapping())
        return mapping

    def supports_limit(self, service: str, limit_name: str) -> bool:
        adapter = self.get(service)
        return bool(adapter and adapter.supports_limit(limit_name))
