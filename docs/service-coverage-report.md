# Service Coverage Report

Validation target:

- Auth: Instance Principal
- Region: `us-ashburn-1`
- Availability domain: `FZyT:US-ASHBURN-AD-1`
- Quota region: `us-ashburn-1`

## Summary

Real OCI discovery found:

| Metric | Count |
| --- | ---: |
| Services discovered | 128 |
| Limits discovered | 1,032 |
| `FULL_PREFLIGHT` limit rows | 24 |
| `MONITOR_ONLY` limit rows | 1,008 |
| `DISCOVERY_ONLY` limit rows | 0 |
| `UNSUPPORTED` limit rows | 0 |

Risk states:

| Risk | Count |
| --- | ---: |
| `HEALTHY` | 560 |
| `WATCH` | 1 |
| `EXHAUSTED` | 2 |
| `UNKNOWN` | 469 |

The product rule remains: a false PASS is worse than a conservative `MONITOR_ONLY` classification.

## FULL_PREFLIGHT Operations

| Service | Operation | Limit | Scope | Unit | Usage Available | Quota Available | Capability | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Compute | `create_instances` | shape-resolved core limit | AD | OCPUs | Yes | Yes | `FULL_PREFLIGHT` | OCI `list_shapes` exposes shape metadata/quota names and resolver maps to unambiguous Compute core limits. |
| Compute | `create_instances` | shape-resolved memory limit | AD | GB memory | Yes | Yes | `FULL_PREFLIGHT` | OCI `list_shapes` exposes memory shape metadata and resolver maps to unambiguous Compute memory limits when present. |
| Block Volume | `create_volumes` | `volume-count` | AD | count | Yes | Yes | `FULL_PREFLIGHT` | Create-volume count maps directly to one consumed volume per requested volume. |
| Block Volume | `create_volumes` | `total-storage-gb` | AD | GB | Yes | Yes | `FULL_PREFLIGHT` | Requested storage is `volume_count * size_gb_each`, mapped to live OCI `total-storage-gb`. |
| Network Load Balancer | `create_network_load_balancers` | `max-nlb-flexible-count` | REGION | count | Yes | Yes | `FULL_PREFLIGHT` | Create NLB count maps directly to the live OCI flexible NLB count limit. |

`FULL_PREFLIGHT` for Network Load Balancer means NLB count only. Backend sets, backends, throughput, and connection-related constraints remain `MONITOR_ONLY` until a verified operation-to-limit mapping exists.

## Real OCI Validation Results

### Compute

Previously validated against the runner:

- Shape-aware `VM.Standard.E5.Flex`, 5 instances, 4 OCPUs each, 32 GB each.
- Service limit and quota checks evaluated OCPU and memory.
- Real quota BLOCK validated for `standard-e5-core-count`.
- Real PASS, service-limit BLOCK, quota BLOCK, invalid Flex input, unavailable shape/AD, and manual OCPU mode validated.

### Block Volume

Real OCI limits:

| Limit | Scope | Current | Limit | Available |
| --- | --- | ---: | ---: | ---: |
| `volume-count` | AD | 0 | 10,000 | 10,000 |
| `total-storage-gb` | AD | 147 | 60,372 | 60,225 |

Real validation:

- PASS: 1 volume x 50 GB.
- BLOCK by storage: requested 60,226 GB, available 60,225 GB, shortfall 1 GB.
- BLOCK by count: requested 10,001 volumes, available 10,000, shortfall 1.
- Exact boundary: requested 60,225 GB, PASS.
- Boundary + 1: requested 60,226 GB, BLOCK.
- UNABLE TO VALIDATE: missing AD because limits are AD-scoped.
- No active Block Volume quota statement was present; quota BLOCK is covered by automated tests.

### Network Load Balancer

Real OCI limits:

| Limit | Description | Scope | Current | Limit | Available |
| --- | --- | --- | ---: | ---: | ---: |
| `max-nlb-flexible-count` | Flexible Network Load Balancer Count | REGION | 0 | 8 | 8 |

Real validation:

- PASS: requested 1 NLB.
- BLOCK: requested 9 NLBs, available 8, shortfall 1.
- Exact boundary: requested 8 NLBs, PASS.
- Boundary + 1: requested 9 NLBs, BLOCK.
- Invalid input: `nlb_count >= 1` required.
- No active NLB quota statement was present; quota BLOCK is covered by automated tests.

## MONITOR_ONLY

All other visible limits are currently `MONITOR_ONLY`. Many expose useful current usage or availability, but they are not `FULL_PREFLIGHT` because we have not verified how a customer operation changes that exact limit.

Examples:

