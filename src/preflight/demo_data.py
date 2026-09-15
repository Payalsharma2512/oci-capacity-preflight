from __future__ import annotations

from src.capacity.models import CapacitySnapshot, Operation
from src.capacity.providers import CapacityProvider


class StaticCapacityProvider(CapacityProvider):
    def __init__(self, snapshots: list[CapacitySnapshot]):
        self.snapshots = snapshots

    def discover_constraints(self, operation: Operation) -> list[str]:
        return [s.limit_name for s in self.snapshots if s.service == operation.service]

    def get_current_state(self, operation: Operation) -> list[CapacitySnapshot]:
        return [s for s in self.snapshots if s.service == operation.service]

    def remediation(self, snapshot: CapacitySnapshot) -> dict[str, str]:
        action = snapshot.remediation_action or "CHANGE_PLACEMENT_OR_REDUCE_REQUEST"
        if snapshot.constraint_type == "COMPARTMENT_QUOTA":
            reason = "Increase compartment quota, deploy into another eligible compartment, or reduce requested capacity."
        elif snapshot.constraint_type == "SERVICE_LIMIT":
            reason = "Request a service limit increase to cover projected usage."
        else:
            reason = snapshot.reason or f"Resolve {snapshot.constraint_type} before provisioning."
        return {"action": action, "reason": reason}


def scenario_quota_blocks() -> tuple[Operation, StaticCapacityProvider]:
    operation = Operation("compute", "instance", "us-phoenix-1", "<COMPARTMENT_OCID>", {"ocpus": 14}, "AD-1", "Production")
    snapshots = [
        CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 80, 8, remediation_action="REQUEST_LIMIT_INCREASE"),
        CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 18, 20, 2, remediation_action="INCREASE_COMPARTMENT_QUOTA"),
    ]
    return operation, StaticCapacityProvider(snapshots)


def scenario_service_limit_blocks() -> tuple[Operation, StaticCapacityProvider]:
    operation = Operation("compute", "instance", "us-phoenix-1", "<COMPARTMENT_OCID>", {"ocpus": 14}, None, "Production")
    snapshots = [
        CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 80, 8, remediation_action="REQUEST_LIMIT_INCREASE"),
        CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 4, 24, 20, remediation_action="INCREASE_COMPARTMENT_QUOTA"),
    ]
    return operation, StaticCapacityProvider(snapshots)


def scenario_passes() -> tuple[Operation, StaticCapacityProvider]:
    operation = Operation("compute", "instance", "us-phoenix-1", "<COMPARTMENT_OCID>", {"ocpus": 8}, None, "Production")
    snapshots = [
        CapacitySnapshot("SERVICE_LIMIT", "compute", "standard-e4-core-count", "us-phoenix-1", "ocpus", 72, 100, 28, remediation_action="REQUEST_LIMIT_INCREASE"),
        CapacitySnapshot("COMPARTMENT_QUOTA", "compute", "standard-e4-core-count", "Production", "ocpus", 8, 28, 20, remediation_action="INCREASE_COMPARTMENT_QUOTA"),
    ]
    return operation, StaticCapacityProvider(snapshots)
