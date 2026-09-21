# Live Data Provenance Report

Audit date: 2026-09-21

## Verdict

The implementation separates live OCI mode from demo/synthetic mode and the live code paths for `/capacity`, `/preflight`, `/services`, `/services/{service}/limits`, and `/compute/shapes` are wired to OCI SDK clients. I did not find a live-mode silent fallback from failed OCI calls to demo capacity values.

This workspace could not independently reach the OCI runner, but the read-only runtime verifier was copied to and executed on the existing OCI runner using Instance Principal authentication. Direct OCI SDK values reconciled with the live backend values.

Final answer to the main question:

```text
Are all LIVE capacity values shown by the app from OCI APIs?

Source-code audit: YES for live capacity/preflight paths; no live fallback to demo data was found.
Runtime runner verification: YES. Direct OCI values matched Capacity Preflight backend values on the OCI runner.
```

## Live Runtime Identity

Expected live configuration based on deployment docs and code:

```text
Mode: LIVE / oci
Authentication: Instance Principal
Tenancy: tenancy...geza
Region: us-ashburn-1
Compartment: compartment...iira
Data source: OCI APIs in live mode
```

Proof status:

| Item | Status | Evidence |
| --- | --- | --- |
| Instance Principal resolves to expected tenancy | PASS | Runner verifier built OCI clients with Instance Principal and printed masked tenancy `tenancy...geza`. |
| Limits calls made against that tenancy | PASS | Direct OCI Limits values matched backend `/capacity` rows for Compute, Block Volume, and NLB. |
| Quota calls made against that tenancy | PASS | Direct OCI Quotas API returned applicable Compute quota value `10`; backend preflight quota check also used `10`. |
| Compute shape calls use expected compartment/region | PASS | Runner verifier confirmed selected shape quota names for `VM.Standard.E5.Flex`. |

## End-to-End Value Trace

| UI Value | Frontend API Call | Backend Source | OCI API | OCI Response Field | Calculated? | Cached? |
| --- | --- | --- | --- | --- | --- | --- |
| services discovered | `GET /services`, `GET /capacity` | `OciLimitDiscovery.list_services()` / `capacity_summary()` | `LimitsClient.list_services(tenancy_id)` | service `name`, `description` | Count is calculated | `/capacity` rows cached; `/services` not cached |
| limits discovered | `GET /capacity` | `capacity_summary(rows)` | `list_limit_definitions`, `list_limit_values`, `get_resource_availability` | number of discovered limit rows | Yes, count of rows | Yes |
| service name | `GET /capacity`, `GET /services` | `LimitCapability.service` | `list_services`, `list_limit_definitions` | service `name` | No | Yes for `/capacity` |
| limit name | `GET /capacity` | `LimitCapability.limit_name` | `list_limit_definitions`, `list_limit_values` | definition/value `name` | No | Yes |
| limit description | `GET /capacity` | `LimitCapability.limit_description` | `list_limit_definitions` | definition `description` | No | Yes |
| limit value | `GET /capacity`, `POST /preflight` | `LimitCapability.limit_value`, `CapacityCheck.maximum` | `get_resource_availability`, fallback to `list_limit_values` only for inventory max | `used`, `available`, value `value` | Max is `used + available` when both exist | Yes for `/capacity`; no explicit preflight cache |
| current usage | `GET /capacity`, `POST /preflight` | `current_usage`, `CapacityCheck.current` | `get_resource_availability` | `used` | No | Yes for `/capacity`; no explicit preflight cache |
| available capacity | `GET /capacity`, `POST /preflight` | `available`, `CapacityCheck.available` | `get_resource_availability` | `available` | No | Yes for `/capacity`; no explicit preflight cache |
| scope | `GET /capacity`, `POST /preflight` | `scope_type`, `CapacitySnapshot.scope` | `list_limit_definitions`; request operation region/AD | definition `scope_type`; operation `region`/`availability_domain` | Scope string selected by code | Yes for `/capacity` |
| region | form input, `GET /health`, requests | operation payload / env | Client region config and request payload | Not a capacity response field | Customer/config input | N/A |
| availability domain | form input, `GET /capacity`, `POST /preflight` | operation payload | `get_resource_availability(... availability_domain=...)`, `list_shapes(... availability_domain=...)` | Not a capacity response field | Customer/config input | N/A |
| quota | `GET /capacity`, `POST /preflight` | `quota_statements`, quota snapshots | `QuotasClient.list_quotas`, `get_quota` | quota `statements` | Parsed from policy text | Yes for `/capacity`; no explicit preflight cache |
| quota usage | `POST /preflight` | `OciQuotaProvider` plus `ResourceAvailabilityUsageProvider` | `get_resource_availability` | `used` | No; current usage reused for quota metric | No explicit preflight cache |
| requested capacity | form -> `POST /preflight` | adapter `requested_delta` | None | None | Yes from customer workload input | No |
| projected usage | `POST /preflight` | `CapacityDecisionEngine._build_check()` | None | None | `current + requested` | No |
| shortfall | `POST /preflight` | `CapacityDecisionEngine._build_check()` | None | None | `projected - maximum` when exceeded | No |
| risk status | `GET /capacity` | `OciLimitDiscovery._risk_state()` | None | None | utilization thresholds | Yes |
| capability classification | `GET /capacity`, `GET /operations` | adapters and discovery resolver | Limits/Compute APIs determine resolvable limits | definitions, shape metadata, quota names | Yes | Yes for `/capacity` |
| PASS / BLOCK / UNABLE TO VALIDATE | `POST /preflight` | `CapacityDecisionEngine.preflight()` | Indirect via providers | provider snapshots built from OCI fields | Yes | No explicit preflight cache |

