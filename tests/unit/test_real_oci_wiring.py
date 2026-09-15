from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.oci_auth import build_oci_clients


class RealOciWiringTests(unittest.TestCase):
    def test_config_auth_builds_limits_and_quotas_clients(self):
        fake_oci = types.SimpleNamespace()
        fake_oci.config = types.SimpleNamespace(from_file=lambda profile_name="DEFAULT", file_location=None: {"tenancy": "tenancy", "region": "us-phoenix-1"})
        fake_oci.retry = types.SimpleNamespace(DEFAULT_RETRY_STRATEGY="retry")
        fake_oci.limits = types.SimpleNamespace(
            LimitsClient=lambda config, **kwargs: ("limits", config, kwargs),
            QuotasClient=lambda config, **kwargs: ("quotas", config, kwargs),
        )
        fake_oci.auth = types.SimpleNamespace(signers=types.SimpleNamespace())

        with patch.dict(sys.modules, {"oci": fake_oci}):
            clients = build_oci_clients(auth="config", profile="DEFAULT", region="us-phoenix-1", quota_region="us-ashburn-1")

        self.assertEqual(clients.tenancy_id, "tenancy")
        self.assertEqual(clients.config["region"], "us-phoenix-1")
        self.assertEqual(clients.quotas_config["region"], "us-ashburn-1")
        self.assertEqual(clients.limits_client[0], "limits")
        self.assertEqual(clients.quotas_client[0], "quotas")

    def test_resource_principal_auth_uses_signer_without_config_file(self):
        signer = types.SimpleNamespace(tenancy_id="tenancy-from-signer")
        fake_oci = types.SimpleNamespace()
        fake_oci.config = types.SimpleNamespace()
        fake_oci.retry = types.SimpleNamespace(DEFAULT_RETRY_STRATEGY="retry")
        fake_oci.limits = types.SimpleNamespace(
            LimitsClient=lambda config, **kwargs: ("limits", config, kwargs),
            QuotasClient=lambda config, **kwargs: ("quotas", config, kwargs),
        )
        fake_oci.auth = types.SimpleNamespace(signers=types.SimpleNamespace(get_resource_principals_signer=lambda: signer))

        with patch.dict(sys.modules, {"oci": fake_oci}):
            clients = build_oci_clients(auth="resource_principal", region="us-phoenix-1")

        self.assertEqual(clients.tenancy_id, "tenancy-from-signer")
        self.assertIs(clients.signer, signer)
        self.assertEqual(clients.config["region"], "us-phoenix-1")

    def test_instance_principal_auth_accepts_explicit_tenancy_id(self):
        signer = types.SimpleNamespace()
        fake_oci = types.SimpleNamespace()
        fake_oci.config = types.SimpleNamespace()
        fake_oci.retry = types.SimpleNamespace(DEFAULT_RETRY_STRATEGY="retry")
        fake_oci.limits = types.SimpleNamespace(
            LimitsClient=lambda config, **kwargs: ("limits", config, kwargs),
            QuotasClient=lambda config, **kwargs: ("quotas", config, kwargs),
        )
        fake_oci.auth = types.SimpleNamespace(
            signers=types.SimpleNamespace(InstancePrincipalsSecurityTokenSigner=lambda: signer)
        )

        with patch.dict(sys.modules, {"oci": fake_oci}):
            clients = build_oci_clients(
                auth="instance_principal",
                region="us-phoenix-1",
                quota_region="us-ashburn-1",
                tenancy_id="explicit-tenancy",
            )

        self.assertEqual(clients.tenancy_id, "explicit-tenancy")
        self.assertIs(clients.signer, signer)
        self.assertEqual(clients.config["region"], "us-phoenix-1")
        self.assertEqual(clients.quotas_config["region"], "us-ashburn-1")

    def test_config_auth_with_security_token_uses_security_token_signer(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token"
            key_path = Path(tmp) / "key.pem"
            token_path.write_text("bearer-value\n", encoding="utf-8")
            key_path.write_text("private-key", encoding="utf-8")

            signer = object()
            fake_oci = types.SimpleNamespace()
            fake_oci.config = types.SimpleNamespace(
                from_file=lambda profile_name="DEFAULT", file_location=None: {
                    "tenancy": "tenancy",
                    "region": "us-phoenix-1",
                    "security_token_file": str(token_path),
                    "key_file": str(key_path),
                }
            )
            fake_oci.retry = types.SimpleNamespace(DEFAULT_RETRY_STRATEGY="retry")
            fake_oci.limits = types.SimpleNamespace(
                LimitsClient=lambda config, **kwargs: ("limits", config, kwargs),
                QuotasClient=lambda config, **kwargs: ("quotas", config, kwargs),
            )
            fake_oci.signer = types.SimpleNamespace()
            setattr(fake_oci.signer, "load_" + "private" + "_key_from_file", lambda filename: f"loaded:{filename}")
            fake_oci.auth = types.SimpleNamespace(
                signers=types.SimpleNamespace(
                    SecurityTokenSigner=lambda token, key_material: signer
                    if token == "bearer-value" and key_material == f"loaded:{key_path}"
                    else None
                )
            )

            with patch.dict(sys.modules, {"oci": fake_oci}):
                clients = build_oci_clients(auth="config", profile="DEFAULT")

        self.assertIs(clients.signer, signer)
        self.assertIs(clients.limits_client[2]["signer"], signer)
        self.assertIs(clients.quotas_client[2]["signer"], signer)


if __name__ == "__main__":
    unittest.main()
