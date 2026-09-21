from __future__ import annotations

import types
import unittest

from src.capacity.models import Operation
from src.quotas.oci_quota_provider import OciQuotaProvider


class Response:
    def __init__(self, data):
        self.data = data
        self.headers = {}


class QuotasClient:
    def list_quotas(self, *_args, **_kwargs):
        return Response([types.SimpleNamespace(id="quota-1", statements=None)])

    def get_quota(self, _quota_id):
        return Response(types.SimpleNamespace(statements=["Set compute-core quota standard-e5-core-count to 10 in compartment Production"]))


class UsageProvider:
    limit_mapping = {"compute": {"ocpus": "standard-e5-core-count"}}

    def current_usage(self, _operation, metric):
        self.metric = metric
        return 1


class OciQuotaProviderTests(unittest.TestCase):
    def test_compute_core_quota_statement_applies_to_compute_ocpus(self):
        usage = UsageProvider()
        provider = OciQuotaProvider(QuotasClient(), "tenancy", usage)
        operation = Operation("compute", "instance", "us-ashburn-1", "compartment", {"ocpus": 20}, compartment_name="Production")

        snapshots = provider.get_current_state(operation)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].metric, "ocpus")
        self.assertEqual(snapshots[0].maximum, 10)
        self.assertEqual(snapshots[0].available, 9)
        self.assertEqual(usage.metric, "ocpus")

    def test_quota_statement_for_different_limit_is_ignored(self):
        usage = UsageProvider()
        usage.limit_mapping = {"compute": {"ocpus": "dense-io-e6-ax-core-count"}}
        provider = OciQuotaProvider(QuotasClient(), "tenancy", usage)
        operation = Operation("compute", "instance", "us-ashburn-1", "compartment", {"ocpus": 20}, compartment_name="Production")

        self.assertEqual(provider.get_current_state(operation), [])


if __name__ == "__main__":
    unittest.main()
