from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Observation:
    timestamp: datetime
    usage: float


def linear_growth_forecast(history: list[Observation], maximum: float) -> dict:
    if len(history) < 2:
        return {"days_to_exhaustion": None, "confidence": "INSUFFICIENT_DATA"}
    ordered = sorted(history, key=lambda item: item.timestamp)
    first, last = ordered[0], ordered[-1]
    elapsed_days = (last.timestamp - first.timestamp).total_seconds() / 86400
    if elapsed_days <= 0:
        return {"days_to_exhaustion": None, "confidence": "INSUFFICIENT_DATA"}
    daily_growth = (last.usage - first.usage) / elapsed_days
    if daily_growth <= 0:
        return {"days_to_exhaustion": None, "confidence": "LOW", "method": "LINEAR_GROWTH"}
    return {"days_to_exhaustion": round((maximum - last.usage) / daily_growth, 1), "confidence": "MEDIUM", "method": "LINEAR_GROWTH"}
