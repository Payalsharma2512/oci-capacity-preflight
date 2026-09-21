# OCI Capacity Preflight Value Proposition

## Summary

OCI Capacity Preflight discovers applicable OCI limits and quotas and provides operation-level preflight checks where the platform has enough information to reliably evaluate the planned request.

Compute is the first `FULL_PREFLIGHT` implementation. Customers can describe the Compute workload they want to deploy by shape and instance count; the tool calculates OCPUs and memory. Other services can still be discovered and monitored, but they are not treated as deployment-ready checks until a verified adapter can translate customer intent into limit consumption.

## Customer Problem

Customers often discover capacity, service-limit, or quota issues only after Terraform, CI/CD, or application provisioning has already started. That creates failed changes, manual troubleshooting, SRs, and avoidable delays.

## What This Tool Answers

```text
Can this specific deployment proceed right now?
```

The tool returns:

- `PASS`: no known capacity constraint detected
- `BLOCK`: the request is expected to exceed a known constraint
- friendly validation errors: authentication, IAM, region, AD, or API input must be fixed before trusting the result

The tool does not return `PASS` for `MONITOR_ONLY`, `DISCOVERY_ONLY`, or `UNSUPPORTED` limits.

## What Reviewers See

- effective available capacity
- planned Compute workload
- blocking constraint
- current usage
- applicable limit or quota
- requested capacity
- projected usage
- remediation guidance

For Compute, service-limit capacity and real-time physical host/shape availability are shown as separate concepts. This prototype does not claim host availability unless a future integration explicitly checks it.

## Differentiation

The OCI Service Limit Tool shared by the team is useful for service-limit inventory and CSV comparison across regions or tenancies.

OCI Capacity Preflight is different: it is a deployment decision layer.

| Question | Service Limit CSV Tool | OCI Capacity Preflight |
|---|---|---|
| What are my service limits? | Yes | Uses as input |
| How do limits compare between regions? | Yes | Not primary focus |
| Will this planned deployment fit? | No | Yes |
| Does it include current usage/availability? | Limited/not primary | Yes |
| Does it evaluate quota impact? | Limited/not primary | Yes |
| Does it return PASS/BLOCK before deployment? | No | Yes |
| Does it provide remediation? | No | Yes |
| Does it classify unsupported limits safely? | No | Yes |

## Positioning

```text
Service Limit Tool = reporting and comparison
OCI Capacity Preflight = deployment readiness gate
```

Together, the tools are complementary. The CSV tool helps identify limit differences. Capacity Preflight helps customers decide whether a specific supported deployment should proceed.

## Team Review Test Plan

1. Validate instance principal access:

```bash
python3.11 -m cli.main validate-oci \
  --auth instance_principal \
  --tenancy-id "$OCI_TENANCY_OCID" \
  --region "$TARGET_REGION" \
  --quota-region "$OCI_CAPACITY_PREFLIGHT_QUOTA_REGION" \
  --availability-domain "$AVAILABILITY_DOMAIN" \
  --compartment-id "$TARGET_COMPARTMENT_OCID" \
  --limit-name standard-e4-core-count
```

Expected:

```text
Limits API: OK
Quotas API: OK
```

2. Start the private review UI:

```bash
bash scripts/team-review-start.sh
```

3. Access through SSH tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 opc@<INSTANCE>
```

4. Open:

```text
http://localhost:8000/
```

5. Test outcomes:

- small OCPU request: expect `PASS`
- very large OCPU request: expect `BLOCK`
- invalid AD name: expect friendly validation error

## Reviewer Laptop Requirements

Reviewer laptops do not need OCI credentials, API keys, private keys, or `oci session authenticate`. The app runs inside the tenancy using OCI Instance Principal.
