from __future__ import annotations

import re
from typing import Any

from src.adapters.registry import ServiceAdapterRegistry
from src.block_volume import BlockVolumeLimitResolver
from src.capacity.models import CapabilityLevel, LimitCapability
from src.compute import ComputeShapeProvider, ShapeLimitResolver
from src.network_load_balancer import NetworkLoadBalancerLimitResolver


class OciLimitDiscovery:
    def __init__(
        self,
        limits_client,
        tenancy_compartment_id: str,
        adapter_registry: ServiceAdapterRegistry | None = None,
        quotas_client=None,
        compute_client=None,
    ):
        self.client = limits_client
        self.quotas_client = quotas_client
        self.compute_client = compute_client
        self.tenancy_compartment_id = tenancy_compartment_id
        self.adapter_registry = adapter_registry or ServiceAdapterRegistry()

    def list_services(self) -> list[dict[str, str | None]]:
        return [
            {
                "name": getattr(service, "name", None),
                "description": getattr(service, "description", None),
            }
            for service in self._paged(lambda page: self.client.list_services(self.tenancy_compartment_id, page=page))
        ]

    def list_limits(
        self,
        service_name: str,
        compartment_id: str | None = None,
        availability_domain: str | None = None,
        region: str | None = None,
        service_description: str | None = None,
    ) -> list[LimitCapability]:
        definitions = self._list_limit_definitions(service_name)
        values = self._limit_values_by_name(service_name)
        quota_index, quota_readable, quota_error = self._quota_index()
        verified_full_preflight_limits = self._verified_full_preflight_limits(service_name, compartment_id, availability_domain)
        return [
            self._capability_from_definition(
                service_name,
                definition,
                values.get(getattr(definition, "name", "")),
                compartment_id,
                availability_domain,
                region,
                service_description,
                verified_full_preflight_limits,
                quota_index,
                quota_readable,
                quota_error,
            )
            for definition in definitions
        ]

    def capacity_matrix(
        self,
        compartment_id: str | None = None,
        availability_domain: str | None = None,
        region: str | None = None,
    ) -> list[LimitCapability]:
        matrix: list[LimitCapability] = []
        for service in self.list_services():
            name = service.get("name")
            if not name:
                continue
            try:
                matrix.extend(
                    self.list_limits(
                        name,
                        compartment_id,
                        availability_domain,
                        region,
                        service_description=service.get("description"),
                    )
                )
            except Exception:
                # Do not manufacture a pseudo-limit such as "discovery-error".
                # Only OCI-discovered limit definitions belong in the inventory.
                continue
        return matrix

    def _list_limit_definitions(self, service_name: str) -> list[Any]:
        return self._paged(lambda page: self.client.list_limit_definitions(self.tenancy_compartment_id, service_name=service_name, page=page))

    def _limit_values_by_name(self, service_name: str) -> dict[str, Any]:
        values = {}
        for item in self._paged(lambda page: self.client.list_limit_values(self.tenancy_compartment_id, service_name, page=page)):
            name = getattr(item, "name", None)
            if name:
                values[name] = item
        return values

    def _capability_from_definition(
        self,
        service_name: str,
        definition: Any,
        limit_value: Any,
        compartment_id: str | None,
        availability_domain: str | None,
        region: str | None,
        service_description: str | None,
        verified_full_preflight_limits: set[tuple[str, str]],
        quota_index: dict[tuple[str, str], list[str]],
        quota_readable: bool | None,
        quota_error: str | None,
    ) -> LimitCapability:
        limit_name = getattr(definition, "name", "")
        limit_description = getattr(definition, "description", None)
        scope_type = getattr(definition, "scope_type", None)
        numeric_limit = self._number(getattr(limit_value, "value", None))
        increase = getattr(definition, "is_eligible_for_limit_increase", None)
        capability = CapabilityLevel.DISCOVERY_ONLY
        current_usage = None
        available = None
        reason = None
        api_limitation = None
        resource_availability_supported = None

        normalized_service = self._normalize_quota_service(service_name)
        quota_statements = quota_index.get((normalized_service, limit_name), [])
        is_full_preflight_supported = self.adapter_registry.supports_limit(service_name, limit_name) or (normalized_service, limit_name) in verified_full_preflight_limits

        if compartment_id:
            try:
                kwargs = {}
                if availability_domain and self._is_ad_scope(scope_type):
                    kwargs["availability_domain"] = availability_domain
                availability_data = self.client.get_resource_availability(service_name, limit_name, compartment_id, **kwargs).data
                current_usage = self._number(getattr(availability_data, "used", None))
                available = self._number(getattr(availability_data, "available", None))
                resource_availability_supported = current_usage is not None or available is not None
                if is_full_preflight_supported:
                    capability = CapabilityLevel.FULL_PREFLIGHT
                else:
                    capability = CapabilityLevel.MONITOR_ONLY
                    reason = "Usage and availability are visible, but no verified operation adapter exists for this limit."
            except Exception as exc:
                resource_availability_supported = False
                api_limitation = str(exc)
                if is_full_preflight_supported:
                    capability = CapabilityLevel.UNSUPPORTED
                    reason = f"Adapter exists, but resource availability could not be read: {exc}"
                else:
                    reason = f"Limit is discoverable, but resource availability was not available: {exc}"
        elif is_full_preflight_supported:
            capability = CapabilityLevel.DISCOVERY_ONLY
            reason = "Adapter exists, but compartment input is required to verify current availability."

        if quota_error and quota_readable is False:
            api_limitation = f"{api_limitation}; quota discovery failed: {quota_error}" if api_limitation else f"quota discovery failed: {quota_error}"

        maximum = self._maximum(current_usage, available, numeric_limit)
        utilization = None if current_usage is None or maximum in {None, 0} else round(current_usage / maximum, 4)
        return LimitCapability(
            service=service_name,
            service_description=service_description,
            limit_name=limit_name,
            limit_description=limit_description,
            scope_type=scope_type,
            limit_value=maximum,
            current_usage=current_usage,
            available=available,
            capability=capability,
            unit=self._unit_for_limit(limit_name, limit_description),
            reason=reason,
            is_eligible_for_increase=increase,
            region=region,
            availability_domain=availability_domain,
            resource_availability_supported=resource_availability_supported,
            quota_statements=quota_statements,
            quota_readable=quota_readable,
            utilization=utilization,
            risk_state=self._risk_state(utilization),
            api_limitation=api_limitation,
        )

    def _quota_index(self) -> tuple[dict[tuple[str, str], list[str]], bool | None, str | None]:
        if not self.quotas_client:
            return {}, None, None
        index: dict[tuple[str, str], list[str]] = {}
        try:
            for quota in self._paged(lambda page: self.quotas_client.list_quotas(self.tenancy_compartment_id, page=page, lifecycle_state="ACTIVE")):
                quota_id = getattr(quota, "id", None)
                full = self.quotas_client.get_quota(quota_id).data if quota_id and not getattr(quota, "statements", None) else quota
                for statement in getattr(full, "statements", []) or []:
                    parsed = self._parse_quota_statement(statement)
                    if parsed:
                        index.setdefault((parsed["service"], parsed["limit"]), []).append(statement)
            return index, True, None
        except Exception as exc:
            return index, False, str(exc)

    def _parse_quota_statement(self, statement: str) -> dict[str, str] | None:
        match = re.search(r"set\s+(?P<service>\S+)\s+quota\s+(?P<limit>\S+)\s+to\s+(?P<value>\d+(?:\.\d+)?)", statement, re.IGNORECASE)
        if not match:
            return None
        return {
            "service": self._normalize_quota_service(match.group("service")),
            "limit": match.group("limit"),
            "value": match.group("value"),
        }

    def _normalize_quota_service(self, service_name: str) -> str:
        lower = service_name.lower()
        if lower in {"compute-core", "compute-memory", "compute-gpu"}:
            return "compute"
        return lower

    def _verified_full_preflight_limits(
        self,
        service_name: str,
        compartment_id: str | None,
        availability_domain: str | None,
    ) -> set[tuple[str, str]]:
        if service_name.lower() != "compute" or not self.compute_client or not compartment_id:
            if service_name.lower() == "block-storage":
                return self._verified_block_volume_limits()
            if service_name.lower() == "network-load-balancer-api":
                return self._verified_network_load_balancer_limits()
            return set()
        verified: set[tuple[str, str]] = set()
        shape_provider = ComputeShapeProvider(self.compute_client)
        resolver = ShapeLimitResolver(self.client, self.tenancy_compartment_id)
        try:
            shapes = shape_provider.list_shapes(compartment_id, availability_domain)
        except Exception:
            return set()
        for shape in shapes:
            try:
                for limit_name in resolver.resolve(shape, {"ocpus", "memory_gb"}).values():
                    verified.add(("compute", limit_name))
            except Exception:
                continue
        return verified

    def _verified_block_volume_limits(self) -> set[tuple[str, str]]:
        try:
            mapping = BlockVolumeLimitResolver(self.client, self.tenancy_compartment_id).resolve({"volume_count", "storage_gb"})
        except Exception:
            return set()
        return {("block-storage", limit_name) for limit_name in mapping.values()}

    def _verified_network_load_balancer_limits(self) -> set[tuple[str, str]]:
        try:
            mapping = NetworkLoadBalancerLimitResolver(self.client, self.tenancy_compartment_id).resolve({"nlb_count"})
        except Exception:
            return set()
        return {("network-load-balancer-api", limit_name) for limit_name in mapping.values()}

    def _paged(self, fetch):
        items = []
        page = None
        while True:
            response = fetch(page)
            items.extend(self._items(response))
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return items

    def _items(self, response: Any) -> list[Any]:
        data = getattr(response, "data", response)
        return data if isinstance(data, list) else [data]

    def _number(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _maximum(self, current_usage: float | None, available: float | None, fallback: float | None) -> float | None:
        if current_usage is not None and available is not None:
            return current_usage + available
        return fallback

    def _is_ad_scope(self, scope_type: Any) -> bool:
        return str(scope_type or "").upper().endswith("AD")

    def _risk_state(self, utilization: float | None) -> str:
        if utilization is None:
            return "UNKNOWN"
        if utilization >= 1:
            return "EXHAUSTED"
        if utilization >= 0.9:
            return "CRITICAL"
        if utilization >= 0.8:
            return "WARNING"
        if utilization >= 0.7:
            return "WATCH"
        return "HEALTHY"

    def _unit_for_limit(self, limit_name: str, description: str | None) -> str | None:
        text = f"{limit_name} {description or ''}".lower()
        if "memory" in text:
            return "memory_gb"
        if "core" in text or "ocpu" in text:
            return "ocpus"
        if "count" in text:
            return "count"
        return None
