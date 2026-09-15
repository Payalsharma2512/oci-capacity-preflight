curl -sS -X POST "$OCI_CAPACITY_PREFLIGHT_URL/preflight" \
  -H 'content-type: application/json' \
  -d '{"quota_region":"<HOME_REGION>","operation":{"service":"compute","resource_type":"instance","region":"<TARGET_REGION>","availability_domain":"<VALID_AD>","compartment_id":"<COMPARTMENT_OCID>","requested_delta":{"ocpus":14}}}'
