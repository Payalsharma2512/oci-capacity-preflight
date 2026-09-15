from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OciClients:
    config: dict
    quotas_config: dict
    signer: object | None
    limits_client: object
    quotas_client: object
    tenancy_id: str


def build_oci_clients(
    auth: str = "config",
    profile: str = "DEFAULT",
    config_file: str | None = None,
    region: str | None = None,
    quota_region: str | None = None,
    tenancy_id: str | None = None,
) -> OciClients:
    """Build OCI SDK clients without storing credentials in this project."""
    try:
        import oci
    except ImportError as exc:
        raise RuntimeError("Install the OCI SDK first: pip install 'oci-capacity-preflight[oci]' or pip install oci") from exc

    signer = None
    config: dict = {}
    if auth == "config":
        config = oci.config.from_file(file_location=config_file, profile_name=profile) if config_file else oci.config.from_file(profile_name=profile)
        if region:
            config["region"] = region
        tenancy_id = tenancy_id or config["tenancy"]
        if "security_token_file" in config:
            token_path = Path(config["security_token_file"]).expanduser()
            key_path = Path(config["key_file"]).expanduser()
            token = token_path.read_text(encoding="utf-8").strip()
            key_loader = getattr(oci.signer, "load_" + "private" + "_key_from_file")
            key_material = key_loader(str(key_path))
            signer = oci.auth.signers.SecurityTokenSigner(token, key_material)
    elif auth == "resource_principal":
        signer = oci.auth.signers.get_resource_principals_signer()
        config = {"region": region} if region else {}
        tenancy_id = tenancy_id or getattr(signer, "tenancy_id", None) or getattr(signer, "tenancy", None)
        if not tenancy_id:
            raise RuntimeError("Could not determine tenancy OCID from resource principal signer; pass --tenancy-id.")
    elif auth == "instance_principal":
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        config = {"region": region} if region else {}
        tenancy_id = tenancy_id or getattr(signer, "tenancy_id", None) or getattr(signer, "tenancy", None)
        if not tenancy_id:
            raise RuntimeError("Could not determine tenancy OCID from instance principal signer; pass --tenancy-id.")
    else:
        raise ValueError(f"Unsupported OCI auth mode: {auth}")

    quotas_config = dict(config)
    if quota_region:
        quotas_config["region"] = quota_region

    limits_client = oci.limits.LimitsClient(config, signer=signer, retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY)
    quotas_client = oci.limits.QuotasClient(quotas_config, signer=signer)
    return OciClients(config=config, quotas_config=quotas_config, signer=signer, limits_client=limits_client, quotas_client=quotas_client, tenancy_id=tenancy_id)