| Service | Limits | Availability Rows | Reason |
| --- | ---: | ---: | --- |
| Load Balancer | 12 | 7 | Flexible count/bandwidth and fixed-shape limits need operation-specific mapping before preflight. |
| VCN | 12 | 2 | Some operations look promising, such as VCN count and reserved public IP count, but other networking limits need API enumeration and per-resource scope validation. |
| OKE / Container Engine | 4 | 3 | Cluster limits are visible, but node capacity also depends on Compute shape preflight and OKE semantics. |
| Functions | 4 | 2 | App/function counts are visible; concurrency memory needs stronger operation mapping. |
| Database | 78 | 78 | Many DB limits are visible, but workload-to-limit mapping depends on database type, shape, ECPU/OCPU model, storage model, and deployment type. |
| Generative AI | 53 | 25 | Many limits are rate/model/dedicated-unit oriented and need product-specific operation semantics. |

## OCI APIs Used

- Limits: `ListServices`, `ListLimitDefinitions`, `ListLimitValues`, `GetResourceAvailability`
- Quotas: `ListQuotas`, `GetQuota`
- Compute shape-aware preflight: Compute `list_shapes`

No resources are provisioned for validation.

## IAM Requirements

No new IAM was required for NLB count preflight. Existing runner policies are sufficient:

```text
Allow dynamic-group runner to inspect limits in tenancy
Allow dynamic-group runner to read quotas in tenancy
Allow dynamic-group runner to inspect instance-family in tenancy
```

NLB preflight uses Limits and Quotas APIs only; it does not require NLB management permissions.

## Current Adapters

- `ComputeAdapter`
- `BlockVolumeAdapter`
- `NetworkLoadBalancerAdapter`

## Service Appendix

The following services were discovered from OCI Limits. Capability counts are limit-row counts, not operation counts.

| Service | Limits | FULL | Monitor | Availability Rows |
| --- | ---: | ---: | ---: | ---: |
| `adm` | 1 | 0 | 1 | 1 |
| `agcs` | 1 | 0 | 1 | 1 |
| `ai-anomaly-detection` | 4 | 0 | 4 | 4 |
| `ai-biometric` | 1 | 0 | 1 | 0 |
| `ai-document` | 2 | 0 | 2 | 2 |
| `ai-forecasting` | 1 | 0 | 1 | 0 |
| `ai-generative` | 53 | 0 | 53 | 25 |
| `ai-language` | 3 | 0 | 3 | 3 |
| `ai-speech` | 1 | 0 | 1 | 0 |
| `ai-vision` | 3 | 0 | 3 | 2 |
| `analytics` | 4 | 0 | 4 | 4 |
| `api-gateway` | 6 | 0 | 6 | 6 |
| `big-data` | 40 | 0 | 40 | 40 |
| `block-storage` | 8 | 2 | 6 | 7 |
| `compute` | 268 | 21 | 247 | 268 |
| `container-engine` | 4 | 0 | 4 | 3 |
| `database` | 78 | 0 | 78 | 78 |
| `data-flow` | 22 | 0 | 22 | 20 |
| `data-science` | 53 | 0 | 53 | 53 |
| `devops` | 16 | 0 | 16 | 8 |
| `faas` | 4 | 0 | 4 | 2 |
| `filesystem` | 10 | 0 | 10 | 9 |
| `load-balancer` | 12 | 0 | 12 | 7 |
| `mysql` | 70 | 0 | 70 | 69 |
| `network-load-balancer-api` | 1 | 1 | 0 | 1 |
| `object-storage` | 2 | 0 | 2 | 2 |
| `vcn` | 12 | 0 | 12 | 2 |
| `vcnip` | 3 | 0 | 3 | 2 |

The remaining discovered services had no `FULL_PREFLIGHT` rows in this run and remain `MONITOR_ONLY` until an operation-specific adapter is verified. The full JSON discovery artifact was generated by `scripts/real_oci_capacity_discovery.py`.

## Technical Gaps

- Operation-level metadata is still hand-authored in adapters; future work should make adapter capability metadata richer and more uniform.
- The tenancy-wide discovery cache is in-memory TTL only; it should become an explicit background refresh job with cache status.
- Quota BLOCK validation depends on real quota statements existing in the tenancy. Synthetic quota tests cover behavior where no real quota exists.
- Several promising services need service-specific APIs before they can be safely preflighted.

## Customer Experience Gaps

- The UI should show operation-level coverage more prominently than service-level coverage.
- The capacity page should expose cache age and refresh status.
- MONITOR_ONLY rows need better “why not preflight yet?” messages by service family.

## Recommended Next Phase

Do not add another adapter until the operation-level capability model is polished in the UI. After that, evaluate the next adapters in this order:

1. Load Balancer flexible count/bandwidth, because availability is visible but operation mapping is more nuanced than NLB.
2. VCN/reserved public IP count, with Networking API validation for scope and existing usage semantics.
3. Functions app/function count, if OCI Functions operation semantics can be mapped cleanly.
