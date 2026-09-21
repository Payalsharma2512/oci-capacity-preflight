from __future__ import annotations

import json
import os
from typing import Any

from src.adapters import NetworkLoadBalancerAdapter
from src.capacity.engine import CapacityDecisionEngine
from src.limits.oci_limits_provider import OciLimitsProvider
from src.network_load_balancer import NetworkLoadBalancerLimitResolver
from src.oci_auth import build_oci_clients
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def payload(region: str, compartment_id: str, count: int) -> dict[str, Any]:
    return {
        "service": "nlb",
        "operation": {
            "operation": "create_network_load_balancers",
            "region": region,
            "compartment_id": compartment_id,
            "workload": {"nlb_count": count},
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
    adapter = NetworkLoadBalancerAdapter()
    operation, mapping = adapter.workload_from_payload(
        payload_data,
        NetworkLoadBalancerLimitResolver(clients.limits_client, tenancy_id),
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
    clients = build_oci_clients(auth="instance_principal", region=region, quota_region=quota_region, tenancy_id=tenancy_id)

    service = "network-load-balancer-api"
    definitions = clients.limits_client.list_limit_definitions(tenancy_id, service_name=service).data
    mapping = NetworkLoadBalancerLimitResolver(clients.limits_client, tenancy_id).resolve({"nlb_count"})
    limit_name = mapping["nlb_count"]
    availability_data = clients.limits_client.get_resource_availability(service, limit_name, compartment_id).data
    used = getattr(availability_data, "used", None)
    available = getattr(availability_data, "available", None)
    maximum = None if used is None or available is None else used + available
    available_count = int(available or 0)

    quota_statements = []
    try:
        response = clients.quotas_client.list_quotas(tenancy_id, lifecycle_state="ACTIVE")
        for quota in response.data:
            full = clients.quotas_client.get_quota(quota.id).data if getattr(quota, "id", None) and not getattr(quota, "statements", None) else quota
            quota_statements.extend(getattr(full, "statements", []) or [])
    except Exception as exc:
        quota_statements = [f"quota read failed: {exc}"]

    cases = [
        try_case("pass_small_nlb", run_preflight, clients, tenancy_id, payload(region, compartment_id, 1)),
        try_case("service_limit_block", run_preflight, clients, tenancy_id, payload(region, compartment_id, available_count + 1)),
        try_case("exact_boundary", run_preflight, clients, tenancy_id, payload(region, compartment_id, available_count)),
        try_case("boundary_plus_one", run_preflight, clients, tenancy_id, payload(region, compartment_id, available_count + 1)),
        try_case("invalid_input", run_preflight, clients, tenancy_id, payload(region, compartment_id, 0)),
    ]

    report = {
        "runner": {"region": region, "quota_region": quota_region},
        "service": service,
        "limit_definitions": [
            {
                "name": getattr(item, "name", None),
                "description": getattr(item, "description", None),
                "scope_type": getattr(item, "scope_type", None),
                "is_eligible_for_limit_increase": getattr(item, "is_eligible_for_limit_increase", None),
            }
            for item in definitions
        ],
        "selected_mapping": mapping,
        "availability": {
            "limit_name": limit_name,
            "used": used,
            "available": available,
            "maximum": maximum,
        },
        "quota_statements": quota_statements,
        "nlb_quota_statements": [statement for statement in quota_statements if "nlb" in statement.lower() or "network-load-balancer" in statement.lower()],
        "cases": cases,
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
