from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Decision(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


class CheckStatus(str, Enum):
    OK = "OK"
    WOULD_EXCEED = "WOULD_EXCEED"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    ERROR = "ERROR"


class CapabilityLevel(str, Enum):
    FULL_PREFLIGHT = "FULL_PREFLIGHT"
    MONITOR_ONLY = "MONITOR_ONLY"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class Operation:
    service: str
    resource_type: str | None
    region: str
    compartment_id: str
    requested_delta: dict[str, float]
    availability_domain: str | None = None
    compartment_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Operation":
        if "operation" in payload:
            operation = dict(payload["operation"])
            if payload.get("service") and not operation.get("service"):
                operation["service"] = payload["service"]
            payload = operation
        requested = payload.get("requested_delta") or payload.get("requested") or {}
        return cls(
            service=payload["service"],
            resource_type=payload.get("resource_type"),
            region=payload["region"],
            availability_domain=payload.get("availability_domain"),
            compartment_id=payload["compartment_id"],
            compartment_name=payload.get("compartment_name"),
            requested_delta={k: float(v) for k, v in requested.items()},
            metadata=payload.get("metadata", {}),
        )


@dataclass
class CapacitySnapshot:
    constraint_type: str
    service: str
    limit_name: str
    scope: str
    metric: str
    current: float | None
    maximum: float | None
    available: float | None
    unit: str | None = None
    capability: CapabilityLevel = CapabilityLevel.FULL_PREFLIGHT
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stale_after_seconds: int = 900
    reason: str | None = None
    remediation_action: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def is_unknown(self) -> bool:
        return self.current is None or self.maximum is None or self.available is None

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return (now - self.timestamp).total_seconds() > self.stale_after_seconds


@dataclass
class CapacityCheck:
    constraint_type: str
    service: str
    limit_name: str
    scope: str
    metric: str
    unit: str | None
    current: float | None
    maximum: float | None
    requested_delta: float
    projected: float | None
    status: CheckStatus
    shortfall: float | None = None
    available: float | None = None
    reason: str | None = None
    last_successful_evaluation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_type": self.constraint_type,
            "service": self.service,
            "limit_name": self.limit_name,
            "scope": self.scope,
            "metric": self.metric,
            "unit": self.unit or self.metric,
            "current": self.current,
            "maximum": self.maximum,
            "available": self.available,
            "requested_delta": self.requested_delta,
            "projected": self.projected,
            "status": self.status.value,
            "shortfall": self.shortfall,
            "reason": self.reason,
            "last_successful_evaluation": self.last_successful_evaluation,
        }


@dataclass
class PreflightResult:
    decision: Decision
    confidence: str
    advisory: bool
    operation: Operation
    effective_available_capacity: float | None
    primary_blocking_constraint: str | None
    checks: list[CapacityCheck]
    recommendations: list[dict[str, str]]
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    unknown_reasons: list[str] = field(default_factory=list)

    def exit_code(self) -> int:
        return 0 if self.decision is Decision.PASS else 2 if self.decision is Decision.BLOCK else 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "advisory": self.advisory,
            "operation": {
                "service": self.operation.service,
                "resource_type": self.operation.resource_type,
                "region": self.operation.region,
                "availability_domain": self.operation.availability_domain,
                "compartment_id": self.operation.compartment_id,
                "compartment_name": self.operation.compartment_name,
                "requested_delta": self.operation.requested_delta,
                "metadata": self.operation.metadata,
            },
            "effective_available_capacity": self.effective_available_capacity,
            "primary_blocking_constraint": self.primary_blocking_constraint,
            "checks": [check.to_dict() for check in self.checks],
            "recommendations": self.recommendations,
            "unknown_reasons": self.unknown_reasons,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


@dataclass
class LimitCapability:
    service: str
    service_description: str | None
    limit_name: str
    limit_description: str | None
    scope_type: str | None
    limit_value: float | None
    current_usage: float | None
    available: float | None
    capability: CapabilityLevel
    unit: str | None = None
    reason: str | None = None
    is_eligible_for_increase: bool | None = None
    region: str | None = None
    availability_domain: str | None = None
    resource_availability_supported: bool | None = None
    quota_statements: list[str] = field(default_factory=list)
    quota_readable: bool | None = None
    utilization: float | None = None
    risk_state: str | None = None
    api_limitation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "service_description": self.service_description,
            "limit_name": self.limit_name,
            "limit_description": self.limit_description,
            "scope_type": self.scope_type,
            "limit_value": self.limit_value,
            "current_usage": self.current_usage,
            "available": self.available,
            "capability": self.capability.value,
            "unit": self.unit,
            "reason": self.reason,
            "is_eligible_for_increase": self.is_eligible_for_increase,
            "region": self.region,
            "availability_domain": self.availability_domain,
            "resource_availability_supported": self.resource_availability_supported,
            "quota_statements": self.quota_statements,
            "quota_readable": self.quota_readable,
            "utilization": self.utilization,
            "risk_state": self.risk_state,
            "api_limitation": self.api_limitation,
        }


@dataclass(frozen=True)
class ComputeWorkloadIntent:
    region: str
    availability_domain: str | None
    compartment_id: str
    shape: str
    instance_count: int
    ocpus_per_instance: float | None = None
    memory_gb_per_instance: float | None = None
    compartment_name: str | None = None


@dataclass(frozen=True)
class ComputeShape:
    name: str
    ocpus: float | None
    memory_gb: float | None
    is_flex: bool
    gpus: float | None = None
    processor_description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ocpus": self.ocpus,
            "memory_gb": self.memory_gb,
            "is_flex": self.is_flex,
            "gpus": self.gpus,
            "processor_description": self.processor_description,
            "raw": self.raw,
        }
