from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cli.main import main
from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import CapacitySnapshot, Decision, Operation
from src.capacity.providers import CapacityProvider
from src.forecasting.linear import Observation, linear_growth_forecast
from src.limits.oci_limits_provider import OciLimitsProvider


DATASET = json.loads((Path(__file__).with_name("synthetic_customer_dataset.json")).read_text(encoding="utf-8"))


class SyntheticCustomerProvider(CapacityProvider):
    def __init__(self, snapshots: list[CapacitySnapshot], strict_filtering: bool = True):
        self.snapshots = snapshots
        self.strict_filtering = strict_filtering

    def discover_constraints(self, operation: Operation) -> list[str]:
        return [snapshot.limit_name for snapshot in self.evaluate(operation)]

    def get_current_state(self, operation: Operation) -> list[CapacitySnapshot]:
        if not self.strict_filtering:
            return [s for s in self.snapshots if s.service == operation.service]
        results = []
        for snapshot in self.snapshots:
            if snapshot.service != operation.service:
                continue
            if snapshot.metric not in operation.requested_delta:
                continue
            if snapshot.constraint_type == "COMPARTMENT_QUOTA" and snapshot.raw.get("compartment_id") != operation.compartment_id:
                continue
            if snapshot.constraint_type in {"SERVICE_LIMIT", "AD_CAPACITY"}:
                if snapshot.scope not in {operation.region, f"{operation.region}/{operation.availability_domain}", "GLOBAL"}:
                    continue
            results.append(snapshot)
        return results

    def remediation(self, snapshot: CapacitySnapshot) -> dict[str, str]:
        return {"action": f"FIX_{snapshot.constraint_type}", "reason": snapshot.reason or "Resolve blocking or unknown capacity evidence."}


def dataset_snapshots() -> list[CapacitySnapshot]:
    now = datetime.now(timezone.utc)
    snapshots: list[CapacitySnapshot] = []
    for item in DATASET["limits"]:
        timestamp = now - timedelta(hours=2) if item.get("stale") else now
        constraint = "AD_CAPACITY" if "/AD-" in item["scope"] else "SERVICE_LIMIT"
        snapshots.append(CapacitySnapshot(
            constraint,
            item["service"],
            item["name"],
            item["scope"],
            item["metric"],
            item["current"],
            item["maximum"],
            item["available"],
            timestamp=timestamp,
            stale_after_seconds=60 if item.get("stale") else 900,
            reason=item.get("reason"),
        ))
    for item in DATASET["quotas"]:
        snapshots.append(CapacitySnapshot(
            "COMPARTMENT_QUOTA",
            item["service"],
            item["limit_name"],
            item["compartment_id"],
            item["metric"],
            item["current"],
            item["maximum"],
            item["available"],
            raw={"compartment_id": item["compartment_id"]},
        ))
    return snapshots


def op(service="compute", metric="ocpus", amount=1, region="us-phoenix-1", compartment="compartment-dev", ad=None):
    return Operation(service, "instance", region, compartment, {metric: amount}, ad, compartment)


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.headers = {}


class FakeLimitsClient:
    def __init__(self, exc):
        self.exc = exc

    def get_resource_availability(self, *_args, **_kwargs):
        raise self.exc


