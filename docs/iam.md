# IAM

Use resource principals for OCI Functions where possible. Grant the function dynamic group least privilege:

```text
Allow dynamic-group oci-capacity-preflight-functions to inspect limits in tenancy
Allow dynamic-group oci-capacity-preflight-functions to read quotas in tenancy
Allow dynamic-group oci-capacity-preflight-functions to inspect instance-family in tenancy
Allow dynamic-group oci-capacity-preflight-functions to read metrics in tenancy
Allow dynamic-group oci-capacity-preflight-functions to manage objects in compartment <snapshot-compartment> where target.bucket.name='oci-capacity-preflight-snapshots'
Allow dynamic-group oci-capacity-preflight-functions to use ons-topics in compartment <ops-compartment>
```

No private keys are stored by the service. Do not log credentials, signer material, or request headers.

For local testing, use your existing `~/.oci/config` profile. For OCI Functions, use resource principals; the implementation calls `oci.auth.signers.get_resource_principals_signer()` when `OCI_CAPACITY_PREFLIGHT_MODE=oci`.
