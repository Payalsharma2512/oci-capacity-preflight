from __future__ import annotations

from typing import Any


class BlockVolumeLimitResolver:
    service = "block-storage"

    def __init__(self, limits_client, tenancy_compartment_id: str):
        self.client = limits_client
        self.tenancy_compartment_id = tenancy_compartment_id

    def resolve(self, requested_metrics: set[str]) -> dict[str, str]:
        definitions = self._list_limit_definitions()
        mapping: dict[str, str] = {}
        if "volume_count" in requested_metrics:
            mapping["volume_count"] = self._find_limit(
                definitions,
                include=("volume", "count"),
                exclude=("backup", "free", "group", "replica"),
                metric="volume count",
            )
        if "storage_gb" in requested_metrics:
            mapping["storage_gb"] = self._find_limit(
                definitions,
                include=("storage", "gb"),
                exclude=("backup", "free", "replica", "regional"),
                metric="total storage GB",
            )
        if "replica_storage_gb" in requested_metrics:
            mapping["replica_storage_gb"] = self._find_limit(
                definitions,
                include=("replica", "storage", "gb"),
                exclude=("free",),
                metric="replica storage GB",
            )
        return mapping

    def _find_limit(self, definitions: list[Any], include: tuple[str, ...], exclude: tuple[str, ...], metric: str) -> str:
        candidates = []
        for definition in definitions:
            name = getattr(definition, "name", "") or ""
            description = getattr(definition, "description", "") or ""
            text = f"{name} {description}".lower()
            if all(word in text for word in include) and not any(word in text for word in exclude):
                candidates.append(name)
        unique = sorted(set(candidates))
        if len(unique) == 1:
            return unique[0]
        detail = "no verified match" if not unique else f"ambiguous matches: {', '.join(unique)}"
        raise ValueError(f"Capacity Preflight could not reliably map Block Volume {metric} to an OCI service limit ({detail}).")

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
