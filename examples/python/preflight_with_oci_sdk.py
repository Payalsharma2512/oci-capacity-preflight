"""Customer-friendly OCI SDK example for OCI Capacity Preflight.

Method names were verified against the current Oracle OCI Python SDK docs:
oci.limits.LimitsClient.list_services, list_limit_definitions,
list_limit_values, get_resource_availability, and
oci.limits.QuotasClient.list_quotas.
"""

import oci

from src.capacity.engine import CapacityDecisionEngine
from src.capacity.models import Operation
from src.limits.oci_limits_provider import OciLimitsProvider
from src.quotas.oci_quota_provider import OciQuotaProvider
from src.usage.providers import StaticUsageProvider


config = oci.config.from_file()
tenancy_id = config["tenancy"]
limits_client = oci.limits.LimitsClient(config, retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY)
quotas_client = oci.limits.QuotasClient(config)

services = limits_client.list_services(tenancy_id).data
limit_definitions = limits_client.list_limit_definitions(tenancy_id, service_name="compute").data
limit_values = limits_client.list_limit_values(tenancy_id, "compute", scope_type="REGION").data
quotas = quotas_client.list_quotas(tenancy_id, lifecycle_state="ACTIVE").data

operation = Operation(
    service="compute",
    resource_type="instance",
    region="<TARGET_REGION>",
    availability_domain="<VALID_AD>",
    compartment_id="<COMPARTMENT_OCID>",
    requested_delta={"ocpus": 14},
)

usage_provider = StaticUsageProvider({("compute", operation.compartment_id, "ocpus"): 18})
engine = CapacityDecisionEngine([
    OciLimitsProvider(limits_client, tenancy_id),
    OciQuotaProvider(quotas_client, tenancy_id, usage_provider),
])

result = engine.preflight(operation)
print(result.to_dict())

if result.decision.value == "PASS":
    print("Continue, while remembering the response is advisory.")
elif result.decision.value == "BLOCK":
    print("Stop and complete the recommended remediation before provisioning.")
else:
    print("Do not treat UNKNOWN as safe; fix IAM, API, or stale data first.")
