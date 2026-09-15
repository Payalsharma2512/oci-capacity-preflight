from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class NotificationState:
    state: str
    last_sent_at: datetime | None = None


def should_notify(previous: NotificationState | None, new_state: str, cooldown_minutes: int = 60) -> bool:
    now = datetime.now(timezone.utc)
    if previous is None or previous.state != new_state:
        return new_state in {"WARNING", "CRITICAL", "EXHAUSTED", "UNKNOWN", "RECOVERY"}
    if previous.last_sent_at is None:
        return True
    return now - previous.last_sent_at >= timedelta(minutes=cooldown_minutes)