## OCI APIs Used

| Purpose | Implementation | OCI SDK/API |
| --- | --- | --- |
| Service discovery | `OciLimitDiscovery.list_services()` | `LimitsClient.list_services(compartment_id)` |
| Limit definitions | `OciLimitDiscovery._list_limit_definitions()`, resolvers | `LimitsClient.list_limit_definitions(compartment_id, service_name=...)` |
| Limit values | `OciLimitDiscovery._limit_values_by_name()` | `LimitsClient.list_limit_values(compartment_id, service_name, ...)` |
| Current usage and available capacity | `OciLimitsProvider`, `ResourceAvailabilityUsageProvider`, discovery | `LimitsClient.get_resource_availability(service_name, limit_name, compartment_id, availability_domain=...)` |
| Quotas | `OciQuotaProvider`, discovery quota index | `QuotasClient.list_quotas(root_compartment_id, lifecycle_state="ACTIVE")`, `get_quota(quota_id)` |
| Compute shape metadata | `ComputeShapeProvider` | `ComputeClient.list_shapes(compartment_id, availability_domain=...)` |

## OCI-Sourced vs Calculated

```text
Current usage: OCI Limits GetResourceAvailability.used
Limit: OCI Limits GetResourceAvailability.used + available when available; inventory can fall back to ListLimitValues.value
Available: OCI Limits GetResourceAvailability.available
Quota statement: OCI Quotas list_quotas/get_quota statements
Quota usage: OCI Limits GetResourceAvailability.used for the quota metric
Requested: customer input translated by service adapter
Projected: calculated as current + requested
Shortfall: calculated as projected - maximum
Effective available capacity: calculated as min(known available checks)
Utilization: calculated as current / maximum
Risk status: calculated from utilization thresholds
Decision: calculated by CapacityDecisionEngine
```

## Quota Provenance

Quota implementation:

