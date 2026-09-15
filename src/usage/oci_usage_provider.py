from __future__ import annotations

from src.capacity.models import Operation


class ResourceAvailabilityUsageProvider:
    """Uses Limits GetResourceAvailability as the usage source where supported."""

    def __init__(self, limits_client, limit_mapping: dict[str, dict[str, str]]):
        self.client = limits_client
        self.limit_mapping = limit_mapping

    def current_usage(self, operation: Operation, metric: str) -> float:
        limit_name = self.limit_mapping.get(operation.service, {}).get(metric)
        if not limit_name:
            raise RuntimeError(f"No OCI limit mapping configured for {operation.service}.{metric}")
        kwargs = {}
        if operation.availability_domain:
            kwargs["availability_domain"] = operation.availability_domain
        availability = self.client.get_resource_availability(operation.service, limit_name, operation.compartment_id, **kwargs).data
        used = getattr(availability, "used", None)
        if used is None:
            raise RuntimeError(f"OCI resource availability did not include used value for {operation.service}.{metric}")
        return float(used)
