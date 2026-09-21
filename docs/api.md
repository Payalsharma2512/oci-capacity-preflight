# API

All responses include `advisory: true`.

`POST /preflight` evaluates one planned operation.

Example:

```json
{
  "service": "compute",
  "operation": {
    "operation": "create_instances",
    "resource_type": "instance",
    "region": "us-ashburn-1",
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

Advanced/manual mode:

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

Block Volume workload mode:

```json
{
  "service": "blockvolume",
  "operation": {
    "operation": "create_volumes",
    "region": "us-ashburn-1",
    "availability_domain": "<VALID_AD>",
    "compartment_id": "<COMPARTMENT_OCID>",
    "workload": {
      "volume_count": 5,
      "size_gb_each": 2048
    }
  }
}
```

Block Volume create-volume preflight evaluates `volume-count` and `total-storage-gb` when those limits resolve unambiguously from OCI limit definitions. In the validated tenancy these limits are AD-scoped, so `availability_domain` is required.

If no verified `FULL_PREFLIGHT` adapter or shape-to-limit mapping exists, the API returns `UNKNOWN` instead of a false `PASS`.

`POST /preflight/batch` evaluates multiple operations and returns one result per operation plus `overall_decision`.

`GET /services` returns OCI services discovered from the Limits API.

`GET /services/{service}/limits` returns discovered limits for one service with capability classification.

`GET /capacity` returns the capability matrix:

```text
Service | Limit | Scope | Current | Limit | Available | Utilization | Capability
```

`GET /compute/shapes` returns Compute shapes from OCI Compute `list_shapes` for the selected compartment and optional availability domain.

`GET /risk` returns current exhaustion states: `HEALTHY`, `WATCH`, `WARNING`, `CRITICAL`, `EXHAUSTED`, or `UNKNOWN`.
