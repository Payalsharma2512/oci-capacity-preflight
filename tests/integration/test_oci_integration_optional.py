import os
import unittest


@unittest.skipUnless(os.getenv("OCI_CAPACITY_PREFLIGHT_INTEGRATION") == "1", "Set OCI_CAPACITY_PREFLIGHT_INTEGRATION=1 and OCI config to run.")
class OciIntegrationTests(unittest.TestCase):
    def test_placeholder_real_tenancy_scan(self):
        import oci

        config = oci.config.from_file()
        client = oci.limits.LimitsClient(config)
        response = client.list_services(config["tenancy"])
        self.assertIsNotNone(response.data)
