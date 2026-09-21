#!/usr/bin/env bash
set -euo pipefail

export OCI_MODE="${OCI_MODE:-live}"
export AUTH="${AUTH:-instance_principal}"
export OCI_CAPACITY_PREFLIGHT_MODE="${OCI_CAPACITY_PREFLIGHT_MODE:-oci}"
export OCI_CAPACITY_PREFLIGHT_AUTH="${OCI_CAPACITY_PREFLIGHT_AUTH:-${AUTH}}"
export OCI_CAPACITY_PREFLIGHT_BIND_HOST="${OCI_CAPACITY_PREFLIGHT_BIND_HOST:-127.0.0.1}"
export OCI_CAPACITY_PREFLIGHT_PORT="${OCI_CAPACITY_PREFLIGHT_PORT:-8000}"
export OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT="${OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT:-standard-e5-core-count}"

required_vars=(
  OCI_TENANCY_OCID
  OCI_CAPACITY_PREFLIGHT_REGION
  OCI_CAPACITY_PREFLIGHT_QUOTA_REGION
  OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID
)

for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 2
  fi
done

doctor_args=(
  --real-oci
  --auth "${OCI_CAPACITY_PREFLIGHT_AUTH}"
  --tenancy-id "${OCI_TENANCY_OCID}"
  --region "${OCI_CAPACITY_PREFLIGHT_REGION}"
  --quota-region "${OCI_CAPACITY_PREFLIGHT_QUOTA_REGION}"
  --compartment-id "${OCI_CAPACITY_PREFLIGHT_COMPARTMENT_ID}"
  --limit-name "${OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT}"
)
if [[ -n "${OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN:-}" ]]; then
  doctor_args+=(--availability-domain "${OCI_CAPACITY_PREFLIGHT_AVAILABILITY_DOMAIN}")
fi

python -m cli.main doctor "${doctor_args[@]}"

python -m uvicorn src.api.app:app \
  --host "${OCI_CAPACITY_PREFLIGHT_BIND_HOST}" \
  --port "${OCI_CAPACITY_PREFLIGHT_PORT}"
