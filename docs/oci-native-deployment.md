# OCI-Native Deployment

Deploy OCI Capacity Preflight inside the customer tenancy:

- OCI Functions hosts `/preflight`, `/preflight/batch`, `/risk`, scheduled scans, and notification evaluation.
- OCI API Gateway exposes the customer-owned API surface.
- OCI Scheduler invokes periodic scans.
- OCI Object Storage stores timestamped capacity snapshots and forecast history.
- OCI Notifications publishes state transitions and forecast alerts.
- OCI IAM authorizes the function through resource principals and least-privilege dynamic group policies.

This design does not require an OCI-wide centralized service. Each deployment evaluates its own tenancy.
