# OCI Capacity Preflight Pressure Test Report

Run date: 2026-09-10

## Results

- Pressure tests: 25 total, 24 passed, 1 failed.
- Full repository tests: 44 total, 43 passed, 1 failed.

## Unexpected Behavior Discovered

`CapacityDecisionEngine.preflight()` returned `PASS` when no provider returned any constraint snapshots. That was unsafe because a missing required service limit, quota, AD capacity, or provider failure could look like a successful preflight. This is now covered by the pressure suite and should remain `UNKNOWN`.

Failing test:

```text
tests/pressure/test_customer_scenarios.py::test_24_missing_required_constraint_must_never_produce_pass
Expected: UNKNOWN
Actual: PASS
```

## Security Concerns

- OCI API exception text is surfaced in `UNKNOWN` reasons. That is useful for troubleshooting, but production code should sanitize messages to avoid leaking OCIDs, policy details, endpoint URLs, or SDK internals.
- The CLI prints recommendations on a `PASS` result in the demo path, which can confuse automation logs and human reviewers.
- Terraform sample uses a placeholder Object Storage namespace and is not yet a complete least-privilege deployment module.

## OCI API And Model Assumptions To Verify

- `GetResourceAvailability` response field names and semantics for all targeted limits, especially whether `available` and `used` are always present when supported.
- Exact exception classes/status-code access patterns for OCI SDK `ServiceError` handling.
- Quota statement parsing. OCI quota statements are policy text; the MVP parser only handles simple `set <service> quota <limit> to <number>` statements.
- Scope behavior for `REGION`, `AD`, `GLOBAL`, `subscription_id`, and `external_location`.
- Whether quota APIs alone can determine effective compartment quota usage, or whether service-specific usage APIs are required per resource type.

## Customer-Experience Gaps

- A `PASS` result currently does not explicitly list which constraints were evaluated in user-facing CLI output.
- Unknown/missing evidence needs a clearer top-level explanation and remediation path.
- The UI is a static demo and does not call the API.
- Batch output needs clearer per-operation summaries for CI/CD logs.

## False-Positive Risks

- Highest risk: no snapshots returned currently produces `PASS`.
- A requested metric absent from an operation defaults to zero for a matching snapshot, which can hide malformed inputs.
- Provider filtering is outside the engine contract; a broad or buggy provider can evaluate the wrong region or compartment.
- Unsupported availability returns `UNKNOWN` only if the provider emits an unknown snapshot. If the provider drops it, the engine can pass.

## False-Negative Risks

- Conservative `UNKNOWN` on stale data or unsupported availability can block safe operations until data quality is restored.
- Multiple constraints with mismatched scopes can over-block if provider filtering is too broad.
- Linear forecasting can overstate exhaustion risk after short-term bursts.
