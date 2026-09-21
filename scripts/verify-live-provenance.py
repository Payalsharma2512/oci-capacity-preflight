from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.compute import ComputeShapeProvider
from src.oci_auth import build_oci_clients


APP_BASE = os.getenv("OCI_CAPACITY_PREFLIGHT_APP_URL", "http://127.0.0.1:8000").rstrip("/")
REGION = os.getenv("OCI_CAPACITY_PREFLIGHT_REGION") or os.getenv("OCI_REGION") or os.getenv("TARGET_REGION") or "us-ashburn-1"
QUOTA_REGION = os.getenv("OCI_CAPACITY_PREFLIGHT_QUOTA_REGION") or REGION
COMPARTMENT_ID = os.getenv("OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID") or os.getenv("TARGET_COMPARTMENT_OCID")
AVAILABILITY_DOMAIN = os.getenv("OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN") or os.getenv("AVAILABILITY_DOMAIN")
TENANCY_ID_ENV = os.getenv("OCI_TENANCY_OCID")
COMPUTE_SHAPE = os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_SHAPE", "VM.Standard.E5.Flex")
COMPUTE_OCPUS_PER_INSTANCE = float(os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_OCPUS_PER_INSTANCE", "4"))
COMPUTE_MEMORY_GB_PER_INSTANCE = float(os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_MEMORY_GB_PER_INSTANCE", "32"))
COMPUTE_INSTANCE_COUNT = int(os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_INSTANCE_COUNT", "5"))
BLOCK_VOLUME_COUNT = int(os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_VOLUME_COUNT", "5"))
BLOCK_VOLUME_SIZE_GB_EACH = float(os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_VOLUME_SIZE_GB_EACH", "2048"))
NLB_COUNT = int(os.getenv("OCI_CAPACITY_PREFLIGHT_VERIFY_NLB_COUNT", "5"))


class Verification:
    def __init__(self) -> None:
        self.failures = 0
        self.not_verified = 0
        self.details: list[str] = []

    def line(self, label: str, status: str, detail: str | None = None) -> None:
        print(f"{label} {status}")
        if detail:
            print(f"  {detail}")
        if status == "FAIL":
            self.failures += 1
        elif status == "NOT VERIFIED":
            self.not_verified += 1

    def pass_fail(self, label: str, ok: bool | None, detail: str | None = None) -> None:
        if ok is True:
            self.line(label, "PASS", detail)
        elif ok is False:
            self.line(label, "FAIL", detail)
        else:
            self.line(label, "NOT VERIFIED", detail)


def mask_ocid(value: str | None) -> str:
    if not value:
        return "not configured"
    if len(value) <= 12:
        return value
    prefix = value.split("..", 1)[0]
    return f"{prefix}...{value[-4:]}"


def safe_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def same_number(left: Any, right: Any) -> bool | None:
    left_num = safe_number(left)
    right_num = safe_number(right)
    if left_num is None or right_num is None:
        return None
    return abs(left_num - right_num) < 0.000001


def maximum(used: Any, available: Any) -> float | None:
    used_num = safe_number(used)
    available_num = safe_number(available)
    if used_num is None or available_num is None:
        return None
    return used_num + available_num


def request_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{APP_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def query_string(params: dict[str, str | None]) -> str:
    return urllib.parse.urlencode({key: value for key, value in params.items() if value})


def paged(fetch) -> list[Any]:
    items: list[Any] = []
    page = None
    while True:
        response = fetch(page)
        data = getattr(response, "data", response)
        items.extend(data if isinstance(data, list) else [data])
        page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
        if not page:
            return items


def get_availability(clients, service: str, limit_name: str, compartment_id: str, availability_domain: str | None = None) -> dict[str, Any]:
    kwargs = {}
    if availability_domain:
        kwargs["availability_domain"] = availability_domain
    data = clients.limits_client.get_resource_availability(service, limit_name, compartment_id, **kwargs).data
    used = getattr(data, "used", None)
    available = getattr(data, "available", None)
    return {
        "service": service,
        "limit_name": limit_name,
        "used": safe_number(used),
        "available": safe_number(available),
        "limit": maximum(used, available),
    }


def row_for(capacity: dict[str, Any], service: str, limit_name: str) -> dict[str, Any] | None:
    for row in capacity.get("capacity", []) or []:
        if row.get("service") == service and row.get("limit_name") == limit_name:
            return row
    return None


def check_for(preflight: dict[str, Any], constraint_type: str, limit_name: str) -> dict[str, Any] | None:
    for check in preflight.get("checks", []) or []:
        if check.get("constraint_type") == constraint_type and check.get("limit_name") == limit_name:
            return check
    return None


def parse_quota_statement(statement: str) -> dict[str, Any] | None:
    match = re.search(
        r"set\s+(?P<service>\S+)\s+quota\s+(?P<limit>\S+)\s+to\s+(?P<value>\d+(?:\.\d+)?)",
        statement,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "service": normalize_quota_service(match.group("service")),
        "limit": match.group("limit"),
        "value": float(match.group("value")),
        "statement": sanitize_statement(statement),
    }


def normalize_quota_service(service_name: str) -> str:
    lower = service_name.lower()
    if lower in {"compute-core", "compute-memory", "compute-gpu"}:
        return "compute"
    if lower in {"blockvolume", "block-volume", "block-storage", "block-volume-service"}:
        return "block-storage"
    if lower in {"nlb", "network-load-balancer", "network-load-balancer-api"}:
        return "network-load-balancer-api"
    return lower


def sanitize_statement(statement: str) -> str:
    return re.sub(r"ocid1\.[A-Za-z0-9_.-]+", "<masked-ocid>", statement)


def quota_index(clients, tenancy_id: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    quotas = paged(lambda page: clients.quotas_client.list_quotas(tenancy_id, page=page, lifecycle_state="ACTIVE"))
    for quota in quotas:
        full = clients.quotas_client.get_quota(quota.id).data if getattr(quota, "id", None) and not getattr(quota, "statements", None) else quota
        for statement in getattr(full, "statements", []) or []:
            parsed = parse_quota_statement(statement)
            if parsed:
                index.setdefault((parsed["service"], parsed["limit"]), []).append(parsed)
    return index


def print_config(clients, verifier: Verification) -> None:
    tenancy_id = TENANCY_ID_ENV or clients.tenancy_id
    print("# LIVE DATA PROVENANCE")
    print()
    print("Authentication:")
    verifier.pass_fail("Instance Principal", True if clients.signer is not None else False)
    print()
    print("Tenancy:")
    verifier.pass_fail(mask_ocid(tenancy_id), bool(tenancy_id))
    print()
    print("Runner configuration:")
    print(f"Region {REGION}")
    print(f"Quota region {QUOTA_REGION}")
    print(f"Compartment {mask_ocid(COMPARTMENT_ID)}")
    print(f"Availability domain {AVAILABILITY_DOMAIN or 'not configured'}")
    print(f"Application {APP_BASE}")
    print()


def direct_oci_values(clients, tenancy_id: str, verifier: Verification) -> dict[str, Any]:
    if not COMPARTMENT_ID:
        verifier.line("Direct OCI values", "NOT VERIFIED", "Missing OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID or TARGET_COMPARTMENT_OCID.")
        return {}
    if not AVAILABILITY_DOMAIN:
        verifier.line("Direct OCI values", "NOT VERIFIED", "Missing OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN or AVAILABILITY_DOMAIN.")
        return {}

    values: dict[str, Any] = {"quotas": {}}
    try:
        shape = ComputeShapeProvider(clients.compute_client).get_shape(COMPARTMENT_ID, COMPUTE_SHAPE, AVAILABILITY_DOMAIN)
        quota_names = list(shape.raw.get("quota_names") or shape.raw.get("_quota_names") or [])
        values["shape"] = {"name": shape.name, "quota_names": quota_names}
        verifier.pass_fail("Compute shape quota_names", "standard-e5-core-count" in quota_names and "standard-e5-memory-count" in quota_names)
    except Exception as exc:
        values["shape_error"] = str(exc)
        verifier.line("Compute shape quota_names", "NOT VERIFIED", str(exc))

    limit_specs = {
        "compute_ocpu": ("compute", "standard-e5-core-count", AVAILABILITY_DOMAIN),
        "compute_memory": ("compute", "standard-e5-memory-count", AVAILABILITY_DOMAIN),
        "block_volume_count": ("block-storage", "volume-count", AVAILABILITY_DOMAIN),
        "block_volume_storage": ("block-storage", "total-storage-gb", AVAILABILITY_DOMAIN),
        "nlb_count": ("network-load-balancer-api", "max-nlb-flexible-count", None),
    }
    for key, (service, limit_name, ad) in limit_specs.items():
        try:
            values[key] = get_availability(clients, service, limit_name, COMPARTMENT_ID, ad)
        except Exception as exc:
            values[key] = {"error": str(exc), "service": service, "limit_name": limit_name}
            verifier.line(f"Direct OCI {limit_name}", "NOT VERIFIED", str(exc))

    try:
        values["quotas"] = quota_index(clients, tenancy_id)
        verifier.pass_fail("Quotas API", True)
    except Exception as exc:
        values["quota_error"] = str(exc)
        verifier.line("Quotas API", "NOT VERIFIED", str(exc))

    return values


def backend_values(verifier: Verification) -> dict[str, Any]:
    values: dict[str, Any] = {}
    try:
        values["health"] = request_json("GET", "/health")
        health = values["health"]
        live = health.get("mode") == "oci" and health.get("auth") == "instance_principal"
        print("Health:")
        verifier.pass_fail("Live OCI mode", live, f"mode={health.get('mode')} auth={health.get('auth')}")
    except Exception as exc:
        print("Health:")
        verifier.line("Live OCI mode", "NOT VERIFIED", str(exc))

    params = query_string({"region": REGION, "compartment_id": COMPARTMENT_ID, "availability_domain": AVAILABILITY_DOMAIN})
    try:
        values["capacity_before"] = request_json("GET", f"/capacity?{params}")
    except Exception as exc:
        values["capacity_before_error"] = str(exc)

    try:
        values["capacity"] = request_json("POST", f"/capacity/refresh?{params}")
        cache = values["capacity"].get("cache", {})
        status = cache.get("status")
        age = safe_number(cache.get("age_seconds"))
        ttl = safe_number(cache.get("ttl_seconds"))
        fresh = status in {"fresh", "synthetic"} and age is not None and ttl is not None and age <= ttl
        print()
        print("Cache:")
        verifier.pass_fail("Fresh", fresh if status != "synthetic" else False, f"status={status} age={cache.get('age_seconds')}s")
        print(f"TTL {cache.get('ttl_seconds')}s")
    except Exception as exc:
        print()
        print("Cache:")
        verifier.line("Fresh", "NOT VERIFIED", str(exc))

    payloads = {
        "compute": {
            "service": "compute",
            "operation": {
                "operation": "create_instances",
                "resource_type": "instance",
                "region": REGION,
                "availability_domain": AVAILABILITY_DOMAIN,
                "compartment_id": COMPARTMENT_ID,
                "workload": {
                    "shape": COMPUTE_SHAPE,
                    "instance_count": COMPUTE_INSTANCE_COUNT,
                    "ocpus_per_instance": COMPUTE_OCPUS_PER_INSTANCE,
                    "memory_gb_per_instance": COMPUTE_MEMORY_GB_PER_INSTANCE,
                },
            },
        },
        "block_volume": {
            "service": "block-storage",
            "operation": {
                "operation": "create_volumes",
                "resource_type": "volume",
                "region": REGION,
                "availability_domain": AVAILABILITY_DOMAIN,
                "compartment_id": COMPARTMENT_ID,
                "workload": {"volume_count": BLOCK_VOLUME_COUNT, "size_gb_each": BLOCK_VOLUME_SIZE_GB_EACH},
            },
        },
        "nlb": {
            "service": "network-load-balancer-api",
            "operation": {
                "operation": "create_network_load_balancers",
                "resource_type": "network_load_balancer",
                "region": REGION,
                "compartment_id": COMPARTMENT_ID,
                "workload": {"nlb_count": NLB_COUNT},
            },
        },
    }
    for key, payload in payloads.items():
        try:
            values[f"{key}_preflight"] = request_json("POST", "/preflight", payload)
        except Exception as exc:
            values[f"{key}_preflight_error"] = str(exc)
    return values


def compare_capacity(verifier: Verification, direct: dict[str, Any], backend: dict[str, Any]) -> None:
    capacity = backend.get("capacity") or {}
    print()
    print("Compute:")
    compare_row(verifier, "E5 OCPU limit", direct.get("compute_ocpu"), row_for(capacity, "compute", "standard-e5-core-count"), "limit")
    compare_row(verifier, "E5 OCPU usage", direct.get("compute_ocpu"), row_for(capacity, "compute", "standard-e5-core-count"), "used")
    compare_row(verifier, "E5 OCPU available", direct.get("compute_ocpu"), row_for(capacity, "compute", "standard-e5-core-count"), "available")
    compare_row(verifier, "E5 memory limit", direct.get("compute_memory"), row_for(capacity, "compute", "standard-e5-memory-count"), "limit")
    compare_row(verifier, "E5 memory available", direct.get("compute_memory"), row_for(capacity, "compute", "standard-e5-memory-count"), "available")
    compare_quota(verifier, direct, backend.get("compute_preflight") or {})

    print()
    print("Block Volume:")
    compare_row(verifier, "Volume count", direct.get("block_volume_count"), row_for(capacity, "block-storage", "volume-count"), "available")
    compare_row(verifier, "Storage", direct.get("block_volume_storage"), row_for(capacity, "block-storage", "total-storage-gb"), "available")

    print()
    print("NLB:")
    compare_row(verifier, "NLB count", direct.get("nlb_count"), row_for(capacity, "network-load-balancer-api", "max-nlb-flexible-count"), "available")


def compare_row(verifier: Verification, label: str, direct: dict[str, Any] | None, row: dict[str, Any] | None, metric: str) -> None:
    if not direct or direct.get("error"):
        verifier.line(label, "NOT VERIFIED", (direct or {}).get("error", "Missing direct OCI value."))
        return
    if not row:
        verifier.line(label, "NOT VERIFIED", "Missing backend capacity row.")
        return
    backend_value = row.get("limit_value") if metric == "limit" else row.get("current_usage") if metric == "used" else row.get("available")
    direct_value = direct.get(metric)
    ok = same_number(direct_value, backend_value)
    verifier.pass_fail(label, ok, f"OCI={direct_value} backend={backend_value}")


def compare_quota(verifier: Verification, direct: dict[str, Any], compute_preflight: dict[str, Any]) -> None:
    quota_entries = direct.get("quotas", {}).get(("compute", "standard-e5-core-count"), [])
    quota_check = check_for(compute_preflight, "COMPARTMENT_QUOTA", "standard-e5-core-count")
    if not quota_entries and not quota_check:
        verifier.line("Compute quota", "NOT VERIFIED", "No applicable Compute E5 OCPU quota statement/check found.")
        return
    if not quota_entries or not quota_check:
        verifier.pass_fail("Compute quota", False, f"direct_quota={bool(quota_entries)} backend_quota={bool(quota_check)}")
        return
    direct_quota = quota_entries[0]["value"]
    ok = same_number(direct_quota, quota_check.get("maximum"))
    verifier.pass_fail("Compute quota", ok, f"OCI quota={direct_quota} backend quota={quota_check.get('maximum')}")


def verify_calculated_values(verifier: Verification, direct: dict[str, Any], backend: dict[str, Any]) -> None:
    print()
    print("Calculated values:")
    compute = backend.get("compute_preflight") or {}
    checks = compute.get("checks") or []
    ocpu_check = next((item for item in checks if item.get("limit_name") == "standard-e5-core-count" and item.get("metric") == "ocpus"), None)
    quota_check = check_for(compute, "COMPARTMENT_QUOTA", "standard-e5-core-count")
    requested_ocpus = COMPUTE_INSTANCE_COUNT * COMPUTE_OCPUS_PER_INSTANCE
    verifier.pass_fail("Requested OCPUs", same_number(requested_ocpus, (ocpu_check or {}).get("requested_delta")), f"expected={requested_ocpus} backend={(ocpu_check or {}).get('requested_delta')}")
    if ocpu_check:
        projected = safe_number(ocpu_check.get("current")) + safe_number(ocpu_check.get("requested_delta")) if safe_number(ocpu_check.get("current")) is not None and safe_number(ocpu_check.get("requested_delta")) is not None else None
        verifier.pass_fail("Projected OCPU usage", same_number(projected, ocpu_check.get("projected")), f"expected={projected} backend={ocpu_check.get('projected')}")
    else:
        verifier.line("Projected OCPU usage", "NOT VERIFIED", "Missing OCPU check.")
    known_available = [safe_number(item.get("available")) for item in checks if safe_number(item.get("available")) is not None and item.get("status") != "STALE"]
    expected_effective = min(known_available) if known_available and compute.get("decision") != "UNKNOWN" else None
    verifier.pass_fail("Effective available capacity", same_number(expected_effective, compute.get("effective_available_capacity")), f"expected={expected_effective} backend={compute.get('effective_available_capacity')}")
    if quota_check:
        projected = safe_number(quota_check.get("current")) + safe_number(quota_check.get("requested_delta")) if safe_number(quota_check.get("current")) is not None and safe_number(quota_check.get("requested_delta")) is not None else None
        expected_shortfall = projected - safe_number(quota_check.get("maximum")) if projected is not None and safe_number(quota_check.get("maximum")) is not None and projected > safe_number(quota_check.get("maximum")) else None
        verifier.pass_fail("Quota shortfall", same_number(expected_shortfall, quota_check.get("shortfall")), f"expected={expected_shortfall} backend={quota_check.get('shortfall')}")
        verifier.pass_fail("Compute quota causes BLOCK", compute.get("decision") == "BLOCK" and compute.get("primary_blocking_constraint") == "COMPARTMENT_QUOTA", f"decision={compute.get('decision')} primary={compute.get('primary_blocking_constraint')}")
    else:
        verifier.line("Quota shortfall", "NOT VERIFIED", "Missing Compute quota check.")
        verifier.line("Compute quota causes BLOCK", "NOT VERIFIED", "Missing Compute quota check.")


def verify_synthetic(verifier: Verification, backend: dict[str, Any]) -> None:
    print()
    print("Backend reconciliation:")
    capacity = backend.get("capacity") or {}
    rows = capacity.get("capacity") or []
    health = backend.get("health") or {}
    synthetic = capacity.get("cache", {}).get("status") == "synthetic" or any(row.get("data_status") == "SYNTHETIC" for row in rows)
    live = health.get("mode") == "oci" and not synthetic
    verifier.pass_fail("OCI -> API", live, f"mode={health.get('mode')} cache={capacity.get('cache', {}).get('status')}")
    verifier.pass_fail("API -> UI/source", live and bool(rows), f"capacity_rows={len(rows)}")
    print()
    print("Synthetic fallback:")
    verifier.pass_fail("NONE FOUND", not synthetic)


def main() -> int:
    verifier = Verification()
    try:
        clients = build_oci_clients(
            auth="instance_principal",
            region=REGION,
            quota_region=QUOTA_REGION,
            tenancy_id=TENANCY_ID_ENV,
        )
    except Exception as exc:
        print("# LIVE DATA PROVENANCE")
        print()
        print("Authentication:")
        verifier.line("Instance Principal", "NOT VERIFIED", str(exc))
        print()
        print("OVERALL:")
        print("NOT VERIFIED")
        return 2

    tenancy_id = TENANCY_ID_ENV or clients.tenancy_id
    print_config(clients, verifier)
    direct = direct_oci_values(clients, tenancy_id, verifier)
    backend = backend_values(verifier)
    compare_capacity(verifier, direct, backend)
    verify_calculated_values(verifier, direct, backend)
    verify_synthetic(verifier, backend)

    print()
    print("OVERALL:")
    if verifier.failures == 0 and verifier.not_verified == 0:
        print("LIVE TENANCY DATA VERIFIED")
        return 0
    if verifier.failures:
        print("FAIL")
        return 1
    print("NOT VERIFIED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
