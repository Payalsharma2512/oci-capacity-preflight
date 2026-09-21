# OCI Capacity Preflight

OCI Capacity Preflight discovers applicable OCI limits and quotas and provides operation-level preflight checks where the platform has enough information to reliably evaluate the planned request.

It is not another Limits, Quotas, or Usage dashboard. Those signals are inputs. Preflight is the decision layer on top.

Compute is the first `FULL_PREFLIGHT` implementation. The primary Compute flow is workload-based: reviewers choose a shape and instance count, and the Compute adapter calculates the required OCPUs and memory before evaluating verified service-limit and quota constraints.

Block Volume is the second `FULL_PREFLIGHT` implementation. Reviewers enter volume count and size per volume, and the Block Volume adapter calculates requested volume count and total storage GB before evaluating verified service-limit and quota constraints.

Other OCI services can be discovered from OCI Limits APIs and may initially appear as `MONITOR_ONLY`, `DISCOVERY_ONLY`, or `UNSUPPORTED` until a verified service adapter exists.

## Value Proposition

OCI Capacity Preflight helps customers catch capacity, service-limit, and quota issues before Terraform, CI/CD, or application provisioning starts. It turns live OCI limit/quota signals into a deployment readiness decision:

```text
PASS / BLOCK / Unable To Validate
```

The customer sees planned workload, current usage, available capacity, requested capacity, projected usage, blocking constraint, and remediation guidance for supported preflight adapters.

Capability levels:

| Capability | Meaning |
| --- | --- |
| `FULL_PREFLIGHT` | The tool can translate a planned operation into capacity consumption and evaluate it. |
| `MONITOR_ONLY` | OCI exposes useful usage/availability, but no verified operation mapping exists yet. |
| `DISCOVERY_ONLY` | OCI exposes the limit, but current usage/availability is not reliable enough for preflight. |
| `UNSUPPORTED` | Required OCI information is unavailable or integration work is incomplete. |

## Screenshots

Architecture:

![Architecture](architecture/architecture.png)

PASS:

![PASS](docs/screenshots/pass.png)

BLOCK:

![BLOCK](docs/screenshots/block.png)

Unable To Validate:

![Unable To Validate](docs/screenshots/unable-to-validate.png)

Customer value: the service-limit CSV/export workflow answers "what are my limits and how do they compare?" OCI Capacity Preflight answers "will this planned deployment fit before I deploy?" The two workflows are complementary.

| Capability             | Answers                                                          |
| ---------------------- | ---------------------------------------------------------------- |
| Usage                  | What am I consuming now?                                         |
| Limits                 | What is my maximum capacity?                                     |
| Quotas                 | What am I allowed to consume in this scope?                      |
| OCI Capacity Preflight | Will my planned operation fit within all applicable constraints? |

Example:

```text
Limit:
80

Usage:
72

Quota:
20

Quota usage:
18

Planned operation:
14
```

Limit says 8 service-level units remain. Quota says 2 compartment-level units remain. Preflight says `BLOCK`: the operation requires 14, but effective available capacity is 2.

## Demo

```bash
python -m cli.main preflight --demo quota --requested-ocpus 14
python -m cli.main preflight --demo pass --requested-ocpus 8
python -m cli.main risk
python -m cli.main forecast
```

`BLOCK` exits with code `2`; `UNKNOWN` exits with code `3`.

## Required Scenarios

### Quota Blocks First

```text
PRECHECK: BLOCK

Planned operation:
Add 14 OCPUs in <TARGET_REGION>

Effective available capacity:
2 OCPUs

Reason:
The target compartment has a quota of 20 OCPUs and is currently using 18.

The requested 14 OCPUs would exceed the compartment quota.

Additional service-level capacity:
8 OCPUs

Recommended actions:
1. Increase the compartment quota.
2. Deploy into another eligible compartment.
3. Reduce the requested capacity.

Service-limit increase:
Not required for this failure.
```

### Service Limit Blocks

```text
PRECHECK: BLOCK

Current service usage: 72
Service limit: 80
Available: 8
Requested: 14
Projected: 86

Reason:
Projected usage exceeds the Compute service limit by 6 OCPUs.

Recommended action:
Request a service limit increase to at least 86 OCPUs.
```

### Everything Fits

```text
PRECHECK: PASS

Current usage: 72
Service limit: 100
Quota available: 20
Requested: 8

Projected service usage: 80
Projected quota usage: 16

No known capacity constraint detected.
```

## Advisory Result

A successful preflight reduces avoidable capacity failures but cannot guarantee that the subsequent OCI operation will succeed. The actual OCI service remains authoritative, and another operation can consume capacity after preflight.

For Compute, the tool evaluates service-limit and quota capacity where the selected shape can be reliably mapped to discovered OCI limit definitions. This is not the same as proving real-time physical host or shape availability.

