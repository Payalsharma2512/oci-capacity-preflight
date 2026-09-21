from __future__ import annotations

import types
import unittest
from datetime import datetime, timedelta, timezone

from src.adapters import BlockVolumeAdapter, ComputeAdapter, ServiceAdapterRegistry
from src.block_volume import BlockVolumeLimitResolver
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapacitySnapshot, Decision
from src.discovery import OciLimitDiscovery
from src.limits.oci_limits_provider import OciLimitsProvider
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.oci_usage_provider import ResourceAvailabilityUsageProvider


class Response:
    def __init__(self, data):
        self.data = data
        self.headers = {}


class BlockVolumeLimitsClient:
    def __init__(self, availability=None):
        self.availability = availability or {
            "volume-count": (0, 10000),
            "total-storage-gb": (147, 60225),
            "total-replica-storage-gb": (0, 256000),
            "backup-count": (0, 99999),
        }

    def list_services(self, *_args, **_kwargs):
        return Response([types.SimpleNamespace(name="block-storage", description="Block Volume")])

    def list_limit_definitions(self, _tenancy, service_name, **_kwargs):
        self.assert_service(service_name)
        return Response([
            types.SimpleNamespace(name="volume-count", description="Volume Count", scope_type="AD"),
            types.SimpleNamespace(name="total-storage-gb", description="Volume Size (GB)", scope_type="AD"),
            types.SimpleNamespace(name="total-replica-storage-gb", description="total-replica-storage-gb", scope_type="AD"),
            types.SimpleNamespace(name="backup-count", description="Backup Count", scope_type="REGION"),
        ])

    def list_limit_values(self, _tenancy, service_name, **_kwargs):
        self.assert_service(service_name)
        return Response([types.SimpleNamespace(name=name, value=used + available) for name, (used, available) in self.availability.items()])

    def get_resource_availability(self, service_name, limit_name, _compartment_id, **kwargs):
        self.assert_service(service_name)
        if limit_name in {"volume-count", "total-storage-gb", "total-replica-storage-gb"} and "availability_domain" not in kwargs:
            raise ValueError("availability_domain is required")
        used, available = self.availability[limit_name]
        return Response(types.SimpleNamespace(used=used, available=available))

    def assert_service(self, service_name):
        if service_name != "block-storage":
            raise AssertionError(f"expected block-storage, got {service_name}")


