from __future__ import annotations

from src.capacity.models import CapacitySnapshot


DEFAULT_THRESHOLDS = {"HEALTHY": 0.70, "WATCH": 0.80, "WARNING": 0.90, "CRITICAL": 1.0}


def risk_state(snapshot: CapacitySnapshot, thresholds: dict[str, float] | None = None) -> dict:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    if snapshot.is_unknown():
        return {"state": "UNKNOWN", "utilization": None}
    utilization = snapshot.current / snapshot.maximum if snapshot.maximum else None
    if utilization is None:
        state = "UNKNOWN"
    elif utilization >= 1:
        state = "EXHAUSTED"
    elif utilization >= thresholds["WARNING"]:
        state = "CRITICAL"
    elif utilization >= thresholds["WATCH"]:
        state = "WARNING"
    elif utilization >= thresholds["HEALTHY"]:
        state = "WATCH"
    else:
        state = "HEALTHY"
    return {"state": state, "utilization": None if utilization is None else round(utilization, 4)}
