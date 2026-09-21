from __future__ import annotations

import unittest
from unittest.mock import patch

from src.api.app import capacity_cache_info, capacity_summary, current_auth, current_mode, error_capacity_response, operation_catalog


class OperationMetadataTests(unittest.TestCase):
    def test_operation_catalog_groups_services_and_operations(self):
        catalog = operation_catalog()
        services = {item["service"]: item for item in catalog["services"]}

        self.assertIn("compute", services)
        self.assertIn("block-storage", services)
        self.assertIn("network-load-balancer-api", services)
        self.assertTrue(any(item["operation"] == "create_instances" for item in services["compute"]["operations"]))
        self.assertTrue(any(item["operation"] == "create_volumes" for item in services["block-storage"]["operations"]))
        self.assertTrue(any(item["operation"] == "create_network_load_balancers" for item in services["network-load-balancer-api"]["operations"]))

    def test_nlb_monitor_only_operations_are_not_full_preflight(self):
        nlb = next(item for item in operation_catalog()["services"] if item["service"] == "network-load-balancer-api")
        operations = {item["operation"]: item for item in nlb["operations"]}

        self.assertEqual(operations["create_network_load_balancers"]["capability"], "FULL_PREFLIGHT")
        self.assertEqual(operations["backend_sets"]["capability"], "MONITOR_ONLY")
        self.assertEqual(operations["backends"]["capability"], "MONITOR_ONLY")
        self.assertEqual(operations["throughput_connections"]["capability"], "MONITOR_ONLY")
        self.assertEqual(operations["unmapped_discovered_limits"]["capability"], "DISCOVERY_ONLY")

    def test_operations_include_form_metadata(self):
        compute = next(item for item in operation_catalog()["operations"] if item["operation"] == "create_instances")
        block = next(item for item in operation_catalog()["operations"] if item["operation"] == "create_volumes")
        nlb = next(item for item in operation_catalog()["operations"] if item["operation"] == "create_network_load_balancers")

        self.assertTrue(any(field["type"] == "compute_shape" for field in compute["form"]))
        self.assertTrue(any(field["name"] == "size_gb_each" for field in block["form"]))
        self.assertTrue(any(field["name"] == "nlb_count" for field in nlb["form"]))

    def test_capacity_summary_counts_capabilities_and_risk(self):
        summary = capacity_summary([
            {"service": "compute", "capability": "FULL_PREFLIGHT", "risk_state": "HEALTHY"},
            {"service": "load-balancer", "capability": "MONITOR_ONLY", "risk_state": "UNKNOWN"},
        ])

        self.assertEqual(summary["services_discovered"], 2)
        self.assertEqual(summary["limits_discovered"], 2)
        self.assertEqual(summary["capability_counts"]["FULL_PREFLIGHT"], 1)
        self.assertEqual(summary["capability_counts"]["MONITOR_ONLY"], 1)
        self.assertEqual(summary["risk_counts"]["HEALTHY"], 1)
        self.assertEqual(summary["risk_counts"]["UNKNOWN"], 1)

    def test_empty_cache_status_is_visible(self):
        info = capacity_cache_info("region", "compartment", "ad")

        self.assertEqual(info["status"], "empty")
        self.assertIn("ttl_seconds", info)

    def test_live_mode_and_auth_aliases_are_supported(self):
        with patch.dict("os.environ", {"OCI_MODE": "live", "AUTH": "instance_principal"}, clear=True):
            self.assertEqual(current_mode(), "oci")
            self.assertEqual(current_auth(), "instance_principal")

    def test_live_capacity_error_response_does_not_include_synthetic_data(self):
        response = error_capacity_response(RuntimeError("Limits API denied"))

        self.assertEqual(response["capacity"], [])
        self.assertEqual(response["cache"]["status"], "error")
        self.assertEqual(response["error"], "UNABLE TO VALIDATE")
        self.assertNotEqual(response["cache"]["status"], "synthetic")


if __name__ == "__main__":
    unittest.main()