class QuotasClient:
    def __init__(self, statements=None, error=None):
        self.statements = statements or []
        self.error = error

    def list_quotas(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return Response([types.SimpleNamespace(statements=self.statements)])


def payload(count=5, size=2048, ad="AD-1"):
    return {
        "service": "blockvolume",
        "operation": {
            "operation": "create_volumes",
            "region": "us-ashburn-1",
            "availability_domain": ad,
            "compartment_id": "compartment",
            "workload": {"volume_count": count, "size_gb_each": size},
        },
    }


def run_block_volume(payload_data, limits_client, quotas_client=None):
    adapter = BlockVolumeAdapter()
    operation, mapping = adapter.workload_from_payload(payload_data, BlockVolumeLimitResolver(limits_client, "tenancy"))
    usage = ResourceAvailabilityUsageProvider(limits_client, mapping)
    providers = [OciLimitsProvider(limits_client, "tenancy", mapping)]
    if quotas_client:
        providers.append(OciQuotaProvider(quotas_client, "tenancy", usage))
    return operation, mapping, CapacityDecisionEngine(providers).preflight(operation)


class BlockVolumePreflightTests(unittest.TestCase):
    def test_volume_count_and_total_gb_calculation(self):
        operation, mapping, result = run_block_volume(payload(), BlockVolumeLimitsClient())

        self.assertEqual(operation.service, "block-storage")
        self.assertEqual(operation.requested_delta["volume_count"], 5)
        self.assertEqual(operation.requested_delta["storage_gb"], 10240)
        self.assertEqual(mapping["block-storage"]["volume_count"], "volume-count")
        self.assertEqual(mapping["block-storage"]["storage_gb"], "total-storage-gb")
        self.assertEqual(result.decision, Decision.PASS)

    def test_single_volume(self):
        operation, _mapping, result = run_block_volume(payload(count=1, size=50), BlockVolumeLimitsClient())

        self.assertEqual(operation.requested_delta, {"volume_count": 1.0, "storage_gb": 50.0})
        self.assertEqual(result.decision, Decision.PASS)

    def test_exact_boundary_passes(self):
        limits = BlockVolumeLimitsClient({"volume-count": (0, 5), "total-storage-gb": (0, 10240), "total-replica-storage-gb": (0, 1)})

        _operation, _mapping, result = run_block_volume(payload(), limits)

        self.assertEqual(result.decision, Decision.PASS)

    def test_boundary_plus_one_blocks(self):
        limits = BlockVolumeLimitsClient({"volume-count": (0, 5), "total-storage-gb": (0, 10239), "total-replica-storage-gb": (0, 1)})

        _operation, _mapping, result = run_block_volume(payload(), limits)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_service_limit_block(self):
        limits = BlockVolumeLimitsClient({"volume-count": (0, 4), "total-storage-gb": (0, 20000), "total-replica-storage-gb": (0, 1)})

        _operation, _mapping, result = run_block_volume(payload(), limits)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertTrue(any(check.limit_name == "volume-count" for check in result.checks if check.status.value == "WOULD_EXCEED"))

    def test_quota_block(self):
        quotas = QuotasClient(["Set block-storage quota total-storage-gb to 1000 in compartment Production"])

        _operation, _mapping, result = run_block_volume(payload(count=1, size=2048), BlockVolumeLimitsClient(), quotas)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")

    def test_quota_missing_permission_is_unable_to_validate(self):
        quotas = QuotasClient(error=PermissionError("403 Forbidden"))

        _operation, _mapping, result = run_block_volume(payload(count=1, size=1), BlockVolumeLimitsClient(), quotas)

        self.assertEqual(result.decision, Decision.UNKNOWN)
        self.assertIn("quota could not be evaluated", result.unknown_reasons[0].lower())

    def test_missing_ad_for_ad_scoped_limit_is_unable_to_validate(self):
        _operation, _mapping, result = run_block_volume(payload(ad=None), BlockVolumeLimitsClient())

        self.assertEqual(result.decision, Decision.UNKNOWN)
        self.assertIn("availability_domain is required", " ".join(result.unknown_reasons))

    def test_invalid_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "volume_count"):
            BlockVolumeAdapter().workload_from_payload(payload(count=0), BlockVolumeLimitResolver(BlockVolumeLimitsClient(), "tenancy"))

    def test_unsupported_limit_mapping_is_unable_to_validate(self):
        class AmbiguousClient(BlockVolumeLimitsClient):
            def list_limit_definitions(self, _tenancy, service_name, **_kwargs):
                self.assert_service(service_name)
                return Response([
                    types.SimpleNamespace(name="volume-count-a", description="Volume Count", scope_type="AD"),
                    types.SimpleNamespace(name="volume-count-b", description="Volume Count", scope_type="AD"),
                    types.SimpleNamespace(name="total-storage-gb", description="Volume Size (GB)", scope_type="AD"),
                ])

        with self.assertRaisesRegex(ValueError, "could not reliably map"):
            BlockVolumeAdapter().workload_from_payload(payload(), BlockVolumeLimitResolver(AmbiguousClient(), "tenancy"))

    def test_stale_data_is_unknown(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        operation = BlockVolumeAdapter().operation_from_payload({
            "operation": {
                "region": "us-ashburn-1",
                "availability_domain": "AD-1",
                "compartment_id": "compartment",
                "requested": {"volume_count": 1, "storage_gb": 1},
            }
        })
        result = CapacityDecisionEngine([
            types.SimpleNamespace(
                evaluate=lambda _op: [CapacitySnapshot("SERVICE_LIMIT", "block-storage", "volume-count", "AD-1", "volume_count", 0, 10, 10, timestamp=old, stale_after_seconds=1)],
                remediation=lambda _snapshot: {"action": "REQUEST_LIMIT_INCREASE", "reason": "stale"},
            )
        ]).preflight(operation)

        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_discovery_marks_dynamic_block_volume_limits_full_preflight(self):
        discovery = OciLimitDiscovery(BlockVolumeLimitsClient(), "tenancy", ServiceAdapterRegistry([ComputeAdapter(), BlockVolumeAdapter()]))

        limits = {item.limit_name: item for item in discovery.list_limits("block-storage", "compartment", "AD-1", "us-ashburn-1")}

        self.assertEqual(limits["volume-count"].capability.value, "FULL_PREFLIGHT")
        self.assertEqual(limits["total-storage-gb"].capability.value, "FULL_PREFLIGHT")
        self.assertEqual(limits["backup-count"].capability.value, "MONITOR_ONLY")

    def test_adapter_isolated_from_compute(self):
        registry = ServiceAdapterRegistry([ComputeAdapter(), BlockVolumeAdapter()])

        self.assertIsInstance(registry.get("compute"), ComputeAdapter)
        self.assertIsInstance(registry.get("blockvolume"), BlockVolumeAdapter)
        self.assertNotEqual(registry.get("compute").service, registry.get("blockvolume").service)


if __name__ == "__main__":
    unittest.main()
