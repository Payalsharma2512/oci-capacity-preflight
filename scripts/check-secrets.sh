#!/usr/bin/env bash
set -euo pipefail

root="${1:-.}"

exclude_args=(
  --glob '!.git/**'
  --glob '!__pycache__/**'
  --glob '!.pytest_cache/**'
  --glob '!.venv/**'
  --glob '!venv/**'
  --glob '!docs/screenshots/**'
  --glob '!*.pyc'
  --glob '!*.png'
  --glob '!*.jpg'
  --glob '!*.jpeg'
  --glob '!*.gif'
  --glob '!*.ico'
  --glob '!scripts/check-secrets.ps1'
  --glob '!scripts/check-secrets.sh'
  --glob '!docs/github-publication-checklist.md'
)

patterns=(
  'ocid1\.'
  '-----BEGIN'
  'fingerprint\s*='
  'key_file\s*='
  'session[_-]?token'
  'ssh-key'
  'C:\\Users\\'
  '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
  '\b(?!(10|127|169\.254|172\.(1[6-9]|2[0-9]|3[0-1])|192\.168)\.)(([1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\.){3}([1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\b'
)

failed=0
for pattern in "${patterns[@]}"; do
  if rg -n "${exclude_args[@]}" --pcre2 "$pattern" "$root"; then
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "Potential secrets or environment-specific values found."
  exit 1
fi

echo "Secret scan passed."
