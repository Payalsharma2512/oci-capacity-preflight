# Prevent OCI Capacity Failures Before They Happen

Without preflight:

```text
Terraform -> OCI API -> LimitExceeded / quota-related failure -> Investigate -> Identify constraint -> Request increase -> Retry
```

With preflight:

```text
Terraform Plan -> OCI Capacity Preflight -> Evaluate limits + quotas + usage -> BLOCK -> Explain exact constraint -> Recommended remediation -> Customer fixes issue -> Terraform Apply
```

**Don't wait for provisioning to fail. Preflight the capacity first.**
