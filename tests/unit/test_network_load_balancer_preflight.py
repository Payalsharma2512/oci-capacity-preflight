from __future__ import annotations

import types
import unittest
from datetime import datetime, timedelta, timezone

from src.adapters import BlockVolumeAdapter, ComputeAdapter, NetworkLoadBalancerAdapter, ServiceAdapterRegistry
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapacitySnapshot, Decision
from src.discovery import OciLimitDiscovery
from src.limits.oci_limits_provider import OciLimitsProvider
from src.network_load_balancer import NetworkLoadBalancerLimitResolver
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


class Response:
    def __init__(self, data):
        self.data = data
        self.headers = {}


class NlbLimitsClient:
    def __init__(self, used=0, available=8, availability_error=None):
        self.used = used
        self.available = available
        self.availability_error = availability_error

    def list_services(self, *_args, **_kwargs):
        return Response([types.SimpleNamespace(name="network-load-balancer-api", description="Network Load Balancer")])

    def list_limit_definitions(self, _tenancy, service_name, **_kwargs):
        if service_name != "network-load-balancer-api":
            raise AssertionError(service_name)
        return Response([
            types.SimpleNamespace(name="max-nlb-flexible-count", description="Flexible Network Load Balancer Count", scope_type="REGION"),
            types.SimpleNamespace(name="nlb-backends-count", description="Backends per NLB", scope_type="REGION"),
        ])

    def list_limit_values(self, _tenancy, service_name, **_kwargs):
        if service_name != "network-load-balancer-api":
            raise AssertionError(service_name)
        return Response([
            types.SimpleNamespace(name="max-nlb-flexible-count", value=self.used + self.available),
            types.SimpleNamespace(name="nlb-backends-count", value=100),
        ])

    def get_resource_availability(self, service_name, limit_name, _compartment_id, **_kwargs):
        if service_name != "network-load-balancer-api":
            raise AssertionError(service_name)
        if self.availability_error:
            raise self.availability_error
        if limit_name == "max-nlb-flexible-count":
            return Response(types.SimpleNamespace(used=self.used, available=self.available))
        if limit_name == "nlb-backends-count":
            return Response(types.SimpleNamespace(used=0, available=100))
        raise AssertionError(limit_name)


