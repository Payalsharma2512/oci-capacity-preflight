from __future__ import annotations

import os
import json
from typing import Any

from src.adapters.base import ServiceAdapter
from src.capacity.models import ComputeShape, ComputeWorkloadIntent, Operation
from src.compute import ComputeShapeProvider, ShapeLimitResolver


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

    def describe_operations(self) -> list[dict[str, Any]]:
        return [
            {
                "operation": "create_instances",
                "display_name": "Create Compute Instances",
                "capability": "FULL_PREFLIGHT",
                "limits": ["shape-resolved core limit", "shape-resolved memory limit when available"],
                "unit": "ocpus/memory_gb",
                "coverage": "shape-aware OCPU and memory service limits plus applicable compartment quota",
                "monitor_only": ["physical host placement", "capacity reservations not explicitly requested"],
                "form": [
                    {"name": "region", "label": "Region", "type": "text", "default": "us-ashburn-1", "required": True},
                    {"name": "compartment_id", "label": "Compartment OCID", "type": "text", "required": True},
                    {"name": "availability_domain", "label": "Availability Domain", "type": "text", "required": True},
                    {"name": "shape", "label": "Shape", "type": "compute_shape", "required": True},
                    {"name": "instance_count", "label": "Number of instances", "type": "number", "default": 5, "min": 1, "required": True},
                    {"name": "ocpus_per_instance", "label": "OCPUs per instance", "type": "number", "default": 4, "min": 0, "step": 0.1},
                    {"name": "memory_gb_per_instance", "label": "Memory per instance GB", "type": "number", "default": 32, "min": 0, "step": 0.1},
                ],
            }
        ]

    def workload_from_payload(
        self,
        payload: dict[str, Any],
        shape_provider: ComputeShapeProvider,
        limit_resolver: ShapeLimitResolver,
    ) -> tuple[Operation, dict[str, dict[str, str]]]:
        intent = self.intent_from_payload(payload)
        shape = shape_provider.get_shape(intent.compartment_id, intent.shape, intent.availability_domain)
        requested_delta = self.requested_delta_for_shape(intent, shape)
        mapping = limit_resolver.resolve(shape, set(requested_delta))
        if self.metric not in mapping:
            raise ValueError(f"Capacity Preflight could not reliably map Compute shape {shape.name} to the applicable OCI service limit.")
        operation = Operation(
            service=self.service,
            resource_type="instance",
            region=intent.region,
            availability_domain=intent.availability_domain,
            compartment_id=intent.compartment_id,
            compartment_name=intent.compartment_name,
            requested_delta=requested_delta,
            metadata={
                "mode": "workload",
                "workload": {
                    "shape": shape.name,
                    "instance_count": intent.instance_count,
                    "ocpus_per_instance": requested_delta["ocpus"] / intent.instance_count,
                    "memory_gb_per_instance": requested_delta.get("memory_gb", 0) / intent.instance_count if requested_delta.get("memory_gb") is not None else None,
                    "total_ocpus": requested_delta["ocpus"],
                    "total_memory_gb": requested_delta.get("memory_gb"),
                    "is_flex": shape.is_flex,
                },
                "capacity_scope_note": "Service limit capacity was evaluated. This does not guarantee real-time physical host or shape availability.",
            },
        )
        return operation, {self.service: mapping}

    def intent_from_payload(self, payload: dict[str, Any]) -> ComputeWorkloadIntent:
        operation = payload.get("operation", payload)
        workload = operation.get("workload") or {}
        if not workload:
            raise ValueError("Compute workload preflight requires operation.workload.")
        count = int(workload.get("instance_count", 0))
        if count < 1:
            raise ValueError("Compute workload requires instance_count >= 1.")
        return ComputeWorkloadIntent(
            region=operation["region"],
            availability_domain=operation.get("availability_domain"),
            compartment_id=operation["compartment_id"],
            compartment_name=operation.get("compartment_name"),
            shape=workload["shape"],
            instance_count=count,
            ocpus_per_instance=self._optional_float(workload.get("ocpus_per_instance")),
            memory_gb_per_instance=self._optional_float(workload.get("memory_gb_per_instance")),
        )

    def requested_delta_for_shape(self, intent: ComputeWorkloadIntent, shape: ComputeShape) -> dict[str, float]:
        if shape.is_flex:
            if intent.ocpus_per_instance is None or intent.memory_gb_per_instance is None:
                raise ValueError(f"Flex shape {shape.name} requires OCPUs and memory per instance.")
            self._validate_flex_value(shape, "ocpus", intent.ocpus_per_instance)
            self._validate_flex_value(shape, "memory_gb", intent.memory_gb_per_instance)
            per_instance_ocpus = intent.ocpus_per_instance
            per_instance_memory = intent.memory_gb_per_instance
        else:
            if shape.ocpus is None:
                raise ValueError(f"Fixed shape {shape.name} did not include OCPU metadata from OCI.")
            per_instance_ocpus = shape.ocpus
            per_instance_memory = shape.memory_gb
        requested = {"ocpus": per_instance_ocpus * intent.instance_count}
        if per_instance_memory is not None:
            requested["memory_gb"] = per_instance_memory * intent.instance_count
        return requested

    def _validate_flex_value(self, shape: ComputeShape, metric: str, value: float) -> None:
        option_key = "ocpu_options" if metric == "ocpus" else "memory_options"
        options = (
            shape.raw.get(option_key)
            or shape.raw.get(f"_{option_key}")
            or shape.raw.get("shape_config_options", {}).get(option_key)
            or shape.raw.get("_shape_config_options", {}).get(option_key)
            or {}
        )
        options = self._normalize_options(options)
        minimum = self._option_value(options, "min", "minimum", "min_in_gbs", "min_in_g_bs")
        maximum = self._option_value(options, "max", "maximum", "max_in_gbs", "max_in_g_bs")
        if minimum is not None and value < minimum:
            raise ValueError(f"{shape.name} requires {metric} >= {minimum:g}.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{shape.name} requires {metric} <= {maximum:g}.")
        if value <= 0:
            raise ValueError(f"{metric} must be greater than zero.")

    def _option_value(self, options: Any, *names: str) -> float | None:
        for name in names:
            value = getattr(options, name, None) if not isinstance(options, dict) else options.get(name)
            if value is None and not isinstance(options, dict):
                value = getattr(options, f"_{name}", None)
            if value is None and isinstance(options, dict):
                value = options.get(f"_{name}")
            if value is not None:
                return float(value)
        return None

    def _normalize_options(self, options: Any) -> Any:
        if isinstance(options, str):
            try:
                return json.loads(options)
            except json.JSONDecodeError:
                return {}
        return options

    def _optional_float(self, value: Any) -> float | None:
        return None if value is None or value == "" else float(value)
