from __future__ import annotations

import argparse
import json
import sys

from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import Operation
from src.forecasting.linear import Observation, linear_growth_forecast
from src.limits.oci_limits_provider import OciLimitsProvider
from src.oci_auth import build_oci_clients
from src.preflight.demo_data import scenario_passes, scenario_quota_blocks, scenario_service_limit_blocks
from src.preflight.risk import risk_state
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


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
    limit_mapping = {args.service: {"ocpus": args.limit_name}}
    usage_provider = ResourceAvailabilityUsageProvider(clients.limits_client, limit_mapping)
    engine = CapacityDecisionEngine([
        OciLimitsProvider(clients.limits_client, tenancy_id, limit_mapping),
        OciQuotaProvider(clients.quotas_client, tenancy_id, usage_provider),
    ])
    return clients, tenancy_id, engine


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
        operation = Operation(args.service, args.resource_type, args.region, args.compartment_id, {"ocpus": args.requested_ocpus}, args.availability_domain, "Production")
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
