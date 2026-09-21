from __future__ import annotations

import types
import unittest

from src.adapters import ComputeAdapter
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapacitySnapshot, Decision, Operation
from src.compute import ComputeShapeProvider, ShapeLimitResolver
from src.preflight.demo_data import StaticCapacityProvider


class Response:
    def __init__(self, data):
        self.data = data
        self.headers = {}


def shape(name, ocpus=None, memory=None, raw=None):
    return types.SimpleNamespace(
        shape=name,
        ocpus=ocpus,
        memory_in_gbs=memory,
        gpus=None,
        processor_description="test",
        to_dict=lambda: raw or {},
    )


class ComputeClient:
    def __init__(self, shapes):
        self.shapes = shapes
        self.calls = []

    def list_shapes(self, compartment_id, **kwargs):
        self.calls.append((compartment_id, kwargs))
        return Response(self.shapes)


class LimitsClient:
    def __init__(self, definitions):
        self.definitions = definitions

    def list_limit_definitions(self, _tenancy, service_name, **_kwargs):
        self.assert_service = service_name
        return Response(self.definitions)


class ComputeShapePreflightTests(unittest.TestCase):
    def payload(self, shape_name="VM.Standard.E5.Flex", count=5, ocpus=4, memory=32):
        return {
            "service": "compute",
            "operation": {
                "operation": "create_instances",
                "region": "us-ashburn-1",
                "availability_domain": "AD-1",
                "compartment_id": "compartment",
                "workload": {
                    "shape": shape_name,
                    "instance_count": count,
                    "ocpus_per_instance": ocpus,
                    "memory_gb_per_instance": memory,
                },
            },
        }

    def adapter_with(self, shapes, definitions):
        return (
            ComputeAdapter(),
            ComputeShapeProvider(ComputeClient(shapes)),
            ShapeLimitResolver(LimitsClient(definitions), "tenancy"),
        )

    def test_flex_shape_calculates_total_ocpus_and_memory(self):
        flex = shape("VM.Standard.E5.Flex", raw={
            "ocpu_options": {"min": 1, "max": 64},
            "memory_options": {"min_in_gbs": 1, "max_in_gbs": 1024},
        })
        definition = types.SimpleNamespace(name="standard-e5-core-count", description="Standard E5 core count", scope_type="REGION")
        adapter, shape_provider, resolver = self.adapter_with([flex], [definition])

        operation, mapping = adapter.workload_from_payload(self.payload(), shape_provider, resolver)

        self.assertEqual(operation.requested_delta["ocpus"], 20)
        self.assertEqual(operation.requested_delta["memory_gb"], 160)
        self.assertEqual(mapping, {"compute": {"ocpus": "standard-e5-core-count"}})
        self.assertEqual(operation.metadata["workload"]["shape"], "VM.Standard.E5.Flex")

    def test_fixed_shape_derives_ocpus_and_memory(self):
        fixed = shape("VM.Standard.E5.4", ocpus=4, memory=64)
        definition = types.SimpleNamespace(name="standard-e5-core-count", description="Standard E5 core count", scope_type="REGION")
        adapter, shape_provider, resolver = self.adapter_with([fixed], [definition])

        operation, _mapping = adapter.workload_from_payload(self.payload("VM.Standard.E5.4", count=2, ocpus=None, memory=None), shape_provider, resolver)

        self.assertEqual(operation.requested_delta["ocpus"], 8)
        self.assertEqual(operation.requested_delta["memory_gb"], 128)

    def test_single_instance_boundary_passes(self):
        operation = Operation("compute", "instance", "us-ashburn-1", "compartment", {"ocpus": 10})
        provider = StaticCapacityProvider([
            CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e5-core-count", "us-ashburn-1", "ocpus", 90, 100, 10)
        ])

        result = CapacityDecisionEngine([provider]).preflight(operation)

        self.assertEqual(result.decision, Decision.PASS)

    def test_service_limit_blocks_workload(self):
        operation = Operation("compute", "instance", "us-ashburn-1", "compartment", {"ocpus": 20})
        provider = StaticCapacityProvider([
            CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e5-core-count", "us-ashburn-1", "ocpus", 90, 100, 10)
        ])

        result = CapacityDecisionEngine([provider]).preflight(operation)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_quota_blocks_workload(self):
        operation = Operation("compute", "instance", "us-ashburn-1", "compartment", {"ocpus": 20})
        provider = StaticCapacityProvider([
            CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e5-core-count", "Production", "ocpus", 15, 30, 15)
        ])

        result = CapacityDecisionEngine([provider]).preflight(operation)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")

    def test_invalid_shape_returns_error(self):
        adapter, shape_provider, resolver = self.adapter_with([], [])

        with self.assertRaisesRegex(ValueError, "not available"):
            adapter.workload_from_payload(self.payload(), shape_provider, resolver)

    def test_unsupported_shape_limit_mapping_returns_unable_to_validate_error(self):
        flex = shape("VM.Standard.E5.Flex", raw={
            "ocpu_options": {"min": 1, "max": 64},
            "memory_options": {"min_in_gbs": 1, "max_in_gbs": 1024},
        })
        unrelated = types.SimpleNamespace(name="standard-e4-core-count", description="Standard E4 core count", scope_type="REGION")
        adapter, shape_provider, resolver = self.adapter_with([flex], [unrelated])

        with self.assertRaisesRegex(ValueError, "could not reliably map"):
            adapter.workload_from_payload(self.payload(), shape_provider, resolver)

    def test_invalid_flex_ocpu_configuration(self):
        flex = shape("VM.Standard.E5.Flex", raw={
            "ocpu_options": {"min": 1, "max": 4},
            "memory_options": {"min_in_gbs": 1, "max_in_gbs": 1024},
        })
        definition = types.SimpleNamespace(name="standard-e5-core-count", description="Standard E5 core count", scope_type="REGION")
        adapter, shape_provider, resolver = self.adapter_with([flex], [definition])

        with self.assertRaisesRegex(ValueError, "ocpus <= 4"):
            adapter.workload_from_payload(self.payload(ocpus=8), shape_provider, resolver)

    def test_invalid_flex_memory_configuration(self):
        flex = shape("VM.Standard.E5.Flex", raw={
            "ocpu_options": {"min": 1, "max": 64},
            "memory_options": {"min_in_gbs": 1, "max_in_gbs": 64},
        })
        definition = types.SimpleNamespace(name="standard-e5-core-count", description="Standard E5 core count", scope_type="REGION")
        adapter, shape_provider, resolver = self.adapter_with([flex], [definition])

        with self.assertRaisesRegex(ValueError, "memory_gb <= 64"):
            adapter.workload_from_payload(self.payload(memory=128), shape_provider, resolver)

    def test_shape_available_in_region_but_not_selected_ad(self):
        client = ComputeClient([])
        provider = ComputeShapeProvider(client)

        with self.assertRaisesRegex(ValueError, "availability domain AD-2"):
            provider.get_shape("compartment", "VM.Standard.E5.Flex", "AD-2")

        self.assertEqual(client.calls[0][1]["availability_domain"], "AD-2")

    def test_manual_ocpu_mode_still_works(self):
        operation = ComputeAdapter().operation_from_payload({
            "operation": {
                "service": "compute",
                "resource_type": "instance",
                "region": "us-ashburn-1",
                "compartment_id": "compartment",
                "requested": {"ocpus": 14},
            }
        })

        self.assertEqual(operation.requested_delta, {"ocpus": 14.0})


if __name__ == "__main__":
    unittest.main()
