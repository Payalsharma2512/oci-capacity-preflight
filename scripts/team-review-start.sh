#!/usr/bin/env bash
set -euo pipefail

export OCI_CAPACITY_PREFLIGHT_MODE="${OCI_CAPACITY_PREFLIGHT_MODE:-oci}"
export OCI_CAPACITY_PREFLIGHT_AUTH="${OCI_CAPACITY_PREFLIGHT_AUTH:-instance_principal}"
export OCI_CAPACITY_PREFLIGHT_BIND_HOST="${OCI_CAPACITY_PREFLIGHT_BIND_HOST:-127.0.0.1}"
export OCI_CAPACITY_PREFLIGHT_PORT="${OCI_CAPACITY_PREFLIGHT_PORT:-8000}"
export OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT="${OCI_CAPACITY_PREFLIGHT_COMPUTE_OCPU_LIMIT:-standard-e4-core-count}"

required_vars=(
  OCI_TENANCY_OCID
  OCI_CAPACITY_PREFLIGHT_QUOTA_REGION
)

for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 2
  fi
done

python -m uvicorn src.api.app:app \
  --host "${OCI_CAPACITY_PREFLIGHT_BIND_HOST}" \
  --port "${OCI_CAPACITY_PREFLIGHT_PORT}"
