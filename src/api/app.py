from __future__ import annotations

import os
from pathlib import Path
from time import time

from src.adapters import ServiceAdapterRegistry
from src.block_volume import BlockVolumeLimitResolver
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import Decision, Operation, PreflightResult
from src.compute import ComputeShapeProvider, ShapeLimitResolver
from src.discovery import OciLimitDiscovery
from src.limits.oci_limits_provider import OciLimitsProvider
from src.network_load_balancer import NetworkLoadBalancerLimitResolver
from src.oci_auth import build_oci_clients
from src.preflight.demo_data import scenario_quota_blocks
from src.preflight.risk import risk_state
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


operation, provider = scenario_quota_blocks()
engine = CapacityDecisionEngine([provider])
adapter_registry = ServiceAdapterRegistry()
capacity_cache: dict[tuple, tuple[float, list[dict]]] = {}
CAPACITY_CACHE_SECONDS = int(os.getenv("OCI_CAPACITY_PREFLIGHT_CAPACITY_CACHE_SECONDS", "300"))


def current_mode() -> str:
    """Normalize deployment aliases while preserving demo mode for local tests."""
    mode = (os.getenv("OCI_CAPACITY_PREFLIGHT_MODE") or os.getenv("OCI_MODE") or "demo").lower()
    return "oci" if mode in {"oci", "live"} else mode


def current_auth() -> str:
    return os.getenv("OCI_CAPACITY_PREFLIGHT_AUTH") or os.getenv("AUTH") or "resource_principal"


def payload_service(payload: dict) -> str:
    operation_payload = payload.get("operation", payload)
    service = (payload.get("service") or operation_payload.get("service") or "").lower()
    adapter = adapter_registry.get(service)
    return adapter.service if adapter else service


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
    auth = current_auth()
    tenancy_id = os.getenv("OCI_TENANCY_OCID")
    return build_oci_clients(
        auth=auth,
        region=oci_region(payload),
        quota_region=oci_quota_region(payload),
        tenancy_id=tenancy_id,
    )


def engine_for_payload(payload: dict):
    if current_mode() != "oci":
        return engine
    clients = clients_for_payload(payload)
    tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
    limit_mapping = payload.get("_resolved_limit_mapping") or adapter_registry.merged_limit_mapping()
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    return CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])


def operation_for_payload(payload: dict) -> Operation:
    if current_mode() != "oci":
        return Operation.from_dict(payload)
    service = payload_service(payload)
    adapter = adapter_registry.get(service)
    operation_payload = payload.get("operation", payload)
    if operation_payload.get("operation") == "check_discovered_limit":
        limit_name = operation_payload.get("limit_name")
        requested = operation_payload.get("requested") or operation_payload.get("requested_delta") or {}
        amount = requested.get("units")
        if not limit_name:
            raise ValueError("Generic discovered-limit preflight requires operation.limit_name.")
        if amount is None:
            raise ValueError("Generic discovered-limit preflight requires requested.units.")
        payload["_resolved_limit_mapping"] = {service: {"units": limit_name}}
        return Operation(
            service=service,
            resource_type="discovered_limit",
            region=operation_payload.get("region") or "",
            availability_domain=operation_payload.get("availability_domain"),
            compartment_id=operation_payload.get("compartment_id") or "",
            compartment_name=operation_payload.get("compartment_name"),
            requested_delta={"units": float(amount)},
            metadata={
                "mode": "generic_discovered_limit",
                "capacity_scope_note": "Generic limit check evaluates live OCI resource availability for the selected limit. It does not prove operation-specific service semantics.",
                "workload": {
                    "resource": "Discovered OCI limit",
                    "limit_name": limit_name,
                    "requested_units": float(amount),
                },
            },
        )
    if not adapter:
        raise ValueError(f"No FULL_PREFLIGHT adapter is available for service '{service}'.")
    if service == "compute" and operation_payload.get("workload"):
        clients = clients_for_payload(payload)
        tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
        operation, limit_mapping = adapter.workload_from_payload(
            payload,
            ComputeShapeProvider(clients.compute_client),
            ShapeLimitResolver(clients.limits_client, tenancy_id),
        )
        payload["_resolved_limit_mapping"] = limit_mapping
        return operation
    if service == "block-storage" and operation_payload.get("workload"):
        clients = clients_for_payload(payload)
        tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
        operation, limit_mapping = adapter.workload_from_payload(
            payload,
            BlockVolumeLimitResolver(clients.limits_client, tenancy_id),
        )
        payload["_resolved_limit_mapping"] = limit_mapping
        return operation
    if service == "network-load-balancer-api" and operation_payload.get("workload"):
        clients = clients_for_payload(payload)
        tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
        operation, limit_mapping = adapter.workload_from_payload(
            payload,
            NetworkLoadBalancerLimitResolver(clients.limits_client, tenancy_id),
        )
        payload["_resolved_limit_mapping"] = limit_mapping
        return operation
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
    return OciLimitDiscovery(clients.limits_client, tenancy_id, adapter_registry, clients.quotas_client, clients.compute_client)


