from __future__ import annotations

from src.adapters.base import ServiceAdapter
from src.adapters.block_volume import BlockVolumeAdapter
from src.adapters.compute import ComputeAdapter
from src.adapters.network_load_balancer import NetworkLoadBalancerAdapter


class ServiceAdapterRegistry:
    def __init__(self, adapters: list[ServiceAdapter] | None = None):
        self._adapters = {}
        self._aliases = {}
        for adapter in (adapters or [ComputeAdapter(), BlockVolumeAdapter(), NetworkLoadBalancerAdapter()]):
            self._adapters[adapter.service] = adapter
            for alias in getattr(adapter, "aliases", {adapter.service}):
                self._aliases[alias.lower()] = adapter.service

    def get(self, service: str) -> ServiceAdapter | None:
        canonical = self._aliases.get(service.lower(), service.lower())
        return self._adapters.get(canonical)

    def services(self) -> list[str]:
        return sorted(self._adapters)

    def describe_operations(self) -> list[dict]:
        operations = []
        for adapter in self._adapters.values():
            for operation in adapter.describe_operations():
                operations.append({"service": adapter.service, **operation})
        return operations

    def merged_limit_mapping(self) -> dict[str, dict[str, str]]:
        mapping: dict[str, dict[str, str]] = {}
        for adapter in self._adapters.values():
            mapping.update(adapter.limit_mapping())
        return mapping

    def supports_limit(self, service: str, limit_name: str) -> bool:
        adapter = self.get(service)
        return bool(adapter and adapter.supports_limit(limit_name))
