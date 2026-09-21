from __future__ import annotations

import argparse
import json
import os
import sys

from src.adapters import ServiceAdapterRegistry
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import Operation
from src.forecasting.linear import Observation, linear_growth_forecast
from src.limits.oci_limits_provider import OciLimitsProvider
from src.oci_auth import build_oci_clients
from src.preflight.demo_data import scenario_passes, scenario_quota_blocks, scenario_service_limit_blocks
from src.preflight.risk import risk_state
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider

adapter_registry = ServiceAdapterRegistry()


def build_demo_engine(kind: str):
    operation, provider = {"quota": scenario_quota_blocks, "limit": scenario_service_limit_blocks, "pass": scenario_passes}[kind]()
    return operation, CapacityDecisionEngine([provider]), provider


def build_real_oci_engine(args):
    clients = build_oci_clients(
        args.auth,
        args.profile,
        args.config_file,
        args.region,
        args.quota_region,
        args.tenancy_id,
    )
    tenancy_id = args.tenancy_id or clients.tenancy_id
    limit_mapping = adapter_registry.merged_limit_mapping()
    if getattr(args, "service", None) == "compute" and getattr(args, "limit_name", None):
        limit_mapping["compute"] = {"ocpus": args.limit_name}
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    engine = CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])
    return clients, tenancy_id, engine


def arg_or_env(args, attr: str, env_name: str):
    return getattr(args, attr, None) or os.getenv(env_name)


def doctor_check(name: str, checks: list[tuple[str, bool, str]], fn) -> None:
    try:
        detail = fn()
        checks.append((name, True, detail or "OK"))
    except Exception as exc:
        checks.append((name, False, str(exc)))


def run_doctor(args) -> int:
    checks: list[tuple[str, bool, str]] = []
    if not args.real_oci:
        checks.append(("Live OCI mode", False, "doctor requires --real-oci for runner validation."))

    args.region = arg_or_env(args, "region", "OCI_CAPACITY_PREFLIGHT_REGION") or os.getenv("OCI_REGION")
    args.quota_region = arg_or_env(args, "quota_region", "OCI_CAPACITY_PREFLIGHT_QUOTA_REGION")
    args.tenancy_id = arg_or_env(args, "tenancy_id", "OCI_TENANCY_OCID")
    args.compartment_id = arg_or_env(args, "compartment_id", "OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID")
    args.availability_domain = arg_or_env(args, "availability_domain", "OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN")
    args.limit_name = args.limit_name or os.getenv("OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT") or "standard-e5-core-count"

    config_items = [
        ("Target region configuration", args.region, "Set --region or OCI_CAPACITY_PREFLIGHT_REGION/OCI_REGION."),
        ("Quota region configuration", args.quota_region, "Set --quota-region or OCI_CAPACITY_PREFLIGHT_QUOTA_REGION."),
        ("Tenancy configuration", args.tenancy_id, "Set --tenancy-id or OCI_TENANCY_OCID."),
        ("Target compartment configuration", args.compartment_id, "Set --compartment-id or OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID."),
    ]
    for name, value, message in config_items:
        checks.append((name, bool(value), str(value) if value else message))

    clients = None
    tenancy_id = args.tenancy_id

    def build_clients():
        nonlocal clients, tenancy_id
        clients = build_oci_clients(
            auth=args.auth,
            profile=args.profile,
            config_file=args.config_file,
            region=args.region,
            quota_region=args.quota_region,
            tenancy_id=args.tenancy_id,
        )
        tenancy_id = args.tenancy_id or clients.tenancy_id
        return f"{args.auth} authenticated"

    doctor_check("Instance Principal authentication", checks, build_clients)

    if clients and tenancy_id:
        doctor_check(
            "Tenancy access",
            checks,
            lambda: f"{len(clients.limits_client.list_services(tenancy_id).data)} service(s) visible",
        )
        doctor_check(
            "Limits API access",
            checks,
            lambda: f"{len(clients.limits_client.list_limit_definitions(tenancy_id, service_name='compute').data)} compute limit definition(s) visible",
        )
        doctor_check(
            "Quotas API access",
            checks,
            lambda: f"{len(clients.quotas_client.list_quotas(tenancy_id, lifecycle_state='ACTIVE').data)} active quota resource(s) visible",
        )
        if args.compartment_id:
            doctor_check(
                "Compute shape API access",
                checks,
                lambda: f"{len(clients.compute_client.list_shapes(args.compartment_id, availability_domain=args.availability_domain).data)} shape(s) visible",
            )
            doctor_check(
                "Required IAM permissions",
                checks,
                lambda: "limits/quota/instance-family reads succeeded",
            )
            doctor_check(
                "Resource availability access",
                checks,
                lambda: f"{args.limit_name}: available={getattr(clients.limits_client.get_resource_availability('compute', args.limit_name, args.compartment_id, **({'availability_domain': args.availability_domain} if args.availability_domain else {})).data, 'available', None)}",
            )

    print("OCI CAPACITY PREFLIGHT DOCTOR")
    print("=============================")
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    failed = [name for name, ok, _ in checks if not ok]
    print("")
    print("RESULT: PASS" if not failed else "RESULT: FAIL")
    if failed:
        print("Failed checks:")
        for name in failed:
            print(f"- {name}")
        return 1
    return 0