class CustomerPressureTests(unittest.TestCase):
    def setUp(self):
        self.provider = SyntheticCustomerProvider(dataset_snapshots())
        self.engine = CapacityDecisionEngine([self.provider])

    def test_01_service_limit_has_sufficient_capacity(self):
        result = self.engine.preflight(op(amount=8, compartment="compartment-dev"))
        self.assertEqual(result.decision, Decision.PASS)

    def test_02_service_limit_will_be_exceeded(self):
        result = self.engine.preflight(op(amount=51, region="us-ashburn-1", compartment="compartment-analytics"))
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_03_compartment_quota_has_less_capacity_than_service_limit(self):
        result = self.engine.preflight(op(amount=14, compartment="compartment-prod"))
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")
        self.assertEqual(result.effective_available_capacity, 2)

    def test_04_service_limit_has_less_capacity_than_compartment_quota(self):
        result = self.engine.preflight(op(amount=14, compartment="compartment-dev"))
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")
        self.assertEqual(result.effective_available_capacity, 8)

    def test_05_multiple_constraints_identify_first_blocking_constraint(self):
        result = self.engine.preflight(op(amount=14, compartment="compartment-prod"))
        self.assertEqual(result.primary_blocking_constraint, "COMPARTMENT_QUOTA")

    def test_06_request_exactly_equals_available_capacity(self):
        result = self.engine.preflight(op(amount=8, compartment="compartment-dev"))
        self.assertEqual(result.decision, Decision.PASS)

    def test_07_request_exceeds_available_capacity_by_one_unit(self):
        result = self.engine.preflight(op(amount=9, compartment="compartment-dev"))
        self.assertEqual(result.decision, Decision.BLOCK)

    def test_08_limit_definition_exists_but_resource_availability_unsupported(self):
        result = self.engine.preflight(op(metric="count", amount=1, compartment="compartment-dev"))
        unsupported = [c for c in result.checks if c.limit_name == "unsupported-shape-count"]
        self.assertTrue(unsupported)
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_09_oci_api_returns_403(self):
        provider = OciLimitsProvider(FakeLimitsClient(PermissionError("403 Forbidden")), "tenancy")
        result = CapacityDecisionEngine([provider]).preflight(op())
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_10_oci_api_returns_404_for_unsupported_availability(self):
        provider = OciLimitsProvider(FakeLimitsClient(Exception("404 NotAuthorizedOrNotFound")), "tenancy")
        result = CapacityDecisionEngine([provider]).preflight(op())
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_11_oci_api_is_throttled(self):
        provider = OciLimitsProvider(FakeLimitsClient(Exception("429 TooManyRequests")), "tenancy")
        result = CapacityDecisionEngine([provider]).preflight(op())
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_12_oci_api_returns_transient_error(self):
        provider = OciLimitsProvider(FakeLimitsClient(Exception("500 InternalError")), "tenancy")
        result = CapacityDecisionEngine([provider]).preflight(op())
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_13_historical_data_is_insufficient_for_forecasting(self):
        now = datetime.now(timezone.utc)
        history = [Observation(now - timedelta(days=i["days_ago"]), i["usage"]) for i in DATASET["forecast_history"]["insufficient"]]
        self.assertEqual(linear_growth_forecast(history, 80)["confidence"], "INSUFFICIENT_DATA")

    def test_14_historical_growth_predicts_exhaustion_soon(self):
        now = datetime.now(timezone.utc)
        history = [Observation(now - timedelta(days=i["days_ago"]), i["usage"]) for i in DATASET["forecast_history"]["soon"]]
        self.assertLessEqual(linear_growth_forecast(history, 80)["days_to_exhaustion"], 7)

    def test_15_historical_growth_predicts_no_exhaustion_within_forecast_window(self):
        now = datetime.now(timezone.utc)
        history = [Observation(now - timedelta(days=i["days_ago"]), i["usage"]) for i in DATASET["forecast_history"]["slow"]]
        self.assertGreater(linear_growth_forecast(history, 80)["days_to_exhaustion"], 30)

    def test_16_snapshot_data_is_stale(self):
        result = self.engine.preflight(op(amount=1, region="ca-toronto-1", compartment="compartment-dev"))
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_17_regional_limit(self):
        result = self.engine.preflight(op(amount=31, region="ca-toronto-1", compartment="compartment-analytics"))
        self.assertTrue(any(c.scope == "ca-toronto-1" for c in result.checks))
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")

    def test_18_availability_domain_limit(self):
        result = self.engine.preflight(op(metric="gpus", amount=3, ad="AD-1", compartment="compartment-dev"))
        self.assertEqual(result.primary_blocking_constraint, "AD_CAPACITY")

    def test_19_multiple_regions(self):
        phoenix = self.engine.preflight(op(amount=9, region="us-phoenix-1", compartment="compartment-dev"))
        ashburn = self.engine.preflight(op(amount=9, region="us-ashburn-1", compartment="compartment-dev"))
        self.assertEqual(phoenix.decision, Decision.BLOCK)
        self.assertEqual(ashburn.decision, Decision.PASS)

    def test_20_multiple_compartments(self):
        prod = self.engine.preflight(op(amount=3, compartment="compartment-prod"))
        dev = self.engine.preflight(op(amount=3, compartment="compartment-dev"))
        self.assertEqual(prod.decision, Decision.BLOCK)
        self.assertEqual(dev.decision, Decision.PASS)

    def test_21_batch_preflight_containing_pass_block_unknown_operations(self):
        batch = self.engine.preflight_batch([
            op(amount=8, compartment="compartment-dev"),
            op(amount=9, compartment="compartment-dev"),
            op(metric="count", amount=1, compartment="compartment-dev"),
        ])
        self.assertEqual(batch["overall_decision"], "BLOCK")
        self.assertEqual([r["decision"] for r in batch["results"]], ["PASS", "BLOCK", "UNKNOWN"])

    def test_22_ci_cd_invocation_returns_non_zero_on_block(self):
        self.assertNotEqual(main(["preflight", "--demo", "quota", "--requested-ocpus", "14"]), 0)

    def test_23_ci_cd_invocation_succeeds_on_pass(self):
        self.assertEqual(main(["preflight", "--demo", "pass", "--requested-ocpus", "8"]), 0)

    def test_24_missing_required_constraint_must_never_produce_pass(self):
        empty_engine = CapacityDecisionEngine([SyntheticCustomerProvider([])])
        result = empty_engine.preflight(op(amount=1))
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_25_stale_or_incomplete_dataset_must_never_silently_produce_pass(self):
        incomplete = [replace(dataset_snapshots()[0], maximum=None, available=None, reason="partial snapshot")]
        result = CapacityDecisionEngine([SyntheticCustomerProvider(incomplete)]).preflight(op(amount=1))
        self.assertEqual(result.decision, Decision.UNKNOWN)

    def test_26_block_volume_storage_request_passes_when_count_and_gb_fit(self):
        snapshots = [
            CapacitySnapshot("SERVICE_LIMIT", "block-storage", "volume-count", "us-ashburn-1/AD-1", "volume_count", 0, 100, 100),
            CapacitySnapshot("SERVICE_LIMIT", "block-storage", "total-storage-gb", "us-ashburn-1/AD-1", "storage_gb", 100, 20000, 19900),
        ]
        operation = Operation("block-storage", "volume", "us-ashburn-1", "compartment-dev", {"volume_count": 5, "storage_gb": 10240}, "AD-1", "compartment-dev")

        result = CapacityDecisionEngine([SyntheticCustomerProvider(snapshots)]).preflight(operation)

        self.assertEqual(result.decision, Decision.PASS)

    def test_27_block_volume_storage_request_blocks_when_gb_exceeds(self):
        snapshots = [
            CapacitySnapshot("SERVICE_LIMIT", "block-storage", "volume-count", "us-ashburn-1/AD-1", "volume_count", 0, 100, 100),
            CapacitySnapshot("SERVICE_LIMIT", "block-storage", "total-storage-gb", "us-ashburn-1/AD-1", "storage_gb", 100, 10000, 9900),
        ]
        operation = Operation("block-storage", "volume", "us-ashburn-1", "compartment-dev", {"volume_count": 5, "storage_gb": 10240}, "AD-1", "compartment-dev")

        result = CapacityDecisionEngine([SyntheticCustomerProvider(snapshots)]).preflight(operation)

        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.primary_blocking_constraint, "SERVICE_LIMIT")


if __name__ == "__main__":
    unittest.main()
