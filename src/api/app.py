from __future__ import annotations

import os
from pathlib import Path

from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import Operation
from src.limits.oci_limits_provider import OciLimitsProvider
from src.oci_auth import build_oci_clients
from src.preflight.demo_data import scenario_quota_blocks
from src.preflight.risk import risk_state
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


operation, provider = scenario_quota_blocks()
engine = CapacityDecisionEngine([provider])


def engine_for_payload(payload: dict):
    if os.getenv("OCI_CAPACITY_PREFLIGHT_MODE", "demo") != "oci":
        return engine
    auth = os.getenv("OCI_CAPACITY_PREFLIGHT_AUTH", "resource_principal")
    region = payload.get("region") or payload.get("operation", {}).get("region")
    quota_region = payload.get("quota_region") or payload.get("operation", {}).get("quota_region") or os.getenv("OCI_CAPACITY_PREFLIGHT_QUOTA_REGION")
    service = payload.get("service") or payload.get("operation", {}).get("service", "compute")
    limit_name = os.getenv("OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT", "standard-e4-core-count")
    tenancy_id = os.getenv("OCI_TENANCY_OCID")
    clients = build_oci_clients(auth=auth, region=region, quota_region=quota_region, tenancy_id=tenancy_id)
    tenancy_id = os.getenv("OCI_TENANCY_OCID", clients.tenancy_id)
    limit_mapping = {service: {"ocpus": limit_name}}
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    return CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])

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
        return engine_for_payload(payload).preflight(Operation.from_dict(payload["operation"] if "operation" in payload else payload)).to_dict()

    @app.post("/preflight/batch")
    def preflight_batch(payload: dict):
        return engine_for_payload(payload).preflight_batch([Operation.from_dict(item) for item in payload["operations"]])

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
