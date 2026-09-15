from __future__ import annotations

from typing import Any

from src.adapters.registry import ServiceAdapterRegistry
from src.capacity.models import CapabilityLevel, LimitCapability


class OciLimitDiscovery:
    def __init__(self, limits_client, tenancy_compartment_id: str, adapter_registry: ServiceAdapterRegistry | None = None):
        self.client = limits_client
        self.tenancy_compartment_id = tenancy_compartment_id
        self.adapter_registry = adapter_registry or ServiceAdapterRegistry()

    def list_services(self) -> list[dict[str, str | None]]:
        response = self.client.list_services(self.tenancy_compartment_id)
        return [
            {
                "name": getattr(service, "name", None),
                "description": getattr(service, "description", None),
            }
            for service in self._items(response)
        ]

    def list_limits(self, service_name: str, compartment_id: str | None = None, availability_domain: str | None = None) -> list[LimitCapability]:
        definitions = self._list_limit_definitions(service_name)
        values = self._limit_values_by_name(service_name)
        return [
            self._capability_from_definition(
                service_name,
                definition,
                values.get(getattr(definition, "name", "")),
                compartment_id,
                availability_domain,
            )
            for definition in definitions
        ]

    def capacity_matrix(self, compartment_id: str | None = None, availability_domain: str | None = None) -> list[LimitCapability]:
        matrix: list[LimitCapability] = []
        for service in self.list_services():
            name = service.get("name")
            if not name:
                continue
            try:
                matrix.extend(self.list_limits(name, compartment_id, availability_domain))
            except Exception as exc:
                matrix.append(
                    LimitCapability(
                        service=name,
                        service_description=service.get("description"),
                        limit_name="discovery-error",
                        scope_type=None,
                        limit_value=None,
                        current_usage=None,
                        available=None,
                        capability=CapabilityLevel.UNSUPPORTED,
                        reason=f"Could not discover limits for {name}: {exc}",
                    )
                )
        return matrix

    def _list_limit_definitions(self, service_name: str) -> list[Any]:
        response = self.client.list_limit_definitions(self.tenancy_compartment_id, service_name=service_name)
        return self._items(response)

    def _limit_values_by_name(self, service_name: str) -> dict[str, Any]:
        values = {}
        page = None
        while True:
            response = self.client.list_limit_values(self.tenancy_compartment_id, service_name, page=page)
            for item in self._items(response):
                name = getattr(item, "name", None)
                if name:
                    values[name] = item
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return values

    def _capability_from_definition(
        self,
        service_name: str,
        definition: Any,
        limit_value: Any,
        compartment_id: str | None,
        availability_domain: str | None,
    ) -> LimitCapability:
        limit_name = getattr(definition, "name", "")
        service_description = getattr(definition, "description", None)
        scope_type = getattr(definition, "scope_type", None)
        numeric_limit = self._number(getattr(limit_value, "value", None))
        increase = getattr(definition, "is_eligible_for_limit_increase", None)
        capability = CapabilityLevel.DISCOVERY_ONLY
        current_usage = None
        available = None
        reason = None

        if compartment_id:
            try:
                kwargs = {}
                if availability_domain:
                    kwargs["availability_domain"] = availability_domain
                availability_data = self.client.get_resource_availability(service_name, limit_name, compartment_id, **kwargs).data
                current_usage = self._number(getattr(availability_data, "used", None))
                available = self._number(getattr(availability_data, "available", None))
                if self.adapter_registry.supports_limit(service_name, limit_name):
                    capability = CapabilityLevel.FULL_PREFLIGHT
                else:
                    capability = CapabilityLevel.MONITOR_ONLY
                    reason = "Usage and availability are visible, but no verified operation adapter exists for this limit."
            except Exception as exc:
                if self.adapter_registry.supports_limit(service_name, limit_name):
                    capability = CapabilityLevel.UNSUPPORTED
                    reason = f"Adapter exists, but resource availability could not be read: {exc}"
                else:
                    reason = f"Limit is discoverable, but resource availability was not available: {exc}"
        elif self.adapter_registry.supports_limit(service_name, limit_name):
            capability = CapabilityLevel.DISCOVERY_ONLY
            reason = "Adapter exists, but compartment input is required to verify current availability."

        return LimitCapability(
            service=service_name,
            service_description=service_description,
            limit_name=limit_name,
            scope_type=scope_type,
            limit_value=numeric_limit,
            current_usage=current_usage,
            available=available,
            capability=capability,
            unit=None,
            reason=reason,
            is_eligible_for_increase=increase,
        )

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