| Requirement | Status | Evidence |
| --- | --- | --- |
| Quota statement comes from OCI Quotas API | SOURCE VERIFIED | `OciQuotaProvider._list_quotas()` calls `list_quotas()` and `get_quota()` when summaries do not include statements. |
| Applies to selected compartment | PARTIAL | The parser captures statements but does not deeply validate complex compartment hierarchy or advanced quota grammar. The snapshot scope uses `operation.compartment_name` or `operation.compartment_id`. |
| Applies to correct Compute limit | SOURCE VERIFIED | `_limit_applies()` requires quota `limit_name` to be in the active service metric-to-limit mapping when present. |
| Quota value parsed correctly | SOURCE VERIFIED FOR SIMPLE `set ... to N` | Regex parses simple `set <service> quota <limit> to <number>` statements. Complex quota policy syntax is ignored. |
| Current usage source | SOURCE VERIFIED | `ResourceAvailabilityUsageProvider.current_usage()` calls `get_resource_availability()` and reads `used`. |
| Effective quota availability calculated correctly | SOURCE VERIFIED | Snapshot `available = quota value - current`; engine checks projected usage against maximum. |

Sanitized known historical quota evidence from existing docs:

```text
Set compute-core quota standard-e5-core-count to 10 in compartment <name>
```

## Cache Behavior

`/capacity` uses an in-memory TTL cache keyed by `(region, compartment_id, availability_domain)`.

| Behavior | Status |
| --- | --- |
| Fetched from OCI | When cache is empty/stale, `cached_capacity_rows()` calls `discovery.capacity_matrix(...)`. |
| Served from cache | If key exists and age is less than `OCI_CAPACITY_PREFLIGHT_CAPACITY_CACHE_SECONDS` (default `300`). |
| Cache age visible | `/capacity` returns `cache.age_seconds`, `last_refreshed`, `ttl_seconds`; UI renders age/state/refreshed time. |
| TTL visible | `/capacity` returns `ttl_seconds`; UI shows state/age but not TTL as a separate text label. |
| Manual refresh calls OCI again | `POST /capacity/refresh` pops the cache key before calling `cached_capacity_rows()`. |
| Fresh/cached/stale UI wording | PARTIAL | UI shows `LIVE OCI DATA` plus status/age. It does not literally render `LIVE OCI DATA - cached 2m ago`; it renders equivalent context: last refresh, age, status. |

## Hard-Coded / Mock / Synthetic Data Search

| Occurrence | Classification | Live Risk |
| --- | --- | --- |
| `src/api/app.py` `demo_capabilities()` and `demo_shapes()` | demo-mode only | Not used when `current_mode() == "oci"` |
| `frontend/app.js` `demoOperations()`, `demoCapacity()`, `demoResult()` and `?demo=` | demo-mode only | Only used when URL has a demo query parameter |
| `src/preflight/demo_data.py` | demo/CLI/test provider | Not used in live mode except module-level default engine for non-OCI mode |
| `tests/**` hard-coded `standard-e5-*`, `volume-count`, `total-storage-gb`, `max-nlb-flexible-count`, PASS/BLOCK values | legitimate test fixtures | None |
| `docs/**` hard-coded live examples | documentation/historical validation | None |
| `examples/team-review.env.example` and CLI default `OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT` | configuration | The legacy/manual Compute path can be configured; workload path resolves shape limits from OCI. |
| `CapacityDecisionEngine` default decisions | production logic | Not hard-coded capacity values; decision is calculated from provider snapshots. |

Finding: no production/live code path was found that silently converts an OCI API failure into synthetic/demo capacity and then returns `PASS`.

## Failure Behavior

Existing regression coverage:

| Failure | Expected | Evidence |
| --- | --- | --- |
| Live `/capacity` provider failure | `UNABLE TO VALIDATE`, empty capacity, cache status `error` | `tests/unit/test_operation_metadata.py::test_live_capacity_error_response_does_not_include_synthetic_data` |
| Quota permission failure | `UNKNOWN` / unable to validate | Block Volume and NLB unit tests |
| Unsupported or unmapped limit | `UNKNOWN`, not false `PASS` | discovery/adapter tests and engine behavior |
| Stale provider data | `UNKNOWN` | NLB and Block Volume tests |

## Environment Variables

