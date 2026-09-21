from __future__ import annotations

from typing import Any

from src.adapters.base import ServiceAdapter
from src.capacity.models import Operation
from src.network_load_balancer import NetworkLoadBalancerLimitResolver


class NetworkLoadBalancerAdapter(ServiceAdapter):
    service = "network-load-balancer-api"
    aliases = {"nlb", "network-load-balancer", "network-load-balancer-api"}

    def operation_from_payload(self, payload: dict[str, Any]) -> Operation:
        operation = payload.get("operation", payload)
        requested = operation.get("requested") or operation.get("requested_delta") or {}
        if "nlb_count" not in requested:
            raise ValueError("Network Load Balancer preflight requires requested.nlb_count.")
        count = float(requested["nlb_count"])
        if count < 1:
            raise ValueError("Network Load Balancer preflight requires nlb_count >= 1.")
        return Operation(
            service=self.service,
            resource_type=operation.get("resource_type", "network_load_balancer"),
            region=operation["region"],
            availability_domain=operation.get("availability_domain"),
            compartment_id=operation["compartment_id"],
            compartment_name=operation.get("compartment_name"),
            requested_delta={"nlb_count": count},
            metadata={
                "mode": "manual",
                "coverage": {
                    "full_preflight": ["NLB count"],
                    "monitor_only": ["backend sets", "backends", "throughput", "new connections", "active connections"],
                },
                "capacity_scope_note": "NLB count service-limit and quota capacity was evaluated. This does not validate every downstream NLB deployment constraint.",
            },
        )

    def limit_mapping(self) -> dict[str, dict[str, str]]:
        return {self.service: {}}

    def describe_operations(self) -> list[dict[str, Any]]:
        return [
            {
                "operation": "create_network_load_balancers",
                "display_name": "Create Network Load Balancers",
                "capability": "FULL_PREFLIGHT",
                "limits": ["max-nlb-flexible-count"],
                "unit": "nlb_count",
                "coverage": "NLB count only",
                "monitor_only": ["backend sets", "backends", "throughput", "new connections", "active connections"],
                "form": [
                    {"name": "region", "label": "Region", "type": "text", "default": "us-ashburn-1", "required": True},
                    {"name": "compartment_id", "label": "Compartment OCID", "type": "text", "required": True},
                    {"name": "nlb_count", "label": "Number of NLBs", "type": "number", "default": 5, "min": 1, "required": True},
                ],
            },
            {
                "operation": "backend_sets",
                "display_name": "Backend Sets",
                "capability": "MONITOR_ONLY",
                "limits": ["not yet mapped"],
                "unit": "count",
                "coverage": "Monitoring only",
                "reason": "The limit may be visible, but this prototype does not yet reliably translate backend set changes into capacity consumption.",
                "form": [],
            },
            {
                "operation": "backends",
                "display_name": "Backends",
                "capability": "MONITOR_ONLY",
                "limits": ["not yet mapped"],
                "unit": "count",
                "coverage": "Monitoring only",
                "reason": "The limit may be visible, but this prototype does not yet reliably translate backend changes into capacity consumption.",
                "form": [],
            },
            {
                "operation": "throughput_connections",
                "display_name": "Throughput And Connections",
                "capability": "MONITOR_ONLY",
                "limits": ["not yet mapped"],
                "unit": "varies",
                "coverage": "Monitoring only",
                "reason": "Throughput and connection changes need operation-specific mapping before preflight.",
                "form": [],
            },
            {
                "operation": "unmapped_discovered_limits",
                "display_name": "Other Discovered Limits",
                "capability": "DISCOVERY_ONLY",
                "limits": ["discovered from OCI"],
                "unit": "varies",
                "coverage": "Discovery only",
                "reason": "These limits can be discovered from OCI, but cannot currently be evaluated with enough usage or availability context for preflight.",
                "form": [],
            },
        ]

    def workload_from_payload(
        self,
        payload: dict[str, Any],
        limit_resolver: NetworkLoadBalancerLimitResolver,
    ) -> tuple[Operation, dict[str, dict[str, str]]]:
        operation = payload.get("operation", payload)
        workload = operation.get("workload") or {}
        count = int(workload.get("nlb_count", 0))
        if count < 1:
            raise ValueError("Network Load Balancer workload requires nlb_count >= 1.")
        requested_delta = {"nlb_count": float(count)}
        mapping = limit_resolver.resolve(set(requested_delta))
        if "nlb_count" not in mapping:
            raise ValueError("Capacity Preflight could not reliably map Network Load Balancer count to an OCI service limit.")
        operation_model = Operation(
            service=self.service,
            resource_type="network_load_balancer",
            region=operation["region"],
            availability_domain=operation.get("availability_domain"),
            compartment_id=operation["compartment_id"],
            compartment_name=operation.get("compartment_name"),
            requested_delta=requested_delta,
            metadata={
                "mode": "workload",
                "workload": {
                    "resource": "Network Load Balancer",
                    "nlb_count": count,
                    "preflight_coverage": "NLB count only",
                },
                "coverage": {
                    "full_preflight": ["NLB count"],
                    "monitor_only": ["backend sets", "backends", "throughput", "new connections", "active connections"],
                },
                "capacity_scope_note": "NLB count service-limit and quota capacity was evaluated. This does not validate every downstream NLB deployment constraint.",
            },
        )
        return operation_model, {self.service: mapping}
