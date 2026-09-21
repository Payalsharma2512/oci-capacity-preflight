from __future__ import annotations

from typing import Any


class NetworkLoadBalancerLimitResolver:
    service = "network-load-balancer-api"

    def __init__(self, limits_client, tenancy_compartment_id: str):
        self.client = limits_client
        self.tenancy_compartment_id = tenancy_compartment_id

    def resolve(self, requested_metrics: set[str]) -> dict[str, str]:
        definitions = self._list_limit_definitions()
        mapping: dict[str, str] = {}
        if "nlb_count" in requested_metrics:
            mapping["nlb_count"] = self._find_count_limit(definitions)
        return mapping

    def _find_count_limit(self, definitions: list[Any]) -> str:
        candidates = []
        for definition in definitions:
            name = getattr(definition, "name", "") or ""
            description = getattr(definition, "description", "") or ""
            text = f"{name} {description}".lower()
            if "nlb" in text and "flexible" in text and "count" in text:
                candidates.append(name)
        unique = sorted(set(candidates))
        if len(unique) == 1:
            return unique[0]
        detail = "no verified match" if not unique else f"ambiguous matches: {', '.join(unique)}"
        raise ValueError(f"Capacity Preflight could not reliably map Network Load Balancer count to an OCI service limit ({detail}).")

    def _list_limit_definitions(self) -> list[Any]:
        items = []
        page = None
        while True:
            response = self.client.list_limit_definitions(self.tenancy_compartment_id, service_name=self.service, page=page)
            data = getattr(response, "data", response)
            items.extend(data if isinstance(data, list) else [data])
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return items
