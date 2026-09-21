# Adversarial Test Report

## Summary

This report covers the complex adversarial test suite in `tests/complex/`.

Run command:

```bash
python -m unittest discover -s tests/complex -v
```

Result:

```text
Ran 32 tests
OK (expected failures=5)
```

The expected failures are known product gaps. They are intentionally captured as executable tests so they remain visible during future development.

## What Passed

- Multiple simultaneous constraints are evaluated together.
- Effective available capacity is the minimum known applicable capacity.
- AD-level blockers can be distinguished from regional/service/quota blockers when represented as separate constraint types.
- Service-limit-only blocker returns service-limit remediation.
- Quota-only blocker returns quota remediation.
- Exact boundary `request = available` passes.
- Exact boundary `request = available + 1` blocks.
- Zero request passes when capacity is known.
- Very large requests block.
- Batch result does not silently pass when one operation blocks.
- Batch result does not silently pass when one operation is unknown.
- Multi-region results can distinguish one blocked region from one viable region.
- Multi-AD results can distinguish AD-level constraints.
- Missing permission simulations return `UNKNOWN`, not `PASS`.
- Simulated OCI API failures return `UNKNOWN`, not `PASS`.
- Stale data returns `UNKNOWN`, not `PASS`, and includes last evaluation timestamp.
- Unknown required constraint prevents false `PASS`.
- Zero and missing values avoid divide-by-zero and false `PASS`.
- Forecast warnings do not override immediate `PASS`.
- Immediate blockers override forecast context.
- Recovery state can be recognized.
- Notifications avoid repeated sends before cooldown.
- Static preflight results are idempotent across 100 repeated runs.
- BLOCK responses contain key customer comprehension fields.
- Unable-to-validate responses include a reason.

## Expected Failures / Product Gaps

| Gap | Current Behavior | Desired Behavior |
|---|---|---|
| Both service limit and quota block | Only the primary/smallest blocking constraint remediation is returned | Return remediation for all blocking constraints |
| Negative request | Can produce `PASS` because projected usage decreases | Reject as invalid input |
| Decimal request for integer-only resource | Can produce `PASS` | Reject or round only with explicit resource schema |
| Workload abstraction | Users must manually calculate total capacity | Accept workload shape/count and derive OCPUs, memory, storage |
| Unit conversion | No conversion between requests/second and requests/minute style units | Add explicit unit schema and conversion rules |

## False Positive / False Negative Analysis

| Scenario | Expected | Actual | Correct? | Risk | Fix |
|---|---|---|---|---|---|
| Small request with sufficient limit/quota | PASS | PASS | Yes | Low | None |
| Request equals available | PASS | PASS | Yes | Low | None |
| Request exceeds available by 1 | BLOCK | BLOCK | Yes | Low | None |
| Service limit blocks, quota passes | BLOCK / SERVICE_LIMIT | BLOCK / SERVICE_LIMIT | Yes | Low | None |
| Quota blocks, service limit passes | BLOCK / COMPARTMENT_QUOTA | BLOCK / COMPARTMENT_QUOTA | Yes | Low | None |
| Both service limit and quota block | BLOCK with both remediations | BLOCK with primary remediation only | Partial | Customer may fix only one blocker and fail again | Return all blocking remediations |
| Missing limits permission | Unable To Validate | UNKNOWN from API/engine | Safe internally; UI should translate | Medium UX risk | Keep API raw, improve UI and API message model |
| Missing quota permission | Unable To Validate | UNKNOWN from API/engine | Safe internally; UI should translate | Medium UX risk | Keep API raw, improve UI and API message model |
| Stale data | Unable To Validate | UNKNOWN / STALE | Yes | Low | Surface last refresh prominently |
| Unknown AD capacity with known service/quota | Unable To Validate | UNKNOWN | Yes | Low | None |
| Negative request | Reject input | PASS possible | No | False PASS | Add request validation |
| Decimal request for integer-only resource | Reject input | PASS possible | No | False PASS | Add resource dimension schema |
| Workload count x per-instance capacity | Derive total request | Not implemented | No | False PASS if user enters instance count as OCPUs | Add workload abstraction |
| Unit conversion | Convert or reject mismatched units | Not implemented | No | False PASS/BLOCK possible | Add unit registry |
| Forecast says exhaustion soon but current request fits | PASS with warning | PASS without integrated warning | Partial | Missed proactive warning | Integrate forecast with preflight result |
| Current request blocks and forecast is healthy | BLOCK | BLOCK | Yes | Low | None |
| Repeated same request with static data | Same result each time | Same result | Yes | Low | None |
| Notification threshold stays same | No repeat before cooldown | No repeat before cooldown | Yes | Low | None |

