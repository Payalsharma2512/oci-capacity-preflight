# Notifications

Notifications are emitted for state transitions into `WARNING`, `CRITICAL`, `EXHAUSTED`, forecasted exhaustion within the configured number of days, recovery, and `UNKNOWN`.

The state machine prevents storms by sending on state changes and enforcing a cooldown for repeated states.
