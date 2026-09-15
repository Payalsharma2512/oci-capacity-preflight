from __future__ import annotations

from datetime import datetime, timezone

from .models import CapabilityLevel, CapacityCheck, CapacitySnapshot, CheckStatus, Decision, Operation, PreflightResult
from .providers import CapacityProvider


class CapacityDecisionEngine:
    def __init__(self, providers: list[CapacityProvider], stale_after_seconds: int = 900):
        self.providers = providers
        self.stale_after_seconds = stale_after_seconds

    def preflight(self, operation: Operation) -> PreflightResult:
        snapshots: list[CapacitySnapshot] = []
        recommendation_candidates: list[tuple[CapacitySnapshot, dict[str, str]]] = []
        for provider in self.providers:
            provider_snapshots = provider.evaluate(operation)
            snapshots.extend(provider_snapshots)
            for snapshot in provider_snapshots:
                recommendation_candidates.append((snapshot, provider.remediation(snapshot)))

        checks = [self._build_check(operation, snapshot) for snapshot in snapshots]
        unknowns = [c.reason or f"{c.constraint_type} could not be evaluated" for c in checks if c.status in {CheckStatus.UNKNOWN, CheckStatus.STALE, CheckStatus.ERROR}]
        blockers = [c for c in checks if c.status is CheckStatus.WOULD_EXCEED]
        known_available = [c.available for c in checks if c.available is not None and c.status is not CheckStatus.STALE]

        if not checks:
            decision = Decision.UNKNOWN
            confidence = "LOW"
            unknowns = ["No capacity constraints were evaluated for this operation."]
        elif unknowns:
            decision = Decision.UNKNOWN
            confidence = "LOW"
        elif blockers:
            decision = Decision.BLOCK
            confidence = "HIGH"
        else:
            decision = Decision.PASS
            confidence = "HIGH" if checks else "LOW"

        primary = self._primary_constraint(blockers)
        effective = min(known_available) if known_available else None
        if decision is Decision.UNKNOWN:
            effective = None

        actionable_constraints = set()
        if primary:
            actionable_constraints = {primary}
        elif unknowns:
            actionable_constraints = {check.constraint_type for check in checks if check.status in {CheckStatus.UNKNOWN, CheckStatus.STALE, CheckStatus.ERROR}}

        deduped_recommendations = []
        seen = set()
        for snapshot, item in recommendation_candidates:
            if actionable_constraints and snapshot.constraint_type not in actionable_constraints:
                continue
            key = (item.get("action"), item.get("reason"))
            if key not in seen:
                deduped_recommendations.append(item)
                seen.add(key)

        return PreflightResult(
            decision=decision,
            confidence=confidence,
            advisory=True,
            operation=operation,
            effective_available_capacity=effective,
            primary_blocking_constraint=primary,
            checks=checks,
            recommendations=deduped_recommendations,
            unknown_reasons=unknowns,
        )

    def preflight_batch(self, operations: list[Operation]) -> dict:
        results = [self.preflight(operation) for operation in operations]
        overall = Decision.PASS
        if any(result.decision is Decision.BLOCK for result in results):
            overall = Decision.BLOCK
        elif any(result.decision is Decision.UNKNOWN for result in results):
            overall = Decision.UNKNOWN
        return {"overall_decision": overall.value, "advisory": True, "results": [r.to_dict() for r in results]}

    def _build_check(self, operation: Operation, snapshot: CapacitySnapshot) -> CapacityCheck:
        requested = float(operation.requested_delta.get(snapshot.metric, 0))
        now = datetime.now(timezone.utc)
        if snapshot.capability is not CapabilityLevel.FULL_PREFLIGHT:
            return CapacityCheck(
                constraint_type=snapshot.constraint_type,
                service=snapshot.service,
                limit_name=snapshot.limit_name,
                scope=snapshot.scope,
                metric=snapshot.metric,
                unit=snapshot.unit or snapshot.metric,
                current=snapshot.current,
                maximum=snapshot.maximum,
                available=snapshot.available,
                requested_delta=requested,
                projected=None,
                status=CheckStatus.UNKNOWN,
                reason=snapshot.reason or f"{snapshot.service}.{snapshot.limit_name} is {snapshot.capability.value}; it cannot be used for operation-level preflight yet.",
                last_successful_evaluation=snapshot.timestamp.isoformat(),
            )
        if snapshot.is_stale(now):
            return CapacityCheck(
                constraint_type=snapshot.constraint_type,
                service=snapshot.service,
                limit_name=snapshot.limit_name,
                scope=snapshot.scope,
                metric=snapshot.metric,
                unit=snapshot.unit or snapshot.metric,
                current=snapshot.current,
                maximum=snapshot.maximum,
                available=snapshot.available,
                requested_delta=requested,
                projected=None if snapshot.current is None else snapshot.current + requested,
                status=CheckStatus.STALE,
                reason=f"{snapshot.constraint_type} data is stale.",
                last_successful_evaluation=snapshot.timestamp.isoformat(),
            )
        if snapshot.is_unknown():
            return CapacityCheck(
                constraint_type=snapshot.constraint_type,
                service=snapshot.service,
                limit_name=snapshot.limit_name,
                scope=snapshot.scope,
                metric=snapshot.metric,
                unit=snapshot.unit or snapshot.metric,
                current=snapshot.current,
                maximum=snapshot.maximum,
                available=snapshot.available,
                requested_delta=requested,
                projected=None,
                status=CheckStatus.UNKNOWN,
                reason=snapshot.reason or f"{snapshot.constraint_type} availability is UNKNOWN.",
                last_successful_evaluation=snapshot.timestamp.isoformat(),
            )

        projected = snapshot.current + requested
        if projected > snapshot.maximum:
            return CapacityCheck(
                constraint_type=snapshot.constraint_type,
                service=snapshot.service,
                limit_name=snapshot.limit_name,
                scope=snapshot.scope,
                metric=snapshot.metric,
                unit=snapshot.unit or snapshot.metric,
                current=snapshot.current,
                maximum=snapshot.maximum,
                available=snapshot.available,
                requested_delta=requested,
                projected=projected,
                status=CheckStatus.WOULD_EXCEED,
                shortfall=projected - snapshot.maximum,
                reason=f"Projected usage exceeds {snapshot.constraint_type.lower().replace('_', ' ')} by {projected - snapshot.maximum:g} {snapshot.metric}.",
                last_successful_evaluation=snapshot.timestamp.isoformat(),
            )

        return CapacityCheck(
            constraint_type=snapshot.constraint_type,
            service=snapshot.service,
            limit_name=snapshot.limit_name,
            scope=snapshot.scope,
            metric=snapshot.metric,
            unit=snapshot.unit or snapshot.metric,
            current=snapshot.current,
            maximum=snapshot.maximum,
            available=snapshot.available,
            requested_delta=requested,
            projected=projected,
            status=CheckStatus.OK,
            last_successful_evaluation=snapshot.timestamp.isoformat(),
        )

    def _primary_constraint(self, blockers: list[CapacityCheck]) -> str | None:
        if not blockers:
            return None
        return min(blockers, key=lambda check: check.available if check.available is not None else float("inf")).constraint_type
