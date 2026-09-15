# Terraform Preflight Gate

```bash
terraform plan -out=tfplan
terraform show -json tfplan > terraform-plan.json
oci-capacity-preflight --plan terraform-plan.json
terraform apply tfplan
```

The CLI exits non-zero on `BLOCK` or `UNKNOWN`, so CI/CD can stop before `terraform apply`.