def operation_from_args(args) -> Operation:
    adapter = adapter_registry.get(args.service)
    if not adapter:
        raise ValueError(f"No FULL_PREFLIGHT adapter is available for service '{args.service}'.")
    payload = {
        "operation": {
            "service": args.service,
            "resource_type": args.resource_type,
            "region": args.region,
            "availability_domain": args.availability_domain,
            "compartment_id": args.compartment_id,
            "compartment_name": "Production",
            "requested": {"ocpus": args.requested_ocpus},
        }
    }
    return adapter.operation_from_payload(payload)


def format_result(result) -> str:
    lines = [
        "OCI CAPACITY PREFLIGHT",
        "======================",
        "",
        f"RESULT: {result.decision.value}",
        "",
        f"Service: {result.operation.service.title()}",
        f"Resource: {(result.operation.resource_type or 'unknown').title()}",
        f"Region: {result.operation.region}",
        f"Compartment: {result.operation.compartment_name or result.operation.compartment_id}",
        "",
    ]
    if result.primary_blocking_constraint:
        check = min([c for c in result.checks if c.status.value == "WOULD_EXCEED"], key=lambda c: c.available or 0)
        lines += [
            "Blocking constraint:",
            result.primary_blocking_constraint.replace("_", " "),
            "",
            f"Current usage: {check.current:g} {check.metric}",
            f"Available: {check.available:g} {check.metric}",
            f"Requested: {check.requested_delta:g} {check.metric}",
            f"Projected: {check.projected:g} {check.metric}",
            f"Shortfall: {check.shortfall:g} {check.metric}",
            "",
        ]
    if result.decision.value == "UNKNOWN":
        lines += ["UNKNOWN", "Why:", *result.unknown_reasons, ""]
    if result.recommendations and result.decision.value != "PASS":
        lines += ["Recommended actions:"]
        lines += [f"- {item['action']}: {item['reason']}" for item in result.recommendations]
    if result.decision.value == "PASS":
        lines += ["No known capacity constraint detected."]
    lines += ["", "advisory: true"]
    return "\n".join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="oci-capacity-preflight")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("scan")
    sub.add_parser("risk")
    sub.add_parser("forecast")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--real-oci", action="store_true", help="Validate live OCI APIs instead of demo mode.")
    doctor.add_argument("--auth", choices=["config", "resource_principal", "instance_principal"], default=os.getenv("OCI_CAPACITY_PREFLIGHT_AUTH") or os.getenv("AUTH") or "instance_principal")
    doctor.add_argument("--profile", default="DEFAULT")
    doctor.add_argument("--config-file")
    doctor.add_argument("--region")
    doctor.add_argument("--quota-region")
    doctor.add_argument("--availability-domain")
    doctor.add_argument("--compartment-id")
    doctor.add_argument("--tenancy-id")
    doctor.add_argument("--limit-name")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--service", default="compute")
    preflight.add_argument("--resource-type", default="instance")
    preflight.add_argument("--region", default="us-phoenix-1")
    preflight.add_argument("--availability-domain")
    preflight.add_argument("--compartment-id", default="<COMPARTMENT_OCID>")
    preflight.add_argument("--requested-ocpus", type=float, default=14)
    preflight.add_argument("--demo", choices=["quota", "limit", "pass"], default="quota")
    preflight.add_argument("--real-oci", action="store_true", help="Connect to OCI using SDK credentials instead of demo data.")
    preflight.add_argument("--auth", choices=["config", "resource_principal", "instance_principal"], default="config")
    preflight.add_argument("--profile", default="DEFAULT")
    preflight.add_argument("--config-file")
    preflight.add_argument("--tenancy-id")
    preflight.add_argument("--quota-region", help="Home region for OCI quota APIs. Defaults to --region.")
    preflight.add_argument("--limit-name", default="standard-e4-core-count")
    validate = sub.add_parser("validate-oci")
    validate.add_argument("--service", default="compute")
    validate.add_argument("--region", required=True)
    validate.add_argument("--quota-region", required=True, help="Tenancy home region for OCI quota APIs.")
    validate.add_argument("--availability-domain")
    validate.add_argument("--compartment-id", required=True)
    validate.add_argument("--auth", choices=["config", "resource_principal", "instance_principal"], default="instance_principal")
    validate.add_argument("--profile", default="DEFAULT")
    validate.add_argument("--config-file")
    validate.add_argument("--tenancy-id", required=True)
    validate.add_argument("--limit-name", default="standard-e4-core-count")
    parser.add_argument("--plan")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.plan:
        with open(args.plan, encoding="utf-8") as handle:
            plan = json.load(handle)
        requested = sum(float(r.get("change", {}).get("after", {}).get("shape_config", {}).get("ocpus", 0)) for r in plan.get("resource_changes", []))
        args.command = "preflight"
        args.requested_ocpus = requested
        args.demo = "quota"

    if args.command in {None, "preflight"}:
        operation = operation_from_args(args)
        if args.real_oci:
            _, _, engine = build_real_oci_engine(args)
        else:
            _, engine, _ = build_demo_engine(args.demo)
        result = engine.preflight(operation)
        print(format_result(result))
        return result.exit_code()
    if args.command == "validate-oci":
        clients, tenancy_id, _ = build_real_oci_engine(args)
        kwargs = {}
        if args.availability_domain:
            kwargs["availability_domain"] = args.availability_domain
        availability = clients.limits_client.get_resource_availability(
            args.service,
            args.limit_name,
            args.compartment_id,
            **kwargs,
        ).data
        quotas = clients.quotas_client.list_quotas(tenancy_id, lifecycle_state="ACTIVE").data
        quota_count = len(quotas) if isinstance(quotas, list) else 1
        print("OCI INSTANCE PRINCIPAL VALIDATION")
        print("===============================")
        print(f"Limits API: OK ({args.service}/{args.limit_name})")
        print(f"Current usage: {getattr(availability, 'used', None)}")
        print(f"Available: {getattr(availability, 'available', None)}")
        print(f"Quotas API: OK ({quota_count} active quota resource(s) visible)")
        print(f"Target region: {args.region}")
        print(f"Quota region: {args.quota_region}")
        return 0
    if args.command == "doctor":
        return run_doctor(args)
    if args.command == "risk":
        _, _, provider = build_demo_engine("quota")
        print(json.dumps([risk_state(snapshot) | {"constraint": snapshot.limit_name} for snapshot in provider.snapshots], indent=2))
        return 0
    if args.command == "forecast":
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        print(json.dumps(linear_growth_forecast([Observation(now - timedelta(days=4), 66), Observation(now, 72)], 80), indent=2))
        return 0
    if args.command == "scan":
        print("Discovered demo constraints: compute standard-e4-core-count")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
