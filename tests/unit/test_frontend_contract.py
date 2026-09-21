from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    def test_service_operation_selector_is_primary(self):
        self.assertIn('id="service"', self.html)
        self.assertIn('id="operation"', self.html)
        self.assertIn("What Are You Planning To Deploy?", self.html)
        self.assertNotIn('id="limit"', self.html)

    def test_capability_and_cache_status_are_visible(self):
        self.assertIn('id="operationCapability"', self.html)
        self.assertIn('id="cacheStatus"', self.html)
        self.assertIn('id="servicesDiscovered"', self.html)
        self.assertIn('id="limitsDiscovered"', self.html)

    def test_monitor_and_discovery_only_disable_preflight(self):
        self.assertIn('operation.capability !== "FULL_PREFLIGHT"', self.js)
        self.assertIn("MONITOR_ONLY", self.js)
        self.assertIn("DISCOVERY_ONLY", self.js)

    def test_discovered_services_are_merged_into_selector_and_coverage(self):
        self.assertIn("mergeDiscoveredServicesIntoCatalog", self.js)
        self.assertIn("mergeServicesIntoCatalog", self.js)
        self.assertIn("/services", self.js)
        self.assertIn("discovered_limits", self.js)
        self.assertIn("operation-level preflight is not verified for this service", self.js)
        self.assertIn("discovered limits:", self.js)
        self.assertIn("service-labels-data-20260918", self.html)

    def test_selected_service_inventory_is_visible_for_discovery_services(self):
        self.assertIn("selectedServiceInventory", self.js)
        self.assertIn("Live inventory for", self.js)
        self.assertIn("with availability", self.js)

    def test_discovered_service_options_keep_names(self):
        self.assertIn("function serviceId", self.js)
        self.assertIn("function serviceLabel", self.js)
        self.assertIn("function renderServiceOptions", self.js)
        self.assertIn("item?.service || item?.name || item?.id", self.js)
        self.assertIn("item?.display_name || item?.displayName || item?.description || item?.label", self.js)

    def test_result_uses_consistent_customer_language(self):
        self.assertIn("Precheck Result", self.html)
        self.assertIn("PASS - no known service-limit or quota constraint was found", self.js)
        self.assertIn("UNABLE TO VALIDATE", self.js)
        self.assertIn("Technical details", self.js)
        self.assertIn("Preflight is advisory and does not reserve capacity", self.js)
        self.assertIn("Current usage", self.js)
        self.assertIn("Recommended action", self.js)

    def test_forms_are_generated_from_operation_metadata(self):
        self.assertIn("operation?.form", self.js)
        self.assertIn("compute_shape", self.js)
        self.assertIn("size_gb_each", self.js)
        self.assertIn("nlb_count", self.js)

    def test_discovered_services_can_use_generic_limit_check(self):
        self.assertIn("genericLimitOperation", self.js)
        self.assertIn("check_discovered_limit", self.js)
        self.assertIn("limit_select", self.js)
        self.assertIn("This is a generic live limit check", self.js)

    def test_capacity_cache_age_is_prominent(self):
        self.assertIn('id="cacheAge"', self.html)
        self.assertIn('id="cacheState"', self.html)
        self.assertIn('id="cacheRefreshed"', self.html)
        self.assertIn("formatDuration", self.js)

    def test_constraints_and_technical_details_are_separated(self):
        self.assertIn("Constraints Evaluated", self.js)
        self.assertIn("Not Evaluated", self.js)
        self.assertIn("Physical host availability", self.js)
        self.assertIn("<details><summary>Technical details</summary>", self.js)


if __name__ == "__main__":
    unittest.main()
