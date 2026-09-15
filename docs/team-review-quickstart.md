# Team Review Quickstart

This guide runs OCI Capacity Preflight on a dedicated OCI Compute instance with Instance Principal authentication. Reviewers do not need OCI CLI sessions, API keys, private keys, or user credentials on their laptops.

## Architecture

```text
Reviewer laptop
  |
  | SSH tunnel or OCI Bastion session
  v
OCI Compute instance, localhost only
  - http://127.0.0.1:8000/
  - POST /preflight
  - GET /health
  |
  | Instance Principal
  v
OCI Limits and Quotas APIs
```

Port `8000` must stay bound to `127.0.0.1` on the instance. Do not add a public security-list or NSG ingress rule for port `8000`.

## OCI Setup

Create or choose a dedicated Compute instance. Record:

```text
TENANCY_OCID=<tenancy OCID>
INSTANCE_OCID=<review instance OCID>
INSTANCE_COMPARTMENT_OCID=<compartment containing the review instance>
TARGET_COMPARTMENT_OCID=<compartment reviewers will preflight>
TARGET_REGION=<target region, for example us-ashburn-1>
QUOTA_REGION=<tenancy home region, for example us-ashburn-1>
AVAILABILITY_DOMAIN=<full AD name, for example <VALID_AD>>
```

Create a dynamic group scoped to the dedicated review instance:

```bash
oci iam dynamic-group create \
  --compartment-id "$TENANCY_OCID" \
  --name oci-capacity-preflight-review-instance \
  --description "Dedicated instance principal for OCI Capacity Preflight team review" \
  --matching-rule "ALL {instance.id = '$INSTANCE_OCID'}"
```

Create the minimum policy required for this prototype:

```bash
oci iam policy create \
  --compartment-id "$TENANCY_OCID" \
  --name oci-capacity-preflight-review-readonly \
  --description "Read-only OCI Limits and Quotas access for Capacity Preflight review" \
  --statements '[
    "Allow dynamic-group oci-capacity-preflight-review-instance to inspect limits in tenancy",
    "Allow dynamic-group oci-capacity-preflight-review-instance to inspect quotas in tenancy"
  ]'
```

Allow a few minutes for IAM policy propagation.

## Instance Install

SSH to the dedicated OCI Compute instance and install the app:

```bash
sudo dnf install -y git python3.11 python3.11-pip
git clone <PRIVATE_REPO_URL> oci-capacity-preflight
cd oci-capacity-preflight
python3.11 -m pip install --user -e ".[oci,api]"
```

Configure with environment variables:

```bash
cp examples/team-review.env.example .env.team-review
vi .env.team-review
```

Example `.env.team-review`:

```bash
OCI_TENANCY_OCID=<TENANCY_OCID>
OCI_CAPACITY_PREFLIGHT_QUOTA_REGION=us-ashburn-1
OCI_CAPACITY_PREFLIGHT_MODE=oci
OCI_CAPACITY_PREFLIGHT_AUTH=instance_principal
OCI_CAPACITY_PREFLIGHT_BIND_HOST=127.0.0.1
OCI_CAPACITY_PREFLIGHT_PORT=8000
OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT=standard-e4-core-count
```

Load the environment:

```bash
set -a
source .env.team-review
set +a
```

## Validate Instance Principal

Run this before starting the UI:

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

Expected result:

```text
OCI INSTANCE PRINCIPAL VALIDATION
===============================
Limits API: OK
Quotas API: OK
```

## One-Command Startup

Start the backend and UI:

```bash
bash scripts/team-review-start.sh
```

The same private service hosts:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/health
http://127.0.0.1:8000/preflight
```

Quick health check from the instance:

```bash
curl http://127.0.0.1:8000/health
```

## Secure Reviewer Access

Recommended access is SSH local port forwarding:

```bash
ssh -L 8000:127.0.0.1:8000 opc@<INSTANCE_PUBLIC_IP_OR_BASTION_TARGET>
```

Then reviewers open this on their own laptop:

```text
http://localhost:8000/
```

If the instance is private, use OCI Bastion managed SSH port forwarding instead of a public IP. Keep network ingress limited to SSH or Bastion access. Do not expose application port `8000` publicly.

## Team Review UI

The UI is read-only with respect to OCI. Reviewers can enter:

- service
- region
- quota/home region
- availability domain
- compartment OCID
- requested OCPUs

The UI calls `POST /preflight` and shows:

- `PASS`, `BLOCK`, or a friendly validation error such as `Missing OCI Permission`
- effective available capacity
- blocking constraint
- current usage
- applicable limit or quota
- projected usage
- remediation

The API still returns raw `UNKNOWN` for automation when a check cannot be fully evaluated. The UI translates common `UNKNOWN` causes into reviewer-friendly messages and keeps the raw reason under `Technical Details`.

## Troubleshooting

`401 NotAuthenticated`:

- Confirm the app is running on an OCI Compute instance.
- Confirm `OCI_CAPACITY_PREFLIGHT_AUTH=instance_principal`.
- Confirm the instance principal dynamic group rule matches the instance OCID.
- Wait a few minutes after creating or editing IAM policy.

`404 NotAuthorizedOrNotFound` or `403 NotAllowed` for quotas:

- Confirm the dynamic group has `inspect quotas in tenancy`.
- Confirm quota calls use the tenancy home region in `OCI_CAPACITY_PREFLIGHT_QUOTA_REGION`.

`Invalid parameter availabilityDomain`:

- Use the full availability-domain name, not a short AD alias.
- Find names with:

```bash
oci iam availability-domain list --auth instance_principal --compartment-id "$OCI_TENANCY_OCID"
```

Friendly validation error in the UI:

- Read the next action in the result panel.
- Expand `Technical Details` only when debugging.
- Run the validation command again.
- Check `/health` to confirm `mode=oci`, `auth=instance_principal`, and `tenancy_configured=true`.
