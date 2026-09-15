# OCI DevOps Gate

Add a build stage before deployment:

```bash
terraform plan -out=tfplan
terraform show -json tfplan > terraform-plan.json
oci-capacity-preflight --plan terraform-plan.json
```

Fail the stage when the command exits with `2` (`BLOCK`) or `3` (`UNKNOWN`).
