# Capacity Readiness Check - Manager Demo

## Primary Message

This dashboard checks planned infrastructure changes against live capacity, service-limit, and quota signals before deployment.

`PASS` means no known service-limit/quota constraint was detected. It does not guarantee physical host availability or successful provisioning, and it does not reserve capacity.

## Problem

Customers often discover service-limit and quota constraints only after Terraform, CI/CD, or provisioning has already started. That causes failed changes, manual troubleshooting, SRs, and avoidable deployment delays.

## Existing OCI Capabilities

OCI already provides the source signals: service limits, resource availability, quota statements, and service-specific metadata such as Compute shapes. These are valuable inventory and governance inputs, but they do not directly answer whether a specific planned operation will exceed a known constraint.

## What This Prototype Adds

- Discovers OCI limits across the tenancy.
- Labels each limit as `FULL_PREFLIGHT`, `MONITOR_ONLY`, `DISCOVERY_ONLY`, or `UNSUPPORTED`.
- Runs operation-level preflight only where a verified operation-to-limit mapping exists.
- Shows requested, current, available, projected, blocking constraint, and remediation for supported operations.
- Clearly labels all views as `LIVE OCI DATA` or `DEMO / SYNTHETIC DATA`.
- Shows cache/freshness metadata so reviewers know when the inventory was collected.

## Current FULL_PREFLIGHT Services and Operations

- Compute: `create_instances`, including `VM.Standard.E5.Flex`, 5 instances, 4 OCPUs each, 32 GB each. The runner validated PASS, service-limit BLOCK, quota BLOCK for `standard-e5-core-count`, invalid Flex input, unavailable shape/AD, and manual OCPU mode.
- Block Volume: `create_volumes`, including 5 x 2 TB. The runner validated live OCI limits `volume-count` and `total-storage-gb`, PASS for small requests, BLOCK at storage/count boundaries, exact-boundary PASS, missing-AD UNABLE TO VALIDATE, and invalid-input UNABLE TO VALIDATE.
- Network Load Balancer: `create_network_load_balancers`, including 5 NLBs. The runner validated live OCI limit `max-nlb-flexible-count`, PASS for 1 NLB, exact-boundary PASS at 8 NLBs, BLOCK at 9 NLBs, and invalid-input handling.

## OCI-Wide Discovery Results

The recorded OCI runner used Instance Principal auth in `us-ashburn-1`, quota region `us-ashburn-1`, and AD `FZyT:US-ASHBURN-AD-1`.

Real discovery found:

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

Examples that remain `MONITOR_ONLY` include Load Balancer, VCN, OKE / Container Engine, Functions, Database, and Generative AI. Many expose useful limit or availability data, but they are not marked `FULL_PREFLIGHT` until the customer operation can be translated into exact limit consumption.

## Three-Minute Demo Flow

1. OCI Capacity Overview: show discovered services, discovered limits, capability counts, risk counts, and freshness.
2. Compute: run 5 x `VM.Standard.E5.Flex`, 4 OCPUs, 32 GB. Show PASS / BLOCK / UNABLE TO VALIDATE with requested, current, available, projected, blocking constraint, and remediation.
3. Block Volume: run 5 x 2 TB and show the same decision fields.
4. Network Load Balancer: run 5 NLBs and show the same decision fields.
5. Preflight Coverage: show Compute, Block Volume, and NLB create-count as `FULL_PREFLIGHT`, plus examples that remain `MONITOR_ONLY`.

## Current Limitations

- `PASS` is advisory and limited to known service-limit/quota constraints.
- It does not guarantee physical host availability, storage placement, downstream service provisioning, or capacity reservation.
- `FULL_PREFLIGHT` exists only for the three verified operation paths above.
- NLB `FULL_PREFLIGHT` means create-count only; backend sets, backends, throughput, and connection-related checks remain `MONITOR_ONLY`.
- The capacity cache is in-memory TTL-backed, not a persistent background inventory service.
- This workspace may run in demo mode if OCI credentials or runner environment variables are not configured; do not claim live validation was performed here unless the runner is configured and used.

## Next Expansion Path

Do not add more adapters until the demo flow and capability messaging are accepted. The next likely candidates are Load Balancer flexible count/bandwidth, VCN or reserved public IP count, and Functions app/function count, each only after operation-to-limit mapping is verified against OCI APIs.
