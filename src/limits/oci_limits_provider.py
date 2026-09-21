from __future__ import annotations

from src.capacity.models import CapacitySnapshot, Operation
from src.capacity.providers import CapacityProvider


class OciLimitsProvider(CapacityProvider):
    """OCI Limits provider using current OCI Python SDK method names.

    Verified against Oracle OCI Python SDK docs: LimitsClient supports
    list_services(compartment_id), list_limit_definitions(compartment_id, ...),
    list_limit_values(compartment_id, service_name, ...), and
    get_resource_availability(service_name, limit_name, compartment_id, ...).
    """

    def __init__(self, limits_client, tenancy_compartment_id: str, limit_mapping: dict[str, dict[str, str]] | None = None):
        self.client = limits_client
        self.tenancy_compartment_id = tenancy_compartment_id
        self.limit_mapping = limit_mapping or {}

    def discover_constraints(self, operation: Operation) -> list[str]:
        definitions = self.client.list_limit_definitions(self.tenancy_compartment_id, service_name=operation.service).data
        return [definition.name for definition in definitions]

    def get_current_state(self, operation: Operation) -> list[CapacitySnapshot]:
        snapshots: list[CapacitySnapshot] = []
        metric_map = self.limit_mapping.get(operation.service, {})
        if not metric_map:
            return [CapacitySnapshot("SERVICE_LIMIT", operation.service, "unmapped-limit", operation.region, "unknown", None, None, None, reason=f"No OCI limit mapping configured for service {operation.service}.")]
        definitions = self._definition_by_name(operation.service)
        for metric, limit_name in metric_map.items():
            definition = definitions.get(limit_name)
            scope_type = str(getattr(definition, "scope_type", "") or "").upper()
            if scope_type.endswith("AD") and not operation.availability_domain:
                snapshots.append(CapacitySnapshot("SERVICE_LIMIT", operation.service, limit_name, operation.region, metric, None, None, None, reason=f"{operation.service}.{limit_name} is AD-scoped; availability_domain is required."))
                continue
            kwargs = {}
            if operation.availability_domain and scope_type.endswith("AD"):
                kwargs["availability_domain"] = operation.availability_domain
            try:
                availability = self.client.get_resource_availability(
                    operation.service,
                    limit_name,
                    operation.compartment_id,
                    **kwargs,
                ).data
                available = getattr(availability, "available", None)
                used = getattr(availability, "used", None)
                maximum = None if available is None or used is None else available + used
                scope = operation.availability_domain if scope_type.endswith("AD") else operation.region
                snapshots.append(CapacitySnapshot("SERVICE_LIMIT", operation.service, limit_name, scope, metric, used, maximum, available))
            except Exception as exc:
                snapshots.append(CapacitySnapshot("SERVICE_LIMIT", operation.service, limit_name, operation.region, metric, None, None, None, reason=f"Limit availability data could not be retrieved: {exc}"))
        return snapshots

    def remediation(self, snapshot: CapacitySnapshot) -> dict[str, str]:
        return {"action": "REQUEST_LIMIT_INCREASE", "reason": "Projected usage exceeds current service limit."}

    def list_all_limit_values(self, service_name: str):
        items = []
        page = None
        while True:
            response = self.client.list_limit_values(self.tenancy_compartment_id, service_name, page=page)
            items.extend(response.data)
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return items

    def _definition_by_name(self, service_name: str):
        items = []
        page = None
        while True:
            try:
                response = self.client.list_limit_definitions(self.tenancy_compartment_id, service_name=service_name, page=page)
            except Exception:
                return {}
            data = getattr(response, "data", response)
            items.extend(data if isinstance(data, list) else [data])
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return {getattr(item, "name", None): item for item in items if getattr(item, "name", None)}
