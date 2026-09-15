from __future__ import annotations

import os
from typing import Any

from src.adapters.base import ServiceAdapter
from src.capacity.models import Operation


class ComputeAdapter(ServiceAdapter):
    service = "compute"
    metric = "ocpus"

    def __init__(self, ocpu_limit_name: str | None = None):
        self.ocpu_limit_name = ocpu_limit_name or os.getenv(
            "OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT",
            "standard-e4-core-count",
        )

    def operation_from_payload(self, payload: dict[str, Any]) -> Operation:
        operation = payload.get("operation", payload)
        requested = operation.get("requested") or operation.get("requested_delta") or {}
        if self.metric not in requested:
            raise ValueError("Compute preflight requires requested.ocpus.")
        return Operation(
            service=self.service,
            resource_type=operation.get("resource_type", "instance"),
            region=operation["region"],
            availability_domain=operation.get("availability_domain"),
            compartment_id=operation["compartment_id"],
            compartment_name=operation.get("compartment_name"),
            requested_delta={self.metric: float(requested[self.metric])},
        )

    def limit_mapping(self) -> dict[str, dict[str, str]]:
        return {self.service: {self.metric: self.ocpu_limit_name}}