def demo_capabilities():
    return [
        {
            "service": "compute",
            "service_description": "Compute",
            "limit_name": "standard-e4-core-count",
            "limit_description": "Demo Compute OCPU limit",
            "scope_type": "REGION",
            "limit_value": 300,
            "current_usage": 5,
            "available": 295,
            "capability": "FULL_PREFLIGHT",
            "unit": "ocpus",
            "reason": None,
            "is_eligible_for_increase": None,
            "region": "us-ashburn-1",
            "availability_domain": None,
            "resource_availability_supported": True,
            "quota_statements": [],
            "quota_readable": True,
            "utilization": 0.0167,
            "risk_state": "HEALTHY",
            "api_limitation": None,
            "data_status": "SYNTHETIC",
        },
        {
            "service": "block-storage",
            "service_description": "Block Storage",
            "limit_name": "total-storage-gb",
            "limit_description": "Demo Block Volume storage limit",
            "scope_type": "AD",
            "limit_value": 60372,
            "current_usage": 147,
            "available": 60225,
            "capability": "FULL_PREFLIGHT",
            "unit": "storage_gb",
            "reason": None,
            "is_eligible_for_increase": None,
            "region": "us-ashburn-1",
            "availability_domain": "Example-AD-A",
            "resource_availability_supported": True,
            "quota_statements": [],
            "quota_readable": True,
            "utilization": 0.0024,
            "risk_state": "HEALTHY",
            "api_limitation": None,
            "data_status": "SYNTHETIC",
        },
        {
            "service": "network-load-balancer",
            "service_description": "Network Load Balancer",
            "limit_name": "discovered-from-oci",
            "limit_description": "Demo discovery-only limit",
            "scope_type": "REGION",
            "limit_value": None,
            "current_usage": None,
            "available": None,
            "capability": "DISCOVERY_ONLY",
            "unit": None,
            "reason": "Demo row only. Full preflight requires a verified operation adapter.",
            "is_eligible_for_increase": None,
            "region": "us-ashburn-1",
            "availability_domain": None,
            "resource_availability_supported": False,
            "quota_statements": [],
            "quota_readable": True,
            "utilization": None,
            "risk_state": "UNKNOWN",
            "api_limitation": None,
            "data_status": "SYNTHETIC",
        },
    ]


def demo_shapes():
    return [
        {
            "name": "VM.Standard.E5.Flex",
            "ocpus": None,
            "memory_gb": None,
            "is_flex": True,
            "gpus": None,
            "processor_description": "Demo flex shape",
            "raw": {"ocpu_options": {"min": 1, "max": 64}, "memory_options": {"min_in_gbs": 1, "max_in_gbs": 1024}},
        },
        {
            "name": "VM.Standard.E5.4",
            "ocpus": 4,
            "memory_gb": 64,
            "is_flex": False,
            "gpus": None,
            "processor_description": "Demo fixed shape",
            "raw": {},
        },
    ]


def filter_capacity_rows(rows: list[dict], service: str | None = None, capability: str | None = None, risk: str | None = None) -> list[dict]:
    filtered = rows
    if service:
        filtered = [row for row in filtered if row.get("service") == service]
    if capability:
        filtered = [row for row in filtered if row.get("capability") == capability]
    if risk:
        filtered = [row for row in filtered if row.get("risk_state") == risk]
    return filtered


def stamp_capacity_rows(rows: list[dict], refreshed_at: float, status: str = "FRESH") -> list[dict]:
    """Attach collection metadata without inventing OCI capacity values."""
    for row in rows:
        row["last_refreshed"] = refreshed_at
        row["data_status"] = status
    return rows


