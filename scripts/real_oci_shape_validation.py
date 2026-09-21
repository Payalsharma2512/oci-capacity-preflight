from __future__ import annotations

import json
import os
from typing import Any

from src.adapters import ComputeAdapter
from src.capacity.engine import CapacityDecisionEngine
from src.compute import ComputeShapeProvider, ShapeLimitResolver
from src.limits.oci_limits_provider import OciLimitsProvider
from src.oci_auth import build_oci_clients
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def result_summary(result) -> dict[str, Any]:
    return {
        "decision": result.decision.value,
        "effective_available_capacity": result.effective_available_capacity,
        "primary_blocking_constraint": result.primary_blocking_constraint,
        "requested_delta": result.operation.requested_delta,
        "metadata": result.operation.metadata,
        "checks": [check.to_dict() for check in result.checks],
        "unknown_reasons": result.unknown_reasons,
        "recommendations": result.recommendations,
    }


def run_preflight(clients, tenancy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    adapter = ComputeAdapter()
    operation, limit_mapping = adapter.workload_from_payload(
        payload,
        ComputeShapeProvider(clients.compute_client),
        ShapeLimitResolver(clients.limits_client, tenancy_id),
    )
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    engine = CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])
    return {"limit_mapping": limit_mapping, "result": result_summary(engine.preflight(operation))}


def run_manual(clients, tenancy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    adapter = ComputeAdapter(os.getenv("OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT"))
    operation = adapter.operation_from_payload(payload)
    limit_mapping = adapter.limit_mapping()
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    engine = CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])
    return {"limit_mapping": limit_mapping, "result": result_summary(engine.preflight(operation))}


def try_case(name: str, func, *args, **kwargs) -> dict[str, Any]:
    try:
        return {"name": name, "ok": True, "data": func(*args, **kwargs)}
    except Exception as exc:
        return {"name": name, "ok": False, "error": str(exc)}


def main() -> int:
    tenancy_id = env("OCI_TENANCY_OCID")
    compartment_id = env("TARGET_COMPARTMENT_OCID")
    region = env("TARGET_REGION", "us-ashburn-1")
    quota_region = env("OCI_CAPACITY_PREFLIGHT_QUOTA_REGION", region)
    availability_domain = env("AVAILABILITY_DOMAIN")
    clients = build_oci_clients(
        auth="instance_principal",
        region=region,
        quota_region=quota_region,
        tenancy_id=tenancy_id,
    )

    shape_provider = ComputeShapeProvider(clients.compute_client)
    shapes = shape_provider.list_shapes(compartment_id, availability_domain)
    shape_names = [shape.name for shape in shapes]
    flex_shape = os.getenv("VALIDATION_FLEX_SHAPE", "VM.Standard.E5.Flex")
    fixed_shape = os.getenv("VALIDATION_FIXED_SHAPE") or next(
        (shape.name for shape in shapes if shape.name and not shape.is_flex and shape.ocpus and shape.memory_gb),
        None,
    )

    definitions = []
    page = None
    while True:
        response = clients.limits_client.list_limit_definitions(tenancy_id, service_name="compute", page=page)
        definitions.extend(response.data)
        page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
        if not page:
            break
    compute_definitions = [
        {
            "name": getattr(item, "name", None),
            "description": getattr(item, "description", None),
            "scope_type": getattr(item, "scope_type", None),
            "is_eligible_for_limit_increase": getattr(item, "is_eligible_for_limit_increase", None),
        }
        for item in definitions
    ]

    flex_payload = {
        "service": "compute",
        "operation": {
            "operation": "create_instances",
            "resource_type": "instance",
            "region": region,
            "availability_domain": availability_domain,
            "compartment_id": compartment_id,
            "compartment_name": "Production",
            "workload": {
                "shape": flex_shape,
                "instance_count": 5,
                "ocpus_per_instance": 4,
                "memory_gb_per_instance": 32,
            },
        },
    }
    fixed_payload = {
        "service": "compute",
        "operation": {
            "operation": "create_instances",
            "resource_type": "instance",
            "region": region,
            "availability_domain": availability_domain,
            "compartment_id": compartment_id,
            "compartment_name": "Production",
            "workload": {
                "shape": fixed_shape,
                "instance_count": 2,
            },
        },
    } if fixed_shape else None
    manual_payload = {
        "operation": {
            "service": "compute",
            "resource_type": "instance",
            "region": region,
            "availability_domain": availability_domain,
            "compartment_id": compartment_id,
            "compartment_name": "Production",
            "requested": {"ocpus": 1},
        }
    }
    invalid_ocpu_payload = json.loads(json.dumps(flex_payload))
    invalid_ocpu_payload["operation"]["workload"]["ocpus_per_instance"] = 999999
    invalid_memory_payload = json.loads(json.dumps(flex_payload))
    invalid_memory_payload["operation"]["workload"]["memory_gb_per_instance"] = 999999
    unavailable_payload = json.loads(json.dumps(flex_payload))
    unavailable_payload["operation"]["availability_domain"] = os.getenv("VALIDATION_UNAVAILABLE_AD", f"{availability_domain}-DOES-NOT-EXIST")

    cases = [
        try_case("flex_workload", run_preflight, clients, tenancy_id, flex_payload),
        try_case("fixed_workload", run_preflight, clients, tenancy_id, fixed_payload) if fixed_payload else {"name": "fixed_workload", "ok": False, "error": "No fixed shape found in OCI list_shapes output."},
        try_case("invalid_flex_ocpu", run_preflight, clients, tenancy_id, invalid_ocpu_payload),
        try_case("invalid_flex_memory", run_preflight, clients, tenancy_id, invalid_memory_payload),
        try_case("shape_unavailable_selected_ad", run_preflight, clients, tenancy_id, unavailable_payload),
        try_case("manual_ocpu", run_manual, clients, tenancy_id, manual_payload),
    ]

    flex_shape_detail = next((shape.to_dict() for shape in shapes if shape.name == flex_shape), None)
    fixed_shape_detail = next((shape.to_dict() for shape in shapes if shape.name == fixed_shape), None) if fixed_shape else None

    report = {
        "runner": {
            "region": region,
            "quota_region": quota_region,
            "availability_domain": availability_domain,
            "shape_count": len(shapes),
        },
        "shape_names_sample": shape_names[:50],
        "selected_shapes": {
            "flex": flex_shape_detail,
            "fixed": fixed_shape_detail,
        },
        "compute_limit_definitions": compute_definitions,
        "cases": cases,
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