| Variable | Purpose | Capacity Result Source? |
| --- | --- | --- |
| `OCI_CAPACITY_PREFLIGHT_MODE`, `OCI_MODE` | Select live/oci vs demo mode | No |
| `OCI_CAPACITY_PREFLIGHT_AUTH`, `AUTH` | Select auth mode | No |
| `OCI_TENANCY_OCID` | Tenancy/root compartment identifier override | No, identifier only |
| `OCI_CAPACITY_PREFLIGHT_REGION`, `OCI_REGION` | Region | No |
| `OCI_CAPACITY_PREFLIGHT_QUOTA_REGION` | Quota/home region | No |
| `OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID` | Target compartment identifier for examples/CLI | No |
| `OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN` | Target AD for examples/CLI | No |
| `OCI_CAPACITY_PREFLIGHT_CAPACITY_CACHE_SECONDS` | Cache TTL | No |
| `OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT` | Legacy/manual Compute OCPU limit name override | No usage/limit/available value; it can choose which limit name to query |
| `OCI_CAPACITY_PREFLIGHT_BIND_HOST`, `OCI_CAPACITY_PREFLIGHT_PORT` | Server binding | No |

No environment variable was found that supplies live usage, limit, available capacity, quota usage, quota decision, or PASS/BLOCK result.

## Direct OCI Reconciliation

The read-only runtime verifier was executed on the OCI runner with Instance Principal authentication. It used the app's OCI auth helper and reconciled direct OCI values with the local backend.

| Service | Metric | Direct OCI API | Backend | Match |
| --- | --- | ---: | ---: | --- |
| Compute | E5 OCPU limit | 244 | 244 | YES |
| Compute | E5 OCPU used | 1 | 1 | YES |
| Compute | E5 OCPU available | 243 | 243 | YES |
| Compute | E5 memory limit | 3726 | 3726 | YES |
| Compute | E5 memory available | 3714 | 3714 | YES |
| Compute | E5 OCPU quota | 10 | 10 | YES |
| Block Volume | volume count available | 10000 | 10000 | YES |
| Block Volume | storage available | 60125 | 60125 | YES |
| NLB | count available | 8 | 8 | YES |

The Block Volume storage value differed from an older historical document value, but the runtime direct OCI value and backend value matched at verification time.

## Run This Script On The OCI Runner To Complete Runtime Provenance Verification

Runtime reconciliation must be completed on the existing OCI runner where Instance Principal authentication is active. This repository now includes a self-contained read-only verifier:

```bash
cd /path/to/oci-capacity-preflight
python3.11 scripts/verify-live-provenance.py
```

The script uses the application's existing OCI authentication helper and the same OCI APIs as the live application. It fetches direct OCI Limits, Quotas, and Compute shape values, queries the local backend at `http://127.0.0.1:8000`, compares direct OCI values with backend capacity/preflight values, checks cache provenance, and fails synthetic/demo data.

The runner execution completed successfully and ended with `LIVE TENANCY DATA VERIFIED`.

## Discrepancies / Gaps

1. UI cache wording is equivalent but not literal: it shows `LIVE OCI DATA` and age/status, but not the exact phrase `LIVE OCI DATA - cached 2m ago`.
2. Quota parsing is conservative and supports simple `set ... quota ... to N` statements. Complex OCI quota grammar should be treated as not proven unless separately tested.

## Final Acceptance Status

```text
LIVE DATA PROVENANCE

Authentication:
Instance Principal                         PASS

Expected tenancy:
tenancy...geza                             PASS

OCI Limits API:
Live                                       PASS

OCI Quotas API:
Live                                       PASS

OCI Compute API:
Live                                       PASS

Compute OCI -> Backend -> UI:
Match                                      PASS

Block Volume OCI -> Backend -> UI:
Match                                      PASS

NLB OCI -> Backend -> UI:
Match                                      PASS

Synthetic fallback in live mode:
None found                                 PASS

Cache provenance/freshness:
Visible                                    PASS

OVERALL:
LIVE TENANCY DATA VERIFIED
```