def error_capacity_response(exc: Exception) -> dict:
    return {
        "capacity": [],
        "summary": capacity_summary([]),
        "cache": {
            "status": "error",
            "last_refreshed": None,
            "age_seconds": None,
            "ttl_seconds": CAPACITY_CACHE_SECONDS,
            "error": str(exc),
        },
        "error": "UNABLE TO VALIDATE",
        "technical_details": str(exc),
    }


def cached_capacity_rows(region: str | None, compartment_id: str | None, availability_domain: str | None) -> list[dict]:
    key = (region, compartment_id, availability_domain)
    now = time()
    cached = capacity_cache.get(key)
    if cached and now - cached[0] < CAPACITY_CACHE_SECONDS:
        return cached[1]
    discovery = discovery_for_request(region)
    rows = stamp_capacity_rows(
        [item.to_dict() for item in discovery.capacity_matrix(compartment_id, availability_domain, region)], now
    )
    capacity_cache[key] = (now, rows)
    return rows


def capacity_cache_info(region: str | None, compartment_id: str | None, availability_domain: str | None) -> dict:
    key = (region, compartment_id, availability_domain)
    cached = capacity_cache.get(key)
    if not cached:
        return {"status": "empty", "last_refreshed": None, "age_seconds": None, "ttl_seconds": CAPACITY_CACHE_SECONDS}
    age = round(time() - cached[0], 1)
    return {
        "status": "fresh" if age < CAPACITY_CACHE_SECONDS else "stale",
        "last_refreshed": cached[0],
        "age_seconds": age,
        "ttl_seconds": CAPACITY_CACHE_SECONDS,
    }


def default_capacity_cache_info() -> dict:
    infos = [capacity_cache_info(*key) for key in capacity_cache]
    refreshed = [info for info in infos if info.get("last_refreshed")]
    if not refreshed:
        return {"status": "empty", "last_refreshed": None, "age_seconds": None, "ttl_seconds": CAPACITY_CACHE_SECONDS}
    latest = max(refreshed, key=lambda item: item["last_refreshed"])
    if any(info.get("status") == "stale" for info in infos):
        latest = dict(latest)
        latest["status"] = "stale"
    return latest


def capacity_summary(rows: list[dict]) -> dict:
    counts = {"FULL_PREFLIGHT": 0, "MONITOR_ONLY": 0, "DISCOVERY_ONLY": 0, "UNSUPPORTED": 0}
    risk = {"CRITICAL": 0, "WARNING": 0, "WATCH": 0, "HEALTHY": 0, "UNKNOWN": 0, "EXHAUSTED": 0}
    services = set()
    for row in rows:
        services.add(row.get("service"))
        if row.get("capability") in counts:
            counts[row["capability"]] += 1
        if row.get("risk_state") in risk:
            risk[row["risk_state"]] += 1
    return {"services_discovered": len([item for item in services if item]), "limits_discovered": len(rows), "capability_counts": counts, "risk_counts": risk}


def masked_ocid(value: str | None) -> str | None:
    if not value:
        return None
    return f"...{value[-12:]}" if len(value) > 12 else value


def default_form_value(field_name: str) -> str | None:
    defaults = {
        "region": os.getenv("OCI_CAPACITY_PREFLIGHT_REGION") or os.getenv("OCI_REGION"),
        "compartment_id": os.getenv("OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID"),
        "availability_domain": os.getenv("OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN"),
    }
    return defaults.get(field_name)


def apply_runtime_form_defaults(operation: dict) -> dict:
    fields = []
    for field in operation.get("form", []):
        item = dict(field)
        default = default_form_value(item.get("name"))
        if default:
            item["default"] = default
        fields.append(item)
    operation["form"] = fields
    return operation


