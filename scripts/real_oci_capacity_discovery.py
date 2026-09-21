from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Any

from src.discovery import OciLimitDiscovery
from src.oci_auth import build_oci_clients


CANDIDATE_SERVICES = {
    "block-storage",
    "block-store",
    "load-balancer",
    "network-load-balancer",
    "database",
    "container-engine",
    "oke",
    "vcn",
    "virtual-network",
    "functions",
    "fn",
    "generative-ai",
    "ai-generative",
}


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def capability_score(row: dict[str, Any]) -> int:
    capability = row.get("capability")
    if capability == "FULL_PREFLIGHT":
        return 4
    if capability == "MONITOR_ONLY":
        return 3
    if capability == "DISCOVERY_ONLY":
        return 2
    return 1


def is_candidate_service(service: str, description: str | None) -> bool:
    text = f"{service} {description or ''}".lower()
    return any(name in text for name in CANDIDATE_SERVICES)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    service_summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        service = row["service"]
        entry = service_summary.setdefault(
            service,
            {
                "service": service,
                "description": row.get("service_description"),
                "limits": 0,
                "capabilities": Counter(),
                "risk_states": Counter(),
                "availability_supported": 0,
                "quota_statements": 0,
                "eligible_for_increase": 0,
                "scopes": Counter(),
                "example_limits": [],
            },
        )
        entry["limits"] += 1
        entry["capabilities"][row.get("capability") or "UNKNOWN"] += 1
        entry["risk_states"][row.get("risk_state") or "UNKNOWN"] += 1
        entry["scopes"][row.get("scope_type") or "UNKNOWN"] += 1
        if row.get("resource_availability_supported"):
            entry["availability_supported"] += 1
        if row.get("quota_statements"):
            entry["quota_statements"] += len(row["quota_statements"])
        if row.get("is_eligible_for_increase"):
            entry["eligible_for_increase"] += 1
        if len(entry["example_limits"]) < 12:
            entry["example_limits"].append(
                {
                    "limit_name": row.get("limit_name"),
                    "scope_type": row.get("scope_type"),
                    "capability": row.get("capability"),
                    "current_usage": row.get("current_usage"),
                    "limit_value": row.get("limit_value"),
                    "available": row.get("available"),
                    "utilization": row.get("utilization"),
                    "resource_availability_supported": row.get("resource_availability_supported"),
                    "quota_statements": row.get("quota_statements"),
                    "api_limitation": row.get("api_limitation"),
                }
            )

    serializable_services = []
    for entry in service_summary.values():
        converted = dict(entry)
        converted["capabilities"] = dict(entry["capabilities"])
        converted["risk_states"] = dict(entry["risk_states"])
        converted["scopes"] = dict(entry["scopes"])
        converted["score"] = sum(capability_score({"capability": cap}) * count for cap, count in converted["capabilities"].items())
        converted["candidate"] = is_candidate_service(converted["service"], converted.get("description"))
        serializable_services.append(converted)

    by_capability = Counter(row.get("capability") or "UNKNOWN" for row in rows)
    by_risk = Counter(row.get("risk_state") or "UNKNOWN" for row in rows)
    best_candidate_services = sorted(
        [entry for entry in serializable_services if entry["candidate"]],
        key=lambda item: (
            item["capabilities"].get("MONITOR_ONLY", 0),
            item["availability_supported"],
            item["quota_statements"],
            item["limits"],
        ),
        reverse=True,
    )
    return {
        "total_limits": len(rows),
        "total_services": len(service_summary),
        "capability_counts": dict(by_capability),
        "risk_counts": dict(by_risk),
        "services": sorted(serializable_services, key=lambda item: item["service"]),
        "candidate_services_ranked_by_data": best_candidate_services,
    }


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
    discovery = OciLimitDiscovery(
        clients.limits_client,
        tenancy_id,
        quotas_client=clients.quotas_client,
        compute_client=clients.compute_client,
    )
    rows = [
        item.to_dict()
        for item in discovery.capacity_matrix(
            compartment_id=compartment_id,
            availability_domain=availability_domain,
            region=region,
        )
    ]
    report = {
        "context": {
            "region": region,
            "quota_region": quota_region,
            "availability_domain": availability_domain,
            "auth": "instance_principal",
        },
        "summary": summarize(rows),
        "limits": rows,
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
