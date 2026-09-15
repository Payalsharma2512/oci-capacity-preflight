from __future__ import annotations

from abc import ABC, abstractmethod

from .models import CapacitySnapshot, Operation


class CapacityProvider(ABC):
    @abstractmethod
    def discover_constraints(self, operation: Operation) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_current_state(self, operation: Operation) -> list[CapacitySnapshot]:
        raise NotImplementedError

    def evaluate(self, operation: Operation) -> list[CapacitySnapshot]:
        return self.get_current_state(operation)

    @abstractmethod
    def remediation(self, snapshot: CapacitySnapshot) -> dict[str, str]:
        raise NotImplementedError


class ServiceSpecificConstraintProvider(CapacityProvider):
    """Extension point for service-specific capacity signals not exposed by Limits."""


class RateLimitProvider(CapacityProvider):
    """Extension point for API rate and throttling constraints."""


class SubscriptionConstraintProvider(CapacityProvider):
    """Extension point for subscription, shape, or capacity-reservation constraints."""
