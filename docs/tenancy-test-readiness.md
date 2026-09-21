# Tenancy Test Readiness

Use this checklist before inviting a team to test the dashboard in a new OCI tenancy.

## Required Runner Configuration

The app should run on an OCI Compute runner with Instance Principal authentication and these environment variables:

```bash
OCI_CAPACITY_PREFLIGHT_MODE=oci
OCI_CAPACITY_PREFLIGHT_AUTH=instance_principal
OCI_CAPACITY_PREFLIGHT_REGION=<target-region>
OCI_CAPACITY_PREFLIGHT_QUOTA_REGION=<tenancy-home-or-quota-region>
OCI_TENANCY_OCID=<tenancy-ocid>
OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID=<target-compartment-ocid>
OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN=<target-ad>
```

The runner dynamic group needs read-only permissions:

```text
inspect limits in tenancy
read quotas in tenancy
inspect instance-family in tenancy
```

## Runtime Provenance Gate

Run the verifier on the runner:

```bash
python3.11 scripts/verify-live-provenance.py
```

The dashboard is ready for team testing only when the verifier ends with:

```text
OVERALL:
LIVE TENANCY DATA VERIFIED
```

If it reports `NOT VERIFIED`, fix the missing IAM, region, compartment, AD, or backend issue before testing.

## Dashboard Smoke Test

Open the dashboard through SSH forwarding or Bastion:

```text
http://localhost:8000/?v=<new-cache-buster>
```

Confirm:

- Banner says `LIVE OCI DATA`.
- Health is `mode=oci`, `auth=instance_principal`.
- Region, Compartment OCID, and Availability Domain are prefilled from the runner environment or persist after entry.
- Compute shape list loads after target fields are present.
- Refresh inventory shows cache status, age, and TTL.
- No URL contains `?demo=`.

## Supported Test Matrix

These operation families are expected to return deterministic, operation-aware `PASS` or `BLOCK`:

| Service | Operation | Expected coverage |
| --- | --- | --- |
| Compute | Create Compute Instances | Shape-resolved OCPU and memory service limits plus applicable Compute quota |
| Block Volume | Create Block Volumes | Volume count and total storage GB |
| Network Load Balancer | Create Network Load Balancers | Flexible NLB count |

Other discovered OCI services can be tested with `Check Discovered Limit` when OCI exposes live resource availability for a selected limit. That generic check can return `PASS` or `BLOCK` for the selected live service-limit value. It does not prove service-specific operation semantics, physical placement, reservations, or non-limit prerequisites.

If OCI does not expose live availability for the selected service/limit, or the app cannot map the request to a concrete limit, `UNABLE TO VALIDATE` is the correct safe result.

## Compute Tests

Use a shape that appears in the live Shape dropdown and is accepted by preflight. Flex shapes require OCPUs and memory per instance.

PASS candidate:

```text
instances = 1
ocpus_per_instance = 1 or another value safely below available quota
memory_gb_per_instance = a valid value for the selected Flex shape
```

BLOCK candidate:

```text
instances x ocpus_per_instance > effective available OCPU capacity or applicable compartment quota
```

If Compute returns `UNABLE TO VALIDATE`, the selected shape could not be reliably mapped to a verified OCI limit in that tenancy. Choose another visible shape or use the runtime verifier output to identify verified shape quota names.

## Block Volume Tests

PASS candidate:

```text
volume_count = 1
size_gb_each = 50
```

BLOCK candidate:

```text
size_gb_each = current total-storage-gb available + 1
```

The available storage value is visible in the capacity inventory and in the runtime verifier output.

## Network Load Balancer Tests

PASS candidate:

```text
nlb_count = 1
```

BLOCK candidate:

```text
nlb_count = current max-nlb-flexible-count available + 1
```

The available NLB count is visible in the capacity inventory and in the runtime verifier output.

## Generic Discovered Service Tests

For any additional service in the dashboard:

1. Select the service.
2. Select `Check Discovered Limit`.
3. Choose a live limit from the Limit dropdown.
4. Enter a requested unit count.

PASS candidate:

```text
requested_units <= available for the selected limit
```

BLOCK candidate:

```text
requested_units > available for the selected limit
```

If the service only offers `Discovered Limits`, it is visible for inventory but does not have a live availability value that can be used for generic preflight.

## Ready Signal

The app is ready for several tenancy tests when all of these are true:

```text
Runtime verifier: LIVE TENANCY DATA VERIFIED
Dashboard banner: LIVE OCI DATA
Compute shape list: populated from /compute/shapes
Compute PASS/BLOCK: one of each verified
Block Volume PASS/BLOCK: one of each verified
NLB PASS/BLOCK: one of each verified
At least one generic discovered-service PASS/BLOCK: verified when another service has live availability
Synthetic fallback: NONE FOUND
```
