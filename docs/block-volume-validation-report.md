# Block Volume FULL_PREFLIGHT Validation

Validation target:

- Auth: Instance Principal
- Region: `us-ashburn-1`
- Availability domain: `FZyT:US-ASHBURN-AD-1`
- Quota region: `us-ashburn-1`

## Supported Operation

`BlockVolumeAdapter` supports create-volume workload preflight:

```json
{
  "service": "blockvolume",
  "operation": {
    "operation": "create_volumes",
    "region": "<REGION>",
    "availability_domain": "<AVAILABILITY_DOMAIN>",
    "compartment_id": "<COMPARTMENT_OCID>",
    "workload": {
      "volume_count": 5,
      "size_gb_each": 2048
    }
  }
}
```

This translates to:

```text
volume_count = +5
storage_gb = +10240
```

## Live OCI Limit Mapping

The adapter resolves limits dynamically from OCI limit definitions. In the validated tenancy, the selected mappings were:

| Metric | Limit name | Scope | Unit | Current | Limit | Available |
| --- | --- | --- | --- | ---: | ---: | ---: |
| `volume_count` | `volume-count` | AD | count | 0 | 10,000 | 10,000 |
| `storage_gb` | `total-storage-gb` | AD | GB | 147 | 60,372 | 60,225 |

Replica storage is only evaluated when the workload requests replication:

| Limit name | Scope | Unit |
| --- | --- | --- |
| `total-replica-storage-gb` | AD | GB |

Backup limits are not evaluated for ordinary create-volume preflight because the operation does not create backups.

## Real OCI Results

| Scenario | Result | Notes |
| --- | --- | --- |
| Small request: 1 volume, 50 GB | PASS | Both count and storage checks passed. |
| Storage service-limit block | BLOCK | Requested 60,226 GB with 60,225 GB available; shortfall 1 GB. |
| Exact storage boundary | PASS | Requested exactly 60,225 GB available. |
| Boundary + 1 | BLOCK | Requested 60,226 GB; storage limit blocked. |
| Volume-count service-limit block | BLOCK | Requested 10,001 volumes with 10,000 available; shortfall 1 volume. |
| Missing AD | UNABLE TO VALIDATE | `volume-count` and `total-storage-gb` are AD-scoped, so `availability_domain` is required. |
| Invalid input | UNABLE TO VALIDATE | `volume_count >= 1` and `size_gb_each > 0` are required. |

Direct `/preflight` API-path validation returned PASS for 1 volume, 50 GB with checks against:

- `volume-count`
- `total-storage-gb`

## Quota Behavior

No active Block Volume quota statements were visible in the validated tenancy. The real runner verified quota API readability, but there was no suitable live Block Volume quota to trigger a real quota-specific BLOCK.

The automated tests cover:

- quota BLOCK for `total-storage-gb`
- quota permission failure returning UNABLE TO VALIDATE
- quota metric mapping for `volume-count`, `total-storage-gb`, and `total-replica-storage-gb`

## IAM

No new IAM policy is required beyond the existing runner policies:

```text
Allow dynamic-group runner to inspect limits in tenancy
Allow dynamic-group runner to read quotas in tenancy
Allow dynamic-group runner to inspect instance-family in tenancy
```

Block Volume preflight uses OCI Limits and Quotas APIs. It does not require Block Volume resource read permissions for the current create-volume limit/quota check.

## Limitations

- This evaluates OCI service-limit and quota capacity only.
- It does not guarantee physical storage placement or downstream provisioning success.
- AD-scoped Block Volume checks require `availability_domain`; the tool returns UNABLE TO VALIDATE if it is missing.
- Real quota BLOCK was not demonstrated because the tenancy had no active Block Volume quota statement.
