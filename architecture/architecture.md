# Architecture

```text
                OCI tenancy
                     |
       +-------------+-------------+
       |             |             |
     Limits        Quotas        Usage
       |             |             |
       +-------------+-------------+
                     |
                     v
            Capacity Intelligence
                     |
       +-------------+-------------+
       |             |             |
   Current Risk   Forecasting   Preflight
       |             |             |
       +-------------+-------------+
                     |
                     v
             Decision Engine
                     |
          +----------+----------+
          |                     |
        PASS                   BLOCK
          |                     |
      continue             Remediation
                                  |
                  +---------------+---------------+
                  |               |               |
             Increase limit   Increase quota   Change placement
                               /capacity
```

Each customer deploys or invokes the solution in its own tenancy. There is no OCI-wide centralized service; scale comes from independent tenant-local execution.
