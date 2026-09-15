# Security And Operations

- Use OCI resource principals for Functions.
- Do not store private keys.
- Do not log credentials or request headers.
- Include correlation IDs in structured logs.
- Handle pagination for OCI list APIs.
- Use OCI SDK retry strategies and exponential backoff for throttling and transient errors.
- Keep polling intervals configurable.
- Return `UNKNOWN` when data cannot be evaluated or is stale.
