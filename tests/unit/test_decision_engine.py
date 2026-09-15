from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from cli.main import main
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapacitySnapshot, Decision, Operation
from src.forecasting.linear import Observation, linear_growth_forecast
from src.limits.oci_limits_provider import OciLimitsProvider
from src.preflight.demo_data import StaticCapacityProvider, scenario_passes, scenario_quota_blocks, scenario_service_limit_blocks


class DecisionEngineTests(unittest.TestCase):
    def result_for(self, snapshots, requested=14, ad=None):
        op = Operation("compute", "instance", "us-phoenix-1", "<COMPARTMENT_OCID>", {"ocpus": requested}, ad, "Production")
        return CapacityDecisionEngine([StaticCapacityProvider(snapshots)]).preflight(op)

    def test_service_limit_pass(self):
        result = self.result_for([CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 100, 28)], 8)
        self.assertEqual(result.decision, Decision.PASS)

    def test_service_limit_block(self):
        op, provider = scenario_service_limit_blocks()
        result = CapacityDecisionEngine([provider]).preflight(op)
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_quota_pass(self):
        result = self.result_for([CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 4, 24, 20)], 14)
        self.assertEqual(result.decision, Decision.PASS)

    def test_quota_block(self):
        op, provider = scenario_quota_blocks()
        result = CapacityDecisionEngine([provider]).preflight(op)
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")

    def test_quota_blocks_before_service_limit(self):
        result = self.result_for([
            CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 80, 8),
            CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 18, 20, 2),
        ], 5)
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")

    def test_service_limit_blocks_before_quota(self):
        result = self.result_for([
            CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 80, 8),
            CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 0, 20, 20),
        ], 14)
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_multiple_simultaneous_constraints(self):
        result = self.result_for([
            CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 80, 8),
            CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 18, 20, 2),
        ], 14)
        self.assertEqual(len([c for c in result.checks if c.status.value == "WOULD_EXCEED"]), 2)

    def test_regional_scope(self):
        result = self.result_for([CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 1, 2, 1)], 1)
        self.assertEqual(result.checks[0].scope, "us-phoenix-1")

    def test_ad_scope(self):
        result = self.result_for([CapacitySnapshot("AD_CAPACITY", "compute", "gpu-count", "AD-1", "ocpus", 1, 2, 1)], 1, "AD-1")
        self.assertEqual(result.checks[0].scope, "AD-1")

    def test_unknown_availability(self):
        result = self.result_for([CapacitySnapshot("SERVICE_LIMIT", "compute", "shape", "us-phoenix-1", "ocpus", None, None, None)])
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_missing_iam_permission(self):
        result = self.result_for([CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "quota-policy", "Production", "ocpus", None, None, None, reason="Compartment quota could not be evaluated because the required API permission is missing.")])
        self.assertIn("permission", result.unknown_reasons[0])

    def test_stale_data(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        result = self.result_for([CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 1, 100, 99, timestamp=old, stale_after_seconds=60)])
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_forecast_with_sufficient_history(self):
        now = datetime.now(timezone.utc)
        forecast = linear_growth_forecast([Observation(now - timedelta(days=4), 66), Observation(now, 72)], 80)
        self.assertEqual(forecast["days_to_exhaustion"], 5.3)

    def test_forecast_without_sufficient_history(self):
        forecast = linear_growth_forecast([], 80)
        self.assertEqual(forecast["confidence"], "INSUFFICIENT_DATA")

    def test_ci_exit_code_on_block(self):
        self.assertEqual(main(["preflight", "--demo", "quota", "--requested-ocpus", "14"]), 2)

    def test_pagination(self):
        class Response:
            def __init__(self, data, next_page=None):
                self.data = data
                self.headers = {"opc-next-page": next_page} if next_page else {}

        class Client:
            def __init__(self):
                self.calls = 0
            def list_limit_values(self, *_args, **_kwargs):
                self.calls += 1
                return Response([self.calls], "next" if self.calls == 1 else None)

        self.assertEqual(OciLimitsProvider(Client(), "tenancy").list_all_limit_values("compute"), [1, 2])

    def test_oci_api_throttling_unknown(self):
        result = self.result_for([CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", None, None, None, reason="OCI API throttling after retries")])
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_oci_transient_errors_unknown(self):
        result = self.result_for([CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", None, None, None, reason="OCI transient error after exponential backoff")])
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_pass_scenario(self):
        op, provider = scenario_passes()
        self.assertEqual(CapacityDecisionEngine([provider]).preflight(op).decision, Decision.PASS)


if __name__ == "__main__":
    unittest.main()