def operation_catalog() -> dict:
    display_names = {
        "compute": "Compute",
        "block-storage": "Block Volume",
        "network-load-balancer-api": "Network Load Balancer",
    }
    grouped: dict[str, dict] = {}
    flat = adapter_registry.describe_operations()
    for item in flat:
        service = item["service"]
        grouped.setdefault(service, {"service": service, "display_name": display_names.get(service, service.replace("-", " ").title()), "operations": []})
        operation = apply_runtime_form_defaults({key: value for key, value in item.items() if key != "service"})
        grouped[service]["operations"].append(operation)
    return {"services": list(grouped.values()), "operations": [apply_runtime_form_defaults({key: value for key, value in item.items()}) for item in flat]}

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Capacity Readiness Check")
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
        if current_mode() != "oci":
            seen = {}
            for row in demo_capabilities():
                seen[row["service"]] = {"name": row["service"], "description": row["service_description"]}
            return {"services": list(seen.values())}
        return {"services": discovery_for_request(region).list_services()}

    @app.get("/services/{service_name}/limits")
    def service_limits(service_name: str, region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None):
        if current_mode() != "oci":
            return {"limits": [row for row in demo_capabilities() if row["service"] == service_name]}
        discovery = discovery_for_request(region)
        return {"limits": [item.to_dict() for item in discovery.list_limits(service_name, compartment_id, availability_domain, region)]}

    @app.get("/operations")
    def operations():
        return operation_catalog()

    @app.get("/capacity")
    def capacity(region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None, service: str | None = None, capability: str | None = None, risk: str | None = None):
        if current_mode() != "oci":
            rows = demo_capabilities()
            filtered = filter_capacity_rows(rows, service, capability, risk)
            refreshed = time()
            return {"capacity": stamp_capacity_rows(filtered, refreshed, "SYNTHETIC"), "summary": capacity_summary(rows), "cache": {"status": "synthetic", "last_refreshed": refreshed, "age_seconds": 0, "ttl_seconds": CAPACITY_CACHE_SECONDS}}
        try:
            rows = cached_capacity_rows(region, compartment_id, availability_domain)
        except Exception as exc:
            return error_capacity_response(exc)
        return {"capacity": filter_capacity_rows(rows, service, capability, risk), "summary": capacity_summary(rows), "cache": capacity_cache_info(region, compartment_id, availability_domain)}

    @app.post("/capacity/refresh")
    def refresh_capacity(region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None):
        """Refresh explicitly; normal page loads remain protected by the TTL cache."""
        if current_mode() != "oci":
            refreshed = time()
            rows = stamp_capacity_rows(demo_capabilities(), refreshed, "SYNTHETIC")
            return {"capacity": rows, "summary": capacity_summary(rows), "cache": {"status": "synthetic", "last_refreshed": refreshed, "age_seconds": 0, "ttl_seconds": CAPACITY_CACHE_SECONDS}}
        key = (region, compartment_id, availability_domain)
        capacity_cache.pop(key, None)
        try:
            rows = cached_capacity_rows(region, compartment_id, availability_domain)
        except Exception as exc:
            return error_capacity_response(exc)
        return {"capacity": rows, "summary": capacity_summary(rows), "cache": capacity_cache_info(region, compartment_id, availability_domain)}

    @app.get("/compute/shapes")
    def compute_shapes(region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None):
        if current_mode() != "oci":
            return {"shapes": demo_shapes()}
        if not compartment_id:
            return {"shapes": [], "error": "compartment_id is required to list Compute shapes."}
        clients = clients_for_payload({"region": region} if region else None)
        shapes = ComputeShapeProvider(clients.compute_client).list_shapes(compartment_id, availability_domain)
        return {"shapes": [shape.to_dict() for shape in shapes]}

    @app.get("/risk")
    def risk(region: str | None = None, compartment_id: str | None = None, availability_domain: str | None = None):
        if current_mode() == "oci":
            discovery = discovery_for_request(region)
            rows = [item.to_dict() for item in discovery.capacity_matrix(compartment_id, availability_domain, region)]
            return {"advisory": True, "risks": [row for row in rows if row.get("risk_state") not in {None, "HEALTHY"}]}
        return {"advisory": True, "risks": [risk_state(snapshot) | {"constraint": snapshot.limit_name, "service": snapshot.service} for snapshot in provider.snapshots]}

    @app.get("/health")
    def health():
        tenancy_id = os.getenv("OCI_TENANCY_OCID")
        cache = default_capacity_cache_info()
        return {
            "status": "ok",
            "mode": current_mode(),
            "auth": current_auth(),
            "tenancy_configured": bool(tenancy_id),
            "tenancy_id": masked_ocid(tenancy_id),
            "region": os.getenv("OCI_CAPACITY_PREFLIGHT_REGION") or os.getenv("OCI_REGION"),
            "quota_region": os.getenv("OCI_CAPACITY_PREFLIGHT_QUOTA_REGION"),
            "discovery_cache": cache["status"],
            "last_refresh": cache["last_refreshed"],
            "data_age_seconds": cache["age_seconds"],
            "cache_ttl_seconds": cache["ttl_seconds"],
        }

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="team-review-ui")
except ImportError:
    app = None
