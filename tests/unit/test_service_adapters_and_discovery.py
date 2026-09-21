from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from src.adapters import ComputeAdapter, ServiceAdapterRegistry
from src.api.app import operation_for_payload
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapabilityLevel, CapacitySnapshot, Decision, Operation
from src.discovery import OciLimitDiscovery
from src.preflight.demo_data import StaticCapacityProvider


class Response:
    def __init__(self, data):
        self.data = data
        self.headers = {}


class DiscoveryClient:
    def list_services(self, _tenancy, **_kwargs):
        return Response([
            types.SimpleNamespace(name="compute", description="Compute"),
            types.SimpleNamespace(name="block-storage", description="Block Storage"),
        ])

    def list_limit_definitions(self, _tenancy, service_name, **_kwargs):
        definitions = {
            "compute": [
                types.SimpleNamespace(name="standard-e4-core-count", description="E4 cores", scope_type="REGION"),
                types.SimpleNamespace(name="standard-e5-core-count", description="Cores for E5 based VM and BM Instances", scope_type="AD"),
                types.SimpleNamespace(name="standard-e5-memory-count", description="Memory for E5 based VM and BM Instances", scope_type="AD"),
            ],
            "block-storage": [types.SimpleNamespace(name="volume-count", description="Volumes", scope_type="REGION")],
        }
        return Response(definitions[service_name])

    def list_limit_values(self, _tenancy, service_name, page=None):
        values = {
            "compute": [
                types.SimpleNamespace(name="standard-e4-core-count", value=300),
                types.SimpleNamespace(name="standard-e5-core-count", value=300),
                types.SimpleNamespace(name="standard-e5-memory-count", value=4500),
            ],
            "block-storage": [types.SimpleNamespace(name="volume-count", value=50)],
        }
        return Response(values[service_name])

    def get_resource_availability(self, service_name, limit_name, _compartment_id, **_kwargs):
        if service_name == "compute" and limit_name == "standard-e4-core-count":
            return Response(types.SimpleNamespace(used=5, available=295))
        if service_name == "compute" and limit_name == "standard-e5-core-count":
            return Response(types.SimpleNamespace(used=5, available=295))
        if service_name == "compute" and limit_name == "standard-e5-memory-count":
            return Response(types.SimpleNamespace(used=50, available=4450))
        if service_name == "block-storage" and limit_name == "volume-count":
            return Response(types.SimpleNamespace(used=10, available=40))
        raise RuntimeError("unsupported")


class ShapeDiscoveryClient:
    def list_shapes(self, compartment_id, **_kwargs):
        return Response([
            types.SimpleNamespace(
                shape="VM.Standard.E5.Flex",
                ocpus=1,
                memory_in_gbs=16,
                gpus=0,
                quota_names=["standard-e5-core-count", "standard-e5-memory-count"],
                shape_config_options={"ocpu_options": {"min": 1, "max": 126}},
            )
        ])


class AdapterDiscoveryTests(unittest.TestCase):
    def test_compute_adapter_translates_customer_intent_to_ocpus(self):
        operation = ComputeAdapter().operation_from_payload({
            "operation": {
                "service": "compute",
                "resource_type": "instance",
                "region": "us-ashburn-1",
                "availability_domain": "AD-1",
                "compartment_id": "compartment",
                "requested": {"ocpus": 14},
            }
        })

        self.assertEqual(operation.service, "compute")
        self.assertEqual(operation.requested_delta, {"ocpus": 14.0})

    def test_operation_from_dict_accepts_generic_nested_api_shape(self):
        operation = Operation.from_dict({
            "service": "database",
            "operation": {
                "resource_type": "system",
                "region": "us-ashburn-1",
                "compartment_id": "compartment",
                "requested": {"storage_gb": 50},
            },
        })

        self.assertEqual(operation.service, "database")
        self.assertEqual(operation.requested_delta, {"storage_gb": 50.0})

    def test_discovery_classifies_adapter_backed_limit_as_full_preflight(self):
        discovery = OciLimitDiscovery(DiscoveryClient(), "tenancy", ServiceAdapterRegistry([ComputeAdapter()]))

        limits = discovery.list_limits("compute", "compartment")

        self.assertEqual(limits[0].capability, CapabilityLevel.FULL_PREFLIGHT)
        self.assertEqual(limits[0].available, 295)

    def test_discovery_classifies_shape_resolved_compute_limits_as_full_preflight(self):
        discovery = OciLimitDiscovery(
            DiscoveryClient(),
            "tenancy",
            ServiceAdapterRegistry([ComputeAdapter()]),
            compute_client=ShapeDiscoveryClient(),
        )

        limits = {limit.limit_name: limit for limit in discovery.list_limits("compute", "compartment", "AD-1")}

        self.assertEqual(limits["standard-e5-core-count"].capability, CapabilityLevel.FULL_PREFLIGHT)
        self.assertEqual(limits["standard-e5-memory-count"].capability, CapabilityLevel.FULL_PREFLIGHT)

    def test_discovery_classifies_visible_unmapped_limit_as_monitor_only(self):
        discovery = OciLimitDiscovery(DiscoveryClient(), "tenancy", ServiceAdapterRegistry([ComputeAdapter()]))

        limits = discovery.list_limits("block-storage", "compartment")

        self.assertEqual(limits[0].capability, CapabilityLevel.MONITOR_ONLY)
        self.assertIn("no verified operation adapter", limits[0].reason)

    def test_monitor_only_snapshot_does_not_return_false_pass(self):
        operation = Operation("block-storage", "volume", "us-ashburn-1", "compartment", {"count": 1})
        provider = StaticCapacityProvider([
            CapacitySnapshot(
                "SERVICE_LIMIT",
                "block-storage",
                "volume-count",
                "us-ashburn-1",
                "count",
                10,
                50,
                40,
                capability=CapabilityLevel.MONITOR_ONLY,
            )
        ])

        result = CapacityDecisionEngine([provider]).preflight(operation)

        self.assertEqual(result.decision, Decision.UNKNOWN)
        self.assertIn("MONITOR_ONLY", result.unknown_reasons[0])

    def test_generic_engine_supports_non_compute_units(self):
        operation = Operation("database", "system", "us-ashburn-1", "compartment", {"storage_gb": 50})
        provider = StaticCapacityProvider([
            CapacitySnapshot("SERVICE_LIMIT", "database", "storage-count", "us-ashburn-1", "storage_gb", 100, 200, 100, unit="GB")
        ])

        result = CapacityDecisionEngine([provider]).preflight(operation)

        self.assertEqual(result.decision, Decision.PASS)
        self.assertEqual(result.checks[0].unit, "GB")

    def test_generic_discovered_limit_payload_maps_to_selected_oci_limit(self):
        payload = {
            "service": "database",
            "operation": {
                "operation": "check_discovered_limit",
                "region": "us-ashburn-1",
                "compartment_id": "compartment",
                "limit_name": "database-count",
                "requested": {"units": 2},
            },
        }

        with patch.dict("os.environ", {"OCI_CAPACITY_PREFLIGHT_MODE": "oci"}):
            operation = operation_for_payload(payload)

        self.assertEqual(operation.service, "database")
        self.assertEqual(operation.requested_delta, {"units": 2.0})
        self.assertEqual(payload["_resolved_limit_mapping"], {"database": {"units": "database-count"}})


if __name__ == "__main__":
    unittest.main()
