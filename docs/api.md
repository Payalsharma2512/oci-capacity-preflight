# API

All responses include `advisory: true`.

`POST /preflight` evaluates one planned operation.

Example:

```json
{
  "service": "compute",
  "operation": {
    "resource_type": "instance",
    "region": "us-ashburn-1",
    "availability_domain": "<VALID_AD>",
    "compartment_id": "<COMPARTMENT_OCID>",
    "requested": {
      "ocpus": 14
    }
  }
}
```

If no verified `FULL_PREFLIGHT` adapter exists for the service, the API returns `UNKNOWN` instead of a false `PASS`.

`POST /preflight/batch` evaluates multiple operations and returns one result per operation plus `overall_decision`.

`GET /services` returns OCI services discovered from the Limits API.

`GET /services/{service}/limits` returns discovered limits for one service with capability classification.

`GET /capacity` returns the capability matrix:

```text
Service | Limit | Scope | Limit Value | Usage | Available | Preflight Support
```

`GET /risk` returns current exhaustion states: `HEALTHY`, `WATCH`, `WARNING`, `CRITICAL`, `EXHAUSTED`, or `UNKNOWN`.
