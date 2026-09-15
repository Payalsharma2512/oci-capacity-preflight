from __future__ import annotations

import re

from src.capacity.models import CapacitySnapshot, Operation
from src.capacity.providers import CapacityProvider


class OciQuotaProvider(CapacityProvider):
    """Quota provider based on oci.limits.QuotasClient.list_quotas(compartment_id).

    OCI quota statements are policy text. This MVP includes a conservative parser for
    simple quota statements and returns UNKNOWN for statements it cannot safely parse.
    """

    SET_RE = re.compile(r"set\s+(?P<service>\S+)\s+quota\s+(?P<limit>\S+)\s+to\s+(?P<value>\d+(?:\.\d+)?)", re.IGNORECASE)

    def __init__(self, quotas_client, root_compartment_id: str, usage_provider):
        self.client = quotas_client
        self.root_compartment_id = root_compartment_id
        self.usage_provider = usage_provider

    def discover_constraints(self, operation: Operation) -> list[str]:
        return [q.name for q in self._list_quotas()]

    def get_current_state(self, operation: Operation) -> list[CapacitySnapshot]:
        snapshots: list[CapacitySnapshot] = []
        try:
            quotas = self._list_quotas()
        except Exception as exc:
            metric = next(iter(operation.requested_delta), "unknown")
            return [CapacitySnapshot("COMPARTMENT_QUOTA", operation.service, "quota-policy", operation.compartment_id, metric, None, None, None, reason=f"Compartment quota could not be evaluated because the required API permission is missing or failed: {exc}")]

        for quota in quotas:
            for statement in getattr(quota, "statements", []) or []:
                parsed = self._parse(statement)
                if not parsed or parsed["service"] != operation.service:
                    continue
                metric = "ocpus" if "core" in parsed["limit"] or "ocpu" in parsed["limit"] else parsed["limit"]
                try:
                    current = self.usage_provider.current_usage(operation, metric)
                    maximum = parsed["value"]
                    snapshots.append(CapacitySnapshot("COMPARTMENT_QUOTA", operation.service, parsed["limit"], operation.compartment_name or operation.compartment_id, metric, current, maximum, maximum - current))
                except Exception as exc:
                    snapshots.append(CapacitySnapshot("COMPARTMENT_QUOTA", operation.service, parsed["limit"], operation.compartment_name or operation.compartment_id, metric, None, parsed["value"], None, reason=f"Quota usage could not be evaluated: {exc}"))
        return snapshots

    def remediation(self, snapshot: CapacitySnapshot) -> dict[str, str]:
        return {"action": "INCREASE_COMPARTMENT_QUOTA", "reason": "Increase compartment quota, deploy elsewhere, or reduce requested capacity."}

    def _list_quotas(self):
        items = []
        page = None
        while True:
            response = self.client.list_quotas(self.root_compartment_id, page=page, lifecycle_state="ACTIVE")
            items.extend(response.data if isinstance(response.data, list) else [response.data])
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return items

    def _parse(self, statement: str) -> dict | None:
        match = self.SET_RE.search(statement)
        if not match:
            return None
        return {"service": match.group("service"), "limit": match.group("limit"), "value": float(match.group("value"))}
