from __future__ import annotations

import json
import os
from typing import Any

from src.adapters import BlockVolumeAdapter
from src.block_volume import BlockVolumeLimitResolver
from src.capacity.engine import CapacityDecisionEngine
from src.limits.oci_limits_provider import OciLimitsProvider
from src.oci_auth import build_oci_clients
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def payload(region: str, compartment_id: str, availability_domain: str | None, count: int, size_gb_each: float) -> dict[str, Any]:
    return {
        "service": "blockvolume",
        "operation": {
            "operation": "create_volumes",
            "region": region,
            "availability_domain": availability_domain,
            "compartment_id": compartment_id,
            "workload": {
                "volume_count": count,
                "size_gb_each": size_gb_each,
            },
        },
    }


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


def run_preflight(clients, tenancy_id: str, payload_data: dict[str, Any]) -> dict[str, Any]:
    adapter = BlockVolumeAdapter()
    operation, mapping = adapter.workload_from_payload(
        payload_data,
        BlockVolumeLimitResolver(clients.limits_client, tenancy_id),
    )
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, mapping)
    engine = CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])
    return {"limit_mapping": mapping, "result": result_summary(engine.preflight(operation))}


def try_case(name: str, func, *args) -> dict[str, Any]:
    try:
        return {"name": name, "ok": True, "data": func(*args)}
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

    definitions = []
    page = None
    while True:
        response = clients.limits_client.list_limit_definitions(tenancy_id, service_name="block-storage", page=page)
        definitions.extend(response.data)
        page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
        if not page:
            break

    resolver = BlockVolumeLimitResolver(clients.limits_client, tenancy_id)
    mapping = resolver.resolve({"volume_count", "storage_gb"})
    availability = {}
    for metric, limit_name in mapping.items():
        response = clients.limits_client.get_resource_availability(
            "block-storage",
            limit_name,
            compartment_id,
            availability_domain=availability_domain,
        )
        data = response.data
        availability[metric] = {
            "limit_name": limit_name,
            "used": getattr(data, "used", None),
            "available": getattr(data, "available", None),
            "maximum": None if getattr(data, "used", None) is None or getattr(data, "available", None) is None else getattr(data, "used") + getattr(data, "available"),
        }

    storage_available = max(float(availability["storage_gb"]["available"] or 0), 0)
    count_available = max(float(availability["volume_count"]["available"] or 0), 0)
    exact_size = storage_available if storage_available > 0 else 1

    quota_statements = []
    try:
        page = None
        while True:
            response = clients.quotas_client.list_quotas(tenancy_id, page=page, lifecycle_state="ACTIVE")
            for quota in response.data:
                full = clients.quotas_client.get_quota(quota.id).data if getattr(quota, "id", None) and not getattr(quota, "statements", None) else quota
                quota_statements.extend(getattr(full, "statements", []) or [])
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                break
    except Exception as exc:
        quota_statements = [f"quota read failed: {exc}"]

    cases = [
        try_case("pass_small_volume", run_preflight, clients, tenancy_id, payload(region, compartment_id, availability_domain, 1, 50)),
        try_case("service_limit_block_storage", run_preflight, clients, tenancy_id, payload(region, compartment_id, availability_domain, 1, storage_available + 1)),
        try_case("exact_storage_boundary", run_preflight, clients, tenancy_id, payload(region, compartment_id, availability_domain, 1, exact_size)),
        try_case("storage_boundary_plus_one", run_preflight, clients, tenancy_id, payload(region, compartment_id, availability_domain, 1, exact_size + 1)),
        try_case("missing_availability_domain", run_preflight, clients, tenancy_id, payload(region, compartment_id, None, 1, 50)),
        try_case("invalid_missing_input", run_preflight, clients, tenancy_id, {"service": "blockvolume", "operation": {"operation": "create_volumes", "region": region, "availability_domain": availability_domain, "compartment_id": compartment_id, "workload": {"volume_count": 0, "size_gb_each": 50}}}),
    ]
    if count_available > 0:
        cases.append(try_case("service_limit_block_volume_count", run_preflight, clients, tenancy_id, payload(region, compartment_id, availability_domain, int(count_available) + 1, 1)))

    report = {
        "runner": {
            "region": region,
            "quota_region": quota_region,
            "availability_domain": availability_domain,
        },
        "block_volume_limit_definitions": [
            {
                "name": getattr(item, "name", None),
                "description": getattr(item, "description", None),
                "scope_type": getattr(item, "scope_type", None),
                "is_eligible_for_limit_increase": getattr(item, "is_eligible_for_limit_increase", None),
            }
            for item in definitions
        ],
        "selected_mapping": mapping,
        "availability": availability,
        "quota_statements": quota_statements,
        "block_volume_quota_statements": [statement for statement in quota_statements if "block" in statement.lower() or "volume" in statement.lower()],
        "cases": cases,
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
