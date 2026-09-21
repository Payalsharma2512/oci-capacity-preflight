# OCI-Wide Discovery Report

Validation target:

- Auth: Instance Principal
- Region: `us-ashburn-1`
- Quota region: `us-ashburn-1`
- Availability domain: `<availability-domain>`

## Discovery Summary

The real OCI runner discovered:

| Metric | Count |
| --- | ---: |
| Services | 128 |
| Limits | 1,032 |
| `FULL_PREFLIGHT` | 21 |
| `MONITOR_ONLY` | 1,011 |
| `DISCOVERY_ONLY` | 0 |
| `UNSUPPORTED` | 0 |

Risk states:

| Risk | Count |
| --- | ---: |
| `HEALTHY` | 560 |
| `WATCH` | 1 |
| `EXHAUSTED` | 2 |
| `UNKNOWN` | 469 |

`FULL_PREFLIGHT` remains limited to Compute limits that can be mapped through OCI shape metadata and OCI limit definitions. Other services with visible usage/availability are intentionally classified as `MONITOR_ONLY` until the planned customer operation can be translated to the exact OCI limit consumption.

## Validated Compute FULL_PREFLIGHT Limits

These limits were classified as `FULL_PREFLIGHT` because OCI `list_shapes` exposed shape metadata and quota names, and the resolver found unambiguous OCI limit definitions. The check evaluates service-limit and quota capacity, not guaranteed real-time host availability.

| Limit | Scope | Current | Limit | Available | Quota |
| --- | --- | ---: | ---: | ---: | --- |
| `standard-e5-core-count` | AD | 1 | 244 | 243 | `Set compute-core quota standard-e5-core-count to 10 in compartment RioImanputra` |
| `standard-e5-memory-count` | AD | 12 | 3,726 | 3,714 | none |
| `dense-io-e6-ax-core-count` | AD | 0 | 576 | 576 | none |
| `dense-io-e6-ax-memory-count` | AD | 0 | 6,912 | 6,912 | none |
| `standard-e4-core-count` | AD | 5 | 300 | 295 | none |
| `standard-e4-memory-count` | AD | 65 | 5,000 | 4,935 | none |

Additional Compute families were also resolved from OCI shape metadata in this AD, including Standard E2/E3/E6, Optimized3, Standard A4/Ax, Standard X12/Ax, and Standard3 core/memory limits.

## Candidate Services Observed

| Service | Limits | Availability rows | Scope | Capability |
| --- | ---: | ---: | --- | --- |
| `database` | 78 | 78 | AD/REGION | `MONITOR_ONLY` |
| `ai-generative` | 53 | 25 | REGION | `MONITOR_ONLY` |
| `load-balancer` | 12 | 7 | REGION | `MONITOR_ONLY` |
| `vcn` | 12 | 2 | GLOBAL/REGION | `MONITOR_ONLY` |
| `block-storage` | 8 | 7 | AD/REGION | `MONITOR_ONLY` |
| `container-engine` | 4 | 3 | REGION | `MONITOR_ONLY` |
| `faas` | 4 | 2 | REGION | `MONITOR_ONLY` |
| `network-load-balancer-api` | 1 | 1 | REGION | `MONITOR_ONLY` |

## Best Next FULL_PREFLIGHT Candidates

### 1. Block Volume

OCI exposes strong limit and availability signals:

- `volume-count`, AD scope, current `0`, limit `10000`, available `10000`
- `total-storage-gb`, AD scope, current `147`, limit `60372`, available `60225`
- `total-replica-storage-gb`, AD scope, current `0`, limit `256000`, available `256000`
- backup/free-tier limits are also visible

Customer operation to translate:

- Create volume or clone/restore volume.
- Inputs: AD, compartment, number of volumes, volume size GB, replica setting if applicable.

Additional OCI API needed:

- Block Volume APIs for volume/backup shape and replication intent if reading from Terraform or existing config.

Can honestly become `FULL_PREFLIGHT`:

- Yes, for create-volume capacity checks where requested count and size GB are explicit.
- Keep backup/replica paths separate until those operations are mapped cleanly.

### 2. Network Load Balancer

OCI exposes a simple regional capacity signal:

- `max-nlb-flexible-count`, REGION scope, current `0`, limit `8`, available `8`

Customer operation to translate:

- Create Network Load Balancer.
- Inputs: region, compartment, NLB count.

Additional OCI API needed:

- Network Load Balancer API for existing NLB details if enriching request/plan parsing.

Can honestly become `FULL_PREFLIGHT`:

- Yes, for create-NLB count checks. It is a small, clean adapter because the exposed limit is count-based and the operation maps directly to one requested NLB.

### 3. Load Balancer

OCI exposes useful regional usage/availability:

- `lb-flexible-count`, REGION scope, current `0`, limit `663`, available `663`
- `lb-flexible-bandwidth-sum`, REGION scope, current `0`, limit `75000`, available `75000`
- fixed bandwidth count limits such as `lb-100mbps-count`, current `1`, limit `1`, available `0`

Customer operation to translate:

- Create Load Balancer.
- Inputs: flexible vs fixed shape, min/max bandwidth, count.

Additional OCI API needed:

- Load Balancer API or Terraform plan parsing to identify flexible shape details and bandwidth.

Can honestly become `FULL_PREFLIGHT`:

- Yes, but it is slightly more complex than NLB because flexible bandwidth must map to both count and bandwidth-sum constraints.

## Other Services

VCN/Public IP is promising for selected operations:

- `reserved-public-ip-count`, REGION scope, current `4`, limit `48`, available `44`
- `vcn-count`, REGION scope, current `35`, limit `45`, available `10`
- Many per-VCN limits expose limit values but not usage through resource availability.

This can become `FULL_PREFLIGHT` for create VCN and reserve public IP operations, but gateway/subnet/security-rule checks need Networking API enumeration.

OKE is partially suitable:

- `cluster-count`, `enhanced-cluster-count`, and `virtual-node-count` expose availability.
- Node capacity still depends on Compute shape preflight plus OKE-specific limits.

Functions is partially suitable:

- `application-count` and `function-count` expose availability.
- Concurrency memory limits are visible but usage/availability was not exposed in this run.

Database and Generative AI expose many limits, but operation-to-limit mapping is more product-specific. They should stay `MONITOR_ONLY` until adapters understand workload shape, ECPU/OCPU/storage/dedicated-unit semantics, and any service-specific provisioning APIs.

## Product Gaps Found

- Full OCI-wide discovery took more than two minutes on the runner. `/capacity` should be cached or refreshed in a background job for the team-review UI.
- Quota statements were only observed for the Compute E5 core limit in this tenancy. The discovery code can surface quota statements, but most candidate services had no active quota statements visible.
- OCI resource availability can expose limit/usage capacity, but it does not prove real-time physical host availability. The UI and docs should continue to call this out.
