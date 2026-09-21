# Live Runner Provenance Verification

Run this only on the existing OCI Capacity Preflight runner where Instance Principal authentication is configured and the backend is running on localhost.

The verifier is read-only with respect to OCI. It uses Instance Principal, OCI Limits, OCI Quotas, and Compute `list_shapes` APIs, then compares those direct OCI values with the local Capacity Preflight backend.

## Run

```bash
cd /path/to/oci-capacity-preflight
python scripts/verify-live-provenance.py
```

If the runner uses Python 3.11 explicitly:

```bash
cd /path/to/oci-capacity-preflight
python3.11 scripts/verify-live-provenance.py
```

The script expects the same environment variables used by the live app:

```bash
OCI_TENANCY_OCID=<tenancy OCID>
OCI_CAPACITY_PREFLIGHT_REGION=us-ashburn-1
OCI_CAPACITY_PREFLIGHT_QUOTA_REGION=us-ashburn-1
OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID=<target compartment OCID>
OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN=<full AD name>
OCI_CAPACITY_PREFLIGHT_AUTH=instance_principal
OCI_CAPACITY_PREFLIGHT_MODE=oci
```

It also accepts the older validation aliases if present:

```bash
TARGET_REGION=us-ashburn-1
TARGET_COMPARTMENT_OCID=<target compartment OCID>
AVAILABILITY_DOMAIN=<full AD name>
```

## Local Backend Check

The script queries the running app at `http://127.0.0.1:8000` by default. To check the backend manually:

```bash
curl -fsS http://127.0.0.1:8000/health
```

To point the verifier at a different local URL:

```bash
OCI_CAPACITY_PREFLIGHT_APP_URL=http://127.0.0.1:8000 python3.11 scripts/verify-live-provenance.py
```

## What It Verifies

- Instance Principal authentication can build OCI SDK clients.
- Tenancy is identified only with a masked OCID.
- Runner region, quota region, target compartment, and availability domain are detected.
- Direct OCI values are fetched for:
  - Compute `standard-e5-core-count`
  - Compute `standard-e5-memory-count`
  - Compute quota for `standard-e5-core-count`, when present
  - Block Volume `volume-count`
  - Block Volume `total-storage-gb`
  - NLB `max-nlb-flexible-count`
- The local app is queried through:
  - `GET /health`
  - `GET /capacity`
  - `POST /capacity/refresh`
  - `POST /preflight` for Compute, Block Volume, and NLB
- Direct OCI values are compared with backend capacity rows and preflight checks.
- Cache status, age, and TTL are reported.
- Synthetic/demo data is treated as failure, not proof.

## Expected Output

Successful runtime verification ends with:

```text
OVERALL:
LIVE TENANCY DATA VERIFIED
```

If a required value, permission, app endpoint, quota, or capacity row is unavailable, the script reports:

```text
NOT VERIFIED
```

Do not treat `NOT VERIFIED` as `PASS`.

## Safety

The script does not create, update, or delete OCI resources. It performs read-only OCI SDK calls and local HTTP calls to the running application.

No new IAM permissions are required beyond the live app's existing read permissions:

```text
inspect limits in tenancy
read quotas in tenancy
inspect instance-family in tenancy
```