## Error Classification Assessment

The engine currently treats simulated OCI errors as `UNKNOWN`, which is safe because it avoids false `PASS`.

Missing product behavior:

- no structured error category for retryable errors
- no structured category for customer input errors
- no structured category for permission errors
- no structured category for unsupported capability
- no structured category for service outage

The UI has started translating common `UNKNOWN` causes into friendlier messages, but the API response should eventually include structured fields such as:

```json
{
  "customer_status": "UNABLE_TO_VALIDATE",
  "error_category": "PERMISSION",
  "next_action": "Grant read quotas to the instance principal dynamic group."
}
```

## Race Condition Assessment

Preflight is advisory. It does not reserve capacity.

Required customer-facing statement:

```text
PASS means no known constraint was detected at evaluation time. It does not reserve capacity.
```

A realistic race-condition test should be added when provisioning integration exists:

1. Run preflight and receive `PASS`.
2. Simulate another workload consuming capacity.
3. Attempt provisioning.
4. Verify documentation and response make clear that preflight is not a reservation.

## Final Product Assessment

### 1. Can this safely be used as a pre-deployment gate today?

It can be used as an advisory prototype gate for Compute OCPU checks where OCI Limits, Quotas, and availability APIs are reachable. It should not be called production-ready yet.

### 2. What OCI constraints are genuinely evaluated today?

- OCI Limits resource availability for mapped limits such as `compute/standard-e4-core-count`
- OCI Quotas via the tenancy home region
- Current usage when exposed through OCI resource availability
- Stale/unknown safety behavior in the decision engine

### 3. What constraints are not evaluated?

- Full shape availability
- Memory as a first-class compute dimension
- GPU dimensions beyond explicitly mapped limits
- Subnet/IP capacity
- boot volume and block volume dimensions by workload
- load balancer bandwidth by planned configuration
- image compatibility
- actual IAM permissions needed for provisioning
- cost/budget policy
- Terraform plan semantics beyond basic OCPU extraction
- capacity reservation semantics

### 4. What can cause a false PASS?

- Negative requested capacity
- Decimal values for integer-only resources
- User enters instance count instead of total OCPUs
- Missing resource dimension mapping, such as memory or storage
- Unit mismatch, such as requests/second versus requests/minute
- Constraint not modeled by a provider

### 5. What can cause a false BLOCK?

- Unit mismatch
- Incorrect limit mapping
- Stale or incorrectly scoped snapshots if a provider supplies them as fresh
- Treating compartment quota as applicable when quota statement parsing is too broad

### 6. Biggest Technical Gap

The biggest technical gap is the lack of a resource schema/workload model. The tool needs to know whether a field is integer-only, which dimensions apply, how to calculate total capacity from workload shape/count, and how to convert units.

### 7. Biggest Customer-Experience Gap

The biggest customer-experience gap is that API-level `UNKNOWN` lacks structured customer-facing categories and next actions. The UI now translates common causes, but the API should return those fields directly.

### 8. What Should Be Implemented Next?

1. Add input validation for negative and invalid decimal requests.
2. Add a workload abstraction: instance count, OCPUs per instance, memory per instance, storage.
3. Return all blocking constraints and all remediations when multiple constraints block.
4. Add structured error categories and customer-facing next actions.
5. Add resource dimension schemas and unit conversion rules.
6. Expand providers for memory, block storage, load balancer, subnet IP capacity, and GPUs.
7. Integrate forecast warnings without letting forecast override immediate blockers.
