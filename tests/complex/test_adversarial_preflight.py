from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapacitySnapshot, Operation
from src.capacity.providers import CapacityProvider
from src.forecasting.linear import Observation, linear_growth_forecast
from src.notifications.state_machine import NotificationState, should_notify
from src.preflight.risk import risk_state


class StaticProvider(CapacityProvider):
    def __init__(self, snapshots, action="REMEDIATE", reason="Review capacity constraint."):
        self.snapshots = snapshots
        self.action = action
        self.reason = reason

    def discover_constraints(self, operation):
        return [snapshot.limit_name for snapshot in self.snapshots]

    def get_current_state(self, operation):
        return self.snapshots

    def remediation(self, snapshot):
        return {"action": self.action, "reason": self.reason}


def snapshot(kind, name, metric="ocpus", current=0, maximum=100, available=100, scope="region", reason=None, age_minutes=0):
    return CapacitySnapshot(
        kind,
        "compute",
        name,
        scope,
        metric,
        current,
        maximum,
        available,
        reason=reason,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )


def op(amount=1, metric="ocpus", region="region-a", compartment="compartment-a", ad=None):
    return Operation("compute", "instance", region, compartment, {metric: amount}, ad, "Production")


class AdversarialPreflightTests(unittest.TestCase):
    def run_engine(self, snapshots, amount=1, metric="ocpus", providers=None):
        engine = CapacityDecisionEngine(providers or [StaticProvider(snapshots)])
        return engine.preflight(op(amount=amount, metric=metric))

    def test_multiple_constraints_ad_constraint_blocks_first(self):
        result = self.run_engine([
            snapshot("SERVICE_LIMIT", "service", current=0, maximum=100, available=100),
            snapshot("COMPARTMENT_QUOTA", "quota", current=0, maximum=20, available=20),
            snapshot("REGIONAL_CAPACITY", "regional", current=0, maximum=50, available=50),
            snapshot("AD_CAPACITY", "ad", current=0, maximum=8, available=8, scope="ad-1"),
        ], amount=10)

        self.assertEqual(result.decision.value, "BLOCK")
        self.assertEqual(result.primary_blocking_constraint, "AD_CAPACITY")
        self.assertEqual(result.effective_available_capacity, 8)
        blocker = [check for check in result.checks if check.status.value == "WOULD_EXCEED"][0]
        self.assertEqual(blocker.shortfall, 2)

    def test_service_limit_blocks_quota_passes(self):
        result = CapacityDecisionEngine([
            StaticProvider([snapshot("SERVICE_LIMIT", "service", current=95, maximum=100, available=5)], "REQUEST_LIMIT_INCREASE", "Request service limit increase."),
            StaticProvider([snapshot("COMPARTMENT_QUOTA", "quota", current=0, maximum=50, available=50)], "INCREASE_COMPARTMENT_QUOTA", "Increase compartment quota."),
        ]).preflight(op(amount=10))

        self.assertEqual(result.decision.value, "BLOCK")
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")
        self.assertEqual(result.recommendations[0]["action"], "REQUEST_LIMIT_INCREASE")

    def test_quota_blocks_service_limit_passes(self):
        result = CapacityDecisionEngine([
            StaticProvider([snapshot("SERVICE_LIMIT", "service", current=0, maximum=100, available=100)], "REQUEST_LIMIT_INCREASE", "Request service limit increase."),
            StaticProvider([snapshot("COMPARTMENT_QUOTA", "quota", current=18, maximum=20, available=2)], "INCREASE_COMPARTMENT_QUOTA", "Increase compartment quota."),
        ]).preflight(op(amount=10))

        self.assertEqual(result.decision.value, "BLOCK")
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")
        self.assertEqual(result.recommendations[0]["action"], "INCREASE_COMPARTMENT_QUOTA")

    @unittest.expectedFailure
    def test_both_service_limit_and_quota_block_should_return_both_remediations(self):
        result = CapacityDecisionEngine([
            StaticProvider([snapshot("SERVICE_LIMIT", "service", current=95, maximum=100, available=5)], "REQUEST_LIMIT_INCREASE", "Request service limit increase."),
            StaticProvider([snapshot("COMPARTMENT_QUOTA", "quota", current=18, maximum=20, available=2)], "INCREASE_COMPARTMENT_QUOTA", "Increase compartment quota."),
        ]).preflight(op(amount=10))

        self.assertEqual(result.decision.value, "BLOCK")
        self.assertEqual({item["action"] for item in result.recommendations}, {"REQUEST_LIMIT_INCREASE", "INCREASE_COMPARTMENT_QUOTA"})

    def test_neither_service_limit_nor_quota_blocks(self):
        result = CapacityDecisionEngine([
            StaticProvider([snapshot("SERVICE_LIMIT", "service", current=10, maximum=100, available=90)]),
            StaticProvider([snapshot("COMPARTMENT_QUOTA", "quota", current=5, maximum=50, available=45)]),
        ]).preflight(op(amount=10))

        self.assertEqual(result.decision.value, "PASS")
        self.assertEqual(result.effective_available_capacity, 45)

    def test_boundary_request_equals_available_passes(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=90, maximum=100, available=10)], amount=10)
        self.assertEqual(result.decision.value, "PASS")

    def test_boundary_request_available_plus_one_blocks(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=90, maximum=100, available=10)], amount=11)
        self.assertEqual(result.decision.value, "BLOCK")
        self.assertEqual(result.checks[0].shortfall, 1)

    def test_zero_request_passes_when_capacity_known(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=90, maximum=100, available=10)], amount=0)
        self.assertEqual(result.decision.value, "PASS")

    @unittest.expectedFailure
    def test_negative_request_should_be_rejected_not_passed(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=90, maximum=100, available=10)], amount=-1)
        self.assertNotEqual(result.decision.value, "PASS")

    @unittest.expectedFailure
    def test_decimal_integer_resource_should_be_rejected(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=0, maximum=10, available=10)], amount=1.5)
        self.assertNotEqual(result.decision.value, "PASS")

    def test_very_large_integer_blocks(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=0, maximum=100, available=100)], amount=10**12)
        self.assertEqual(result.decision.value, "BLOCK")

    def test_batch_block_overrides_passes(self):
        engine = CapacityDecisionEngine([StaticProvider([snapshot("SERVICE_LIMIT", "service", current=0, maximum=10, available=10)])])
        batch = engine.preflight_batch([op(amount=1), op(amount=11)])
        self.assertEqual(batch["overall_decision"], "BLOCK")
        self.assertEqual(batch["results"][1]["decision"], "BLOCK")

    def test_batch_unknown_does_not_become_pass(self):
        engine = CapacityDecisionEngine([StaticProvider([snapshot("SERVICE_LIMIT", "service", None, None, None, reason="permission missing")])])
        batch = engine.preflight_batch([op(amount=1), op(amount=2)])
        self.assertEqual(batch["overall_decision"], "UNKNOWN")

    def test_multi_region_candidate_pass_is_distinguishable_from_block(self):
        phoenix = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=99, maximum=100, available=1, scope="region-a")], amount=5)
        ashburn = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=0, maximum=100, available=100, scope="region-b")], amount=5)
        self.assertEqual(phoenix.decision.value, "BLOCK")
        self.assertEqual(ashburn.decision.value, "PASS")

    def test_multi_region_unknown_is_not_reported_as_block(self):
        unknown = self.run_engine([snapshot("SERVICE_LIMIT", "service", None, None, None, scope="region-a", reason="timeout")], amount=5)
        viable = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=0, maximum=100, available=100, scope="region-b")], amount=5)
        self.assertEqual(unknown.decision.value, "UNKNOWN")
        self.assertEqual(viable.decision.value, "PASS")

    def test_multi_ad_constraints_are_distinct(self):
        ad1 = self.run_engine([snapshot("AD_CAPACITY", "ad", current=0, maximum=10, available=10, scope="ad-1")], amount=5)
        ad2 = self.run_engine([snapshot("AD_CAPACITY", "ad", current=9, maximum=10, available=1, scope="ad-2")], amount=5)
        ad3 = self.run_engine([snapshot("AD_CAPACITY", "ad", current=0, maximum=10, available=10, scope="ad-3")], amount=5)
        self.assertEqual([ad1.decision.value, ad2.decision.value, ad3.decision.value], ["PASS", "BLOCK", "PASS"])
        self.assertEqual(ad2.primary_blocking_constraint, "AD_CAPACITY")

    def test_invalid_ad_returns_unable_to_validate_semantics(self):
        result = self.run_engine([snapshot("AD_CAPACITY", "ad", None, None, None, reason="Invalid parameter availabilityDomain")])
        self.assertEqual(result.decision.value, "UNKNOWN")

    def test_missing_permissions_never_pass(self):
        for reason in ["limits permission missing", "quota permission missing", "usage permission missing"]:
            with self.subTest(reason=reason):
                result = self.run_engine([snapshot("SERVICE_LIMIT", "service", None, None, None, reason=reason)])
                self.assertEqual(result.decision.value, "UNKNOWN")

    def test_api_error_statuses_never_pass(self):
        for code in [400, 401, 403, 404, 409, 429, 500]:
            with self.subTest(code=code):
                result = self.run_engine([snapshot("SERVICE_LIMIT", "service", None, None, None, reason=f"OCI API {code}")])
                self.assertEqual(result.decision.value, "UNKNOWN")

    def test_stale_data_does_not_pass(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=1, maximum=100, available=99, age_minutes=180)])
        self.assertEqual(result.decision.value, "UNKNOWN")
        self.assertEqual(result.checks[0].status.value, "STALE")
        self.assertIsNotNone(result.checks[0].last_successful_evaluation)

    def test_unknown_required_constraint_does_not_pass(self):
        result = self.run_engine([
            snapshot("SERVICE_LIMIT", "service", current=0, maximum=100, available=100),
            snapshot("COMPARTMENT_QUOTA", "quota", current=0, maximum=100, available=100),
            snapshot("AD_CAPACITY", "ad", None, None, None, reason="Required capacity constraint could not be evaluated."),
        ], amount=5)
        self.assertEqual(result.decision.value, "UNKNOWN")

    def test_zero_and_missing_values_do_not_divide_by_zero_or_false_pass(self):
        exhausted = self.run_engine([snapshot("SERVICE_LIMIT", "zero", current=0, maximum=0, available=0)], amount=1)
        missing = self.run_engine([snapshot("SERVICE_LIMIT", "missing", current=None, maximum=10, available=None)], amount=1)
        risk = risk_state(snapshot("SERVICE_LIMIT", "zero", current=0, maximum=0, available=0))
        self.assertEqual(exhausted.decision.value, "BLOCK")
        self.assertEqual(missing.decision.value, "UNKNOWN")
        self.assertEqual(risk["state"], "UNKNOWN")

    @unittest.expectedFailure
    def test_workload_abstraction_should_calculate_total_ocpus(self):
        instances = 10
        ocpus_each = 4
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=0, maximum=30, available=30)], amount=instances)
        self.assertEqual(instances * ocpus_each, 40)
        self.assertEqual(result.decision.value, "BLOCK")

    def test_different_resource_dimensions_fail_independently(self):
        ocpu_pass_memory_fail = self.run_engine([
            snapshot("SERVICE_LIMIT", "ocpu", "ocpus", current=0, maximum=100, available=100),
            snapshot("SERVICE_LIMIT", "memory", "gb", current=90, maximum=100, available=10),
        ], amount=20, metric="gb")
        self.assertEqual(ocpu_pass_memory_fail.decision.value, "BLOCK")
        self.assertEqual(ocpu_pass_memory_fail.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_forecast_warning_does_not_override_immediate_pass(self):
        now = datetime.now(timezone.utc)
        forecast = linear_growth_forecast([Observation(now - timedelta(days=1), 80), Observation(now, 90)], 110)
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=90, maximum=110, available=20)], amount=5)
        self.assertEqual(result.decision.value, "PASS")
        self.assertEqual(forecast["days_to_exhaustion"], 2.0)

    def test_immediate_block_overrides_forecast(self):
        now = datetime.now(timezone.utc)
        forecast = linear_growth_forecast([Observation(now - timedelta(days=1), 10), Observation(now, 11)], 100)
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=95, maximum=100, available=5)], amount=10)
        self.assertEqual(result.decision.value, "BLOCK")
        self.assertGreater(forecast["days_to_exhaustion"], 2)

    def test_recovery_state_can_be_recognized(self):
        critical = risk_state(snapshot("SERVICE_LIMIT", "service", current=95, maximum=100, available=5))
        healthy = risk_state(snapshot("SERVICE_LIMIT", "service", current=10, maximum=100, available=90))
        self.assertEqual(critical["state"], "CRITICAL")
        self.assertEqual(healthy["state"], "HEALTHY")

    def test_notifications_do_not_repeat_before_cooldown_and_do_recover(self):
        now = datetime.now(timezone.utc)
        previous = NotificationState("WARNING", now - timedelta(minutes=10))
        old_previous = NotificationState("WARNING", now - timedelta(minutes=70))
        self.assertFalse(should_notify(previous, "WARNING"))
        self.assertTrue(should_notify(old_previous, "WARNING"))
        self.assertTrue(should_notify(previous, "RECOVERY"))

    @unittest.expectedFailure
    def test_unit_consistency_requires_explicit_conversion_rules(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "requests-per-minute", "requests/minute", current=0, maximum=60, available=60)], amount=2, metric="requests/second")
        self.assertEqual(result.decision.value, "BLOCK")

    def test_idempotency_for_static_inputs(self):
        snapshots = [snapshot("SERVICE_LIMIT", "service", current=5, maximum=300, available=295)]
        results = [self.run_engine(snapshots, amount=20) for _ in range(100)]
        self.assertEqual({result.decision.value for result in results}, {"PASS"})
        self.assertEqual({result.effective_available_capacity for result in results}, {295})

    def test_block_response_contains_customer_comprehension_fields(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", current=95, maximum=100, available=5)], amount=10)
        check = result.checks[0].to_dict()
        for field in ["current", "maximum", "available", "requested_delta", "projected", "shortfall", "reason"]:
            self.assertIn(field, check)
            self.assertIsNotNone(check[field])
        self.assertTrue(result.recommendations)

    def test_unable_to_validate_contains_reason_and_next_debug_context(self):
        result = self.run_engine([snapshot("SERVICE_LIMIT", "service", None, None, None, reason="Quota API returned 403")], amount=10)
        self.assertEqual(result.decision.value, "UNKNOWN")
        self.assertIn("Quota API returned 403", result.unknown_reasons[0])


if __name__ == "__main__":
    unittest.main()