class QuotasClient:
    def __init__(self, statements=None, error=None):
        self.statements = statements or []
        self.error = error

    def list_quotas(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return Response([types.SimpleNamespace(statements=self.statements)])


def payload(count=5):
    return {
        "service": "nlb",
        "operation": {
            "operation": "create_network_load_balancers",
            "region": "us-ashburn-1",
            "compartment_id": "compartment",
            "workload": {"nlb_count": count},
        },
    }


def run_nlb(payload_data, limits_client, quotas_client=None):
    adapter = NetworkLoadBalancerAdapter()
    operation, mapping = adapter.workload_from_payload(payload_data, NetworkLoadBalancerLimitResolver(limits_client, "tenancy"))
    usage = ResourceAvailabilityUsageProvider(limits_client, mapping)
    providers = [OciLimitsProvider(limits_client, "tenancy", mapping)]
    if quotas_client:
        providers.append(OciQuotaProvider(quotas_client, "tenancy", usage))
    return operation, mapping, CapacityDecisionEngine(providers).preflight(operation)


class NetworkLoadBalancerPreflightTests(unittest.TestCase):
    def test_nlb_count_pass(self):
        operation, mapping, result = run_nlb(payload(5), NlbLimitsClient())

        self.assertEqual(operation.service, "network-load-balancer-api")
        self.assertEqual(operation.requested_delta, {"nlb_count": 5.0})
        self.assertEqual(mapping["network-load-balancer-api"]["nlb_count"], "max-nlb-flexible-count")
        self.assertEqual(result.decision, Decision.PASS)

    def test_nlb_count_block(self):
        _operation, _mapping, result = run_nlb(payload(9), NlbLimitsClient(used=0, available=8))

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_exact_boundary_passes(self):
        _operation, _mapping, result = run_nlb(payload(8), NlbLimitsClient(used=0, available=8))

        self.assertEqual(result.decision, Decision.PASS)

    def test_boundary_plus_one_blocks_with_shortfall_one(self):
        _operation, _mapping, result = run_nlb(payload(9), NlbLimitsClient(used=0, available=8))

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual([check.shortfall for check in result.checks if check.status.value == "WOULD_EXCEED"], [1])

    def test_quota_block(self):
        quotas = QuotasClient(["Set network-load-balancer-api quota max-nlb-flexible-count to 3 in compartment Production"])

        _operation, _mapping, result = run_nlb(payload(5), NlbLimitsClient(), quotas)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")

    def test_quota_permission_failure_is_unable_to_validate(self):
        quotas = QuotasClient(error=PermissionError("403 Forbidden"))

        _operation, _mapping, result = run_nlb(payload(1), NlbLimitsClient(), quotas)

        self.assertEqual(result.decision, Decision.UNKNOWN)
        self.assertIn("quota could not be evaluated", result.unknown_reasons[0].lower())

    def test_scope_is_region(self):
        _operation, _mapping, result = run_nlb(payload(1), NlbLimitsClient())

        self.assertEqual(result.checks[0].scope, "us-ashburn-1")

    def test_missing_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nlb_count"):
            NetworkLoadBalancerAdapter().workload_from_payload({"service": "nlb", "operation": {"region": "us-ashburn-1", "compartment_id": "compartment", "workload": {}}}, NetworkLoadBalancerLimitResolver(NlbLimitsClient(), "tenancy"))

    def test_invalid_count_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nlb_count >= 1"):
            NetworkLoadBalancerAdapter().workload_from_payload(payload(0), NetworkLoadBalancerLimitResolver(NlbLimitsClient(), "tenancy"))

    def test_stale_data_is_unknown(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        operation = NetworkLoadBalancerAdapter().operation_from_payload({
            "operation": {
                "region": "us-ashburn-1",
                "compartment_id": "compartment",
                "requested": {"nlb_count": 1},
            }
        })
        result = CapacityDecisionEngine([
            types.SimpleNamespace(
                evaluate=lambda _op: [CapacitySnapshot("SERVICE_LIMIT", "network-load-balancer-api", "max-nlb-flexible-count", "us-ashburn-1", "nlb_count", 0, 8, 8, timestamp=old, stale_after_seconds=1)],
                remediation=lambda _snapshot: {"action": "REQUEST_LIMIT_INCREASE", "reason": "stale"},
            )
        ]).preflight(operation)

        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_unavailable_limit_information_is_unknown(self):
        _operation, _mapping, result = run_nlb(payload(1), NlbLimitsClient(availability_error=RuntimeError("limit unavailable")))

        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_unsupported_limit_mapping_is_unable_to_validate(self):
        class AmbiguousClient(NlbLimitsClient):
            def list_limit_definitions(self, _tenancy, service_name, **_kwargs):
                return Response([
                    types.SimpleNamespace(name="max-nlb-flexible-count-a", description="Flexible Network Load Balancer Count", scope_type="REGION"),
                    types.SimpleNamespace(name="max-nlb-flexible-count-b", description="Flexible Network Load Balancer Count", scope_type="REGION"),
                ])

        with self.assertRaisesRegex(ValueError, "could not reliably map"):
            NetworkLoadBalancerAdapter().workload_from_payload(payload(1), NetworkLoadBalancerLimitResolver(AmbiguousClient(), "tenancy"))

    def test_adapter_isolated_from_compute_and_block_volume(self):
        registry = ServiceAdapterRegistry([ComputeAdapter(), BlockVolumeAdapter(), NetworkLoadBalancerAdapter()])

        self.assertIsInstance(registry.get("compute"), ComputeAdapter)
        self.assertIsInstance(registry.get("blockvolume"), BlockVolumeAdapter)
        self.assertIsInstance(registry.get("nlb"), NetworkLoadBalancerAdapter)

    def test_other_nlb_limits_remain_monitor_only(self):
        discovery = OciLimitDiscovery(NlbLimitsClient(), "tenancy", ServiceAdapterRegistry([NetworkLoadBalancerAdapter()]))

        limits = {item.limit_name: item for item in discovery.list_limits("network-load-balancer-api", "compartment", None, "us-ashburn-1")}

        self.assertEqual(limits["max-nlb-flexible-count"].capability.value, "FULL_PREFLIGHT")
        self.assertEqual(limits["nlb-backends-count"].capability.value, "MONITOR_ONLY")


if __name__ == "__main__":
    unittest.main()
