from __future__ import annotations

import os
from pathlib import Path

from src.adapters import ServiceAdapterRegistry
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import Decision, Operation, PreflightResult
from src.discovery import OciLimitDiscovery
from src.limits.oci_limits_provider import OciLimitsProvider
from src.oci_auth import build_oci_clients
from src.preflight.demo_data import scenario_quota_blocks
from src.preflight.risk import risk_state
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


operation, provider = scenario_quota_blocks()
engine = CapacityDecisionEngine([provider])
adapter_registry = ServiceAdapterRegistry()


def payload_service(payload: dict) -> str:
    operation_payload = payload.get("operation", payload)
    return (payload.get("service") or operation_payload.get("service") or "").lower()


def oci_region(payload: dict | None = None) -> str | None:
    payload = payload or {}
    return (
        payload.get("region")
        or payload.get("operation", {}).get("region")
        or os.getenv("OCI_CAPACITY_PREFLIGHT_REGION")
        or os.getenv("OCI_REGION")
    )


def oci_quota_region(payload: dict | None = None) -> str | None:
    payload = payload or {}
    return (
        payload.get("quota_region")
        or payload.get("operation", {}).get("quota_region")
        or os.getenv("OCI_CAPACITY_PREFLIGHT_QUOTA_REGION")
        or oci_region(payload)
    )


def clients_for_payload(payload: dict | None = None):
    auth = os.getenv("OCI_CAPACITY_PREFLIGHT_AUTH", "resource_principal")
    tenancy_id = os.getenv("OCI_TENANCY_OCID")
    return build_oci_clients(
        auth=auth,
        region=oci_region(payload),
        quota_region=oci_quota_region(payload),
        tenancy_id=tenancy_id,
    )


def engine_for_payload(payload: dict):
    if os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo") != "oci":
        return engine
    clients = clients_for_payload(payload)
    tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
    limit_mapping = adapter_registry.merged_limit_mapping()
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    return CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])


def operation_for_payload(payload: dict) -> Operation:
    if os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo") != "oci":
        return Operation.from_dict(payload)
    service = payload_service(payload)
    adapter = adapter_registry.get(service)
    if not adapter:
        raise ValueError(f"No FULL_PREFLIGHT adapter is available for service '{service}'.")
    return adapter.operation_from_payload(payload)


def unable_to_validate(payload: dict, reason: str) -> dict:
    operation_payload = payload.get("operation", payload)
    service = payload_service(payload) or operation_payload.get("service") or "unknown"
    operation = Operation(
        service=service,
        resource_type=operation_payload.get("resource_type"),
        region=operation_payload.get("region") or "",
        availability_domain=operation_payload.get("availability_domain"),
        compartment_id=operation_payload.get("compartment_id") or "",
        compartment_name=operation_payload.get("compartment_name"),
        requested_delta={k: float(v) for k, v in (operation_payload.get("requested") or operation_payload.get("requested_delta") or {}).items()},
    )
    return PreflightResult(
        decision=Decision.UNKNOWN,
        confidence="LOW",
        advisory=True,
        operation=operation,
        effective_available_capacity=None,
        primary_blocking_constraint=None,
        checks=[],
        recommendations=[{"action": "USE_SUPPORTED_PREFLIGHT_ADAPTER", "reason": reason}],
        unknown_reasons=[reason],
    ).to_dict()


def discovery_for_request(region: str | None = None):
    clients = clients_for_payload({"region": region} if region else None)
    tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
    return OciLimitDiscovery(clients.limits_client, tenancy_id, adapter_registry)


def demo_capabilities():
    return [
        {
            "service": "compute",
            "service_description": "Compute",
            "limit_name": "standard-e4-core-count",
            "scope_type": "REGION",
            "limit_value": 300,
            "current_usage": 5,
            "available": 295,
            "capability": "FULL_PREFLIGHT",
            "unit": "ocpus",
            "reason": None,
            "is_eligible_for_increase": None,
        },
        {
            "service": "block-storage",
            "service_description": "Block Storage",
            "limit_name": "discovered-from-oci",
            "scope_type": "REGION",
            "limit_value": None,
            "current_usage": None,
            "available": None,
            "capability": "DISCOVERY_ONLY",
            "unit": None,
            "reason": "Demo row only. Real limit names come from OCI discovery.",
            "is_eligible_for_increase": None,
        },
        {
            "service": "network-load-balancer",
            "service_description": "Network Load Balancer",
            "limit_name": "discovered-from-oci",
            "scope_type": "REGION",
            "limit_value": None,
            "current_usage": None,
            "available": None,
            "capability": "DISCOVERY_ONLY",
            "unit": None,
            "reason": "Demo row only. Full preflight requires a verified operation adapter.",
            "is_eligible_for_increase": None,
        },
    ]

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="OCI Capacity Preflight")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/preflight")
    def preflight(payload: dict):
        try:
            operation = operation_for_payload(payload)
        except Exception as exc:
            return unable_to_validate(payload, str(exc))
        return engine_for_payload(payload).preflight(operation).to_dict()

    @app.post("/preflight/batch")
    def preflight_batch(payload: dict):
        try:
            operations = [operation_for_payload(item) for item in payload["operations"]]
        except Exception as exc:
            return {"overall_decision": "UNKNOWN", "advisory": True, "results": [], "unknown_reasons": [str(exc)]}
        return engine_for_payload(payload).preflight_batch(operations)

    @app.get("/services")
    def services(region: str | None = None):
        if os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo") != "oci":
            seen = {}
            for row in demo_capabilities():
                seen[row["service"]] = {"name": row["service"], "description": row["service_description"]}
            return {"services": list(seen.values())}
        return {"services": discovery_for_request(region).list_services()}

    @app.get("/services/{service_name}/limits")
    def service_limits(service_name: str, region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None):
        if os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo") != "oci":
            return {"limits": [row for row in demo_capabilities() if row["service"] == service_name]}
        discovery = discovery_for_request(region)
        return {"limits": [item.to_dict() for item in discovery.list_limits(service_name, compartment_id, availability_domain)]}

    @app.get("/capacity")
    def capacity(region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None):
        if os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo") != "oci":
            return {"capacity": demo_capabilities()}
        discovery = discovery_for_request(region)
        return {"capacity": [item.to_dict() for item in discovery.capacity_matrix(compartment_id, availability_domain)]}

    @app.get("/risk")
    def risk():
        return {"advisory": True, "risks": [risk_state(snapshot) | {"constraint": snapshot.limit_name, "service": snapshot.service} for snapshot in provider.snapshots]}

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "mode": os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo"),
            "auth": os.getenv("OCI_CAPACITY_PREFLIGHT_AUTH", "resource_principal"),
            "tenancy_configured": bool(os.getenv("OCI_TENANCY_OCID")),
            "quota_region": os.getenv("OCI_CAPACITY_PREFLIGHT_QUOTA_REGION"),
        }

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="team-review-ui")
except ImportError:
    app = None
