from __future__ import annotations

from typing import Any

from src.adapters.base import ServiceAdapter
from src.block_volume import BlockVolumeLimitResolver
from src.capacity.models import Operation


class BlockVolumeAdapter(ServiceAdapter):
    service = "block-storage"
    aliases = {"blockvolume", "block-volume", "block-storage"}

    def operation_from_payload(self, payload: dict[str, Any]) -> Operation:
        operation = payload.get("operation", payload)
        requested = operation.get("requested") or operation.get("requested_delta") or {}
        if "volume_count" not in requested or "storage_gb" not in requested:
            raise ValueError("Block Volume preflight requires requested.volume_count and requested.storage_gb.")
        return Operation(
            service=self.service,
            resource_type=operation.get("resource_type", "volume"),
            region=operation["region"],
            availability_domain=operation.get("availability_domain"),
            compartment_id=operation["compartment_id"],
            compartment_name=operation.get("compartment_name"),
            requested_delta={k: float(v) for k, v in requested.items()},
            metadata={
                "mode": "manual",
                "capacity_scope_note": "Service limit and quota capacity was evaluated. This does not guarantee physical storage placement or downstream provisioning success.",
            },
        )

    def limit_mapping(self) -> dict[str, dict[str, str]]:
        return {self.service: {}}

    def describe_operations(self) -> list[dict[str, Any]]:
        return [
            {
                "operation": "create_volumes",
                "display_name": "Create Block Volumes",
                "capability": "FULL_PREFLIGHT",
                "limits": ["volume-count", "total-storage-gb"],
                "unit": "volume_count/storage_gb",
                "coverage": "volume count and total storage GB",
                "monitor_only": ["backup count", "replica storage unless replication is requested"],
                "form": [
                    {"name": "region", "label": "Region", "type": "text", "default": "us-ashburn-1", "required": True},
                    {"name": "compartment_id", "label": "Compartment OCID", "type": "text", "required": True},
                    {"name": "availability_domain", "label": "Availability Domain", "type": "text", "required": True},
                    {"name": "volume_count", "label": "Number of volumes", "type": "number", "default": 5, "min": 1, "required": True},
                    {"name": "size_gb_each", "label": "Size per volume GB", "type": "number", "default": 2048, "min": 1, "required": True},
                ],
            }
        ]

    def workload_from_payload(
        self,
        payload: dict[str, Any],
        limit_resolver: BlockVolumeLimitResolver,
    ) -> tuple[Operation, dict[str, dict[str, str]]]:
        operation = payload.get("operation", payload)
        workload = operation.get("workload") or {}
        count = int(workload.get("volume_count", 0))
        size_gb_each = float(workload.get("size_gb_each", 0))
        if count < 1:
            raise ValueError("Block Volume workload requires volume_count >= 1.")
        if size_gb_each <= 0:
            raise ValueError("Block Volume workload requires size_gb_each > 0.")

        requested_delta = {
            "volume_count": float(count),
            "storage_gb": count * size_gb_each,
        }
        if workload.get("replication_enabled"):
            requested_delta["replica_storage_gb"] = requested_delta["storage_gb"]

        mapping = limit_resolver.resolve(set(requested_delta))
        missing = sorted(set(requested_delta) - set(mapping))
        if missing:
            raise ValueError(f"Capacity Preflight could not reliably map Block Volume metrics to OCI service limits: {', '.join(missing)}.")

        operation_model = Operation(
            service=self.service,
            resource_type="volume",
            region=operation["region"],
            availability_domain=operation.get("availability_domain"),
            compartment_id=operation["compartment_id"],
            compartment_name=operation.get("compartment_name"),
            requested_delta=requested_delta,
            metadata={
                "mode": "workload",
                "workload": {
                    "resource": "Block Volume",
                    "volume_count": count,
                    "size_gb_each": size_gb_each,
                    "total_storage_gb": requested_delta["storage_gb"],
                    "total_storage_tb": requested_delta["storage_gb"] / 1024,
                    "replication_enabled": bool(workload.get("replication_enabled")),
                },
                "capacity_scope_note": "Service limit and quota capacity was evaluated. This does not guarantee physical storage placement or downstream provisioning success.",
            },
        )
        return operation_model, {self.service: mapping}