## OCI APIs

Service limits use OCI Limits APIs: `ListServices`, `ListLimitDefinitions`, `ListLimitValues`, and `GetResourceAvailability`. Quotas use OCI quota APIs, including `list_quotas`. The implementation discovers limits dynamically and returns `UNKNOWN` when an applicable constraint cannot be evaluated.

## Security And Deployment

For team review, run the backend and UI on a dedicated OCI Compute instance with Instance Principal authentication. Reviewers access the UI through SSH local port forwarding or OCI Bastion; port `8000` should bind to `127.0.0.1` and should not be exposed publicly.

No OCI user credentials, API keys, private keys, session tokens, or local OCI config files are required on reviewer laptops.

Minimum IAM policy:

```text
Allow dynamic-group <DYNAMIC_GROUP_NAME> to inspect limits in tenancy
Allow dynamic-group <DYNAMIC_GROUP_NAME> to read quotas in tenancy
Allow dynamic-group <DYNAMIC_GROUP_NAME> to inspect instance-family in tenancy
```

## API

- `POST /preflight`
- `POST /preflight/batch`
- `GET /services`
- `GET /services/{service}/limits`
- `GET /capacity`
- `GET /compute/shapes`
- `GET /risk`
- `GET /health`

Block Volume workload example:

```json
{
  "service": "blockvolume",
  "operation": {
    "operation": "create_volumes",
    "region": "<TARGET_REGION>",
    "availability_domain": "<VALID_AD>",
    "compartment_id": "<COMPARTMENT_OCID>",
    "workload": {
      "volume_count": 5,
      "size_gb_each": 2048
    }
  }
}
```

## CLI

```bash
oci-capacity-preflight scan
oci-capacity-preflight risk
oci-capacity-preflight forecast
oci-capacity-preflight preflight \
  --service compute \
  --resource-type instance \
  --region <TARGET_REGION> \
  --availability-domain <VALID_AD> \
  --compartment-id <COMPARTMENT_OCID> \
  --requested-ocpus 14
```

Connect the CLI to your tenancy with your existing OCI SDK/CLI config:

```bash
oci-capacity-preflight preflight \
  --real-oci \
  --auth config \
  --profile DEFAULT \
  --service compute \
  --resource-type instance \
  --region <TARGET_REGION> \
  --quota-region <HOME_REGION> \
  --availability-domain <VALID_AD> \
  --compartment-id <COMPARTMENT_OCID> \
  --requested-ocpus 14 \
  --limit-name standard-e4-core-count
```

For OCI Functions, set `OCI_CAPACITY_PREFLIGHT_MODE=oci` and use resource principals. For team review on a Compute runner, use Instance Principal by setting `OCI_CAPACITY_PREFLIGHT_AUTH=instance_principal`.

Generic API shape:

```json
{
  "service": "compute",
  "operation": {
    "operation": "create_instances",
    "resource_type": "instance",
    "region": "<TARGET_REGION>",
    "availability_domain": "<VALID_AD>",
    "compartment_id": "<COMPARTMENT_OCID>",
    "workload": {
      "shape": "VM.Standard.E5.Flex",
      "instance_count": 5,
      "ocpus_per_instance": 4,
      "memory_gb_per_instance": 32
    }
  }
}
```

Advanced/manual mode remains available for automation callers that already know the capacity delta:

```json
{
  "service": "compute",
  "operation": {
    "resource_type": "instance",
    "region": "<TARGET_REGION>",
    "availability_domain": "<VALID_AD>",
    "compartment_id": "<COMPARTMENT_OCID>",
    "requested": {
      "ocpus": 14
    }
  }
}
```

If a service or Compute shape cannot be mapped to a verified `FULL_PREFLIGHT` constraint, `/preflight` returns `UNKNOWN` / Unable To Validate rather than a false `PASS`. The Compute workload path never silently falls back to `standard-e4-core-count`.

## Terraform Workflow

```text
terraform plan
       |
       v
OCI Capacity Preflight
       |
   +---+---+
   |       |
 PASS    BLOCK
   |       |
 apply    stop
```

```bash
terraform plan -out=tfplan
terraform show -json tfplan > terraform-plan.json
oci-capacity-preflight --plan terraform-plan.json
```

## Deployment

See `docs/oci-native-deployment.md`, `docs/iam.md`, `terraform/`, and the CI/CD examples for OCI Functions, API Gateway, Scheduler, Object Storage, Notifications, and IAM guidance.

For private team review on a Compute instance, see `docs/team-review-quickstart.md`.

## Publication Safety

Before pushing to GitHub, run:

```powershell
.\scripts\check-secrets.ps1
python -m unittest discover -s tests -v
python -m compileall src cli tests
```

See `docs/github-publication-checklist.md`.
