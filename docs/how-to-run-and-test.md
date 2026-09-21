# How To Run And Test Capacity Readiness Check

This guide explains how to run the live OCI dashboard on an OCI runner and how to test it end to end before sharing it with a team.

## What This App Does

Capacity Readiness Check compares a planned deployment request against live OCI service-limit, quota, and resource-availability data.

It does not reserve capacity and it does not replace OCI Limits or Quotas. It answers a narrower question:

```text
Will this planned request exceed a known OCI limit or quota before I deploy?
```

## Required Access

The recommended test setup is:

- OCI Compute runner
- Instance Principal authentication
- Dynamic group policies with read-only access
- Local browser access through an SSH tunnel or Bastion

Required read-only OCI policy coverage:

```text
inspect limits in tenancy
read quotas in tenancy
inspect instance-family in tenancy
```

## Start The App On The Runner

Run from the unpacked app directory on the OCI runner:

```bash
cd /home/opc/oci-capacity-preflight-test

export OCI_CAPACITY_PREFLIGHT_MODE=oci
export OCI_CAPACITY_PREFLIGHT_AUTH=instance_principal
export OCI_CAPACITY_PREFLIGHT_REGION=us-ashburn-1
export OCI_CAPACITY_PREFLIGHT_QUOTA_REGION=us-ashburn-1
export OCI_TENANCY_OCID='<tenancy_ocid>'
export OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID='<compartment_ocid>'
export OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN='<availability_domain>'

pkill -f 'uvicorn src.api.app:app' || true

nohup /home/opc/oci-capacity-preflight-venv/bin/python -m uvicorn src.api.app:app \
  --host 127.0.0.1 \
  --port 8000 \
  > /home/opc/oci-capacity-preflight-test.log 2>&1 &
```

Confirm health:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Expected:

```text
"mode":"oci"
"auth":"instance_principal"
"tenancy_configured":true
```

## Verify Live OCI Provenance

Run this on the runner:

```bash
cd /home/opc/oci-capacity-preflight-test

PYTHONPATH=/home/opc/oci-capacity-preflight-test \
/home/opc/oci-capacity-preflight-venv/bin/python scripts/verify-live-provenance.py
```

Expected final result:

```text
OVERALL:
LIVE TENANCY DATA VERIFIED
```

Do not mark runtime data as verified unless this script passes on the OCI runner.

## Open The Dashboard

Use an SSH tunnel or Bastion so the app remains bound to localhost on the runner.

Example tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 opc@<runner_public_ip>
```

Then open:

```text
http://localhost:8000
```

If the browser appears stale after a deployment, use a cache buster:

```text
http://localhost:8000/?v=final
```

## Dashboard Smoke Test

Confirm:

- The banner says `LIVE OCI DATA`.
- The health details show `mode=oci` and `auth=instance_principal`.
- Region, compartment OCID, and availability domain are present or can be entered.
- The Compute shape dropdown loads after region and compartment are present.
- Changing service, operation, shape, or inputs clears the old result until `Run Preflight` is clicked again.
- The app does not show `DEMO / SYNTHETIC DATA`.

## Compute Test

Select:

```text
Service: Compute
Operation: Create Compute Instances
Shape: VM.Standard.E5.Flex or another visible supported shape
```

PASS candidate:

```text
Number of instances: 1
OCPUs per instance: 1
Memory per instance GB: valid value for the selected shape
```

BLOCK candidate:

```text
Number of instances x OCPUs per instance > effective available OCPU capacity or compartment quota
```

For the verified runner example:

```text
5 x VM.Standard.E5.Flex
4 OCPUs each
32 GB each
```

Expected:

```text
BLOCK
Blocking constraint: Compartment quota
Requested OCPUs: 20
```

## Block Volume Test

Select:

```text
Service: Block Volume
Operation: Create Block Volumes
```

PASS candidate:

```text
Number of volumes: 1
Size per volume GB: 50
```

BLOCK candidate:

```text
Size per volume GB greater than available total-storage-gb
```

## Network Load Balancer Test

Select:

```text
Service: Network Load Balancer
Operation: Create Network Load Balancers
```

PASS candidate:

```text
Number of NLBs: 1
```

BLOCK candidate:

```text
Number of NLBs greater than available max-nlb-flexible-count
```

## Generic Discovered Service Test

For other OCI services:

1. Select a service.
2. Select `Check Discovered Limit` if available.
3. Choose a limit.
4. Enter requested units.
5. Click `Run Preflight`.

Expected:

```text
requested units <= available: PASS
requested units > available: BLOCK
```

If the service only shows `Discovered Limits`, the service is inventory-only. `UNABLE TO VALIDATE` or no preflight action is safe and expected.

## What Results Mean

`PASS` means no known service-limit or quota constraint was detected for the request.

`BLOCK` means the planned request exceeds a known service limit or applicable quota.

`UNABLE TO VALIDATE` means the app could not safely prove the request from live OCI data. Treat this as not approved, not as pass.

## Ready For Team Testing

The app is ready for team testing when all are true:

```text
Runtime verifier: LIVE TENANCY DATA VERIFIED
Dashboard banner: LIVE OCI DATA
Compute PASS/BLOCK tested
Block Volume PASS/BLOCK tested
NLB PASS/BLOCK tested
At least one generic discovered-service test completed when available
Old results clear when changing service/operation/input
Synthetic fallback: none found
```

## Troubleshooting

If the app shows old UI behavior:

```text
Use a cache-busted URL like http://localhost:8000/?v=final
Hard refresh with Ctrl+F5
Restart uvicorn from /home/opc/oci-capacity-preflight-test
```

If the verifier does not pass:

```text
Check Instance Principal auth
Check dynamic group policies
Check tenancy OCID, compartment OCID, region, quota region, and availability domain
Check /health and /capacity
```

If a shape does not validate:

```text
Choose a visible shape with OCI quota_names and known service-limit mapping
Use the verifier output to confirm Compute E5 quota_names
```
