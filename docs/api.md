# API

All responses include `advisory: true`.

`POST /preflight` evaluates one planned operation.

`POST /preflight/batch` evaluates multiple operations and returns one result per operation plus `overall_decision`.

`GET /risk` returns current exhaustion states: `HEALTHY`, `WATCH`, `WARNING`, `CRITICAL`, `EXHAUSTED`, or `UNKNOWN`.
