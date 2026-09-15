curl -sS -X POST "$OCI_CAPACITY_PREFLIGHT_URL/preflight" \
  -H 'content-type: application/json' \
  -d '{"operation":{"service":"compute","resource_type":"instance","region":"us-phoenix-1","availability_domain":"AD-1","compartment_id":"<COMPARTMENT_OCID>","requested_delta":{"ocpus":14}}}'
