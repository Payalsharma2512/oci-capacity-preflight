from __future__ import annotations

import re
from typing import Any

from src.capacity.models import ComputeShape


class ComputeShapeProvider:
    def __init__(self, compute_client):
        self.client = compute_client

    def list_shapes(self, compartment_id: str, availability_domain: str | None = None) -> list[ComputeShape]:
        kwargs = {}
        if availability_domain:
            kwargs["availability_domain"] = availability_domain
        response = self.client.list_shapes(compartment_id=compartment_id, **kwargs)
        return [self._from_oci_shape(item) for item in self._items(response)]

    def get_shape(self, compartment_id: str, shape_name: str, availability_domain: str | None = None) -> ComputeShape:
        matches = [shape for shape in self.list_shapes(compartment_id, availability_domain) if shape.name == shape_name]
        if not matches:
            scope = f" in availability domain {availability_domain}" if availability_domain else ""
            raise ValueError(f"Compute shape {shape_name} is not available{scope}.")
        return matches[0]

    def _from_oci_shape(self, item: Any) -> ComputeShape:
        name = getattr(item, "shape", None) or getattr(item, "name", None)
        ocpus = self._number(getattr(item, "ocpus", None))
        memory = self._number(getattr(item, "memory_in_gbs", None))
        gpus = self._number(getattr(item, "gpus", None))
        raw = self._raw(item)
        options = raw.get("shape_config_options") or raw.get("ocpu_options") or raw.get("memory_options") or {}
        is_flex = bool(name and name.lower().endswith(".flex")) or bool(options)
        return ComputeShape(
            name=name,
            ocpus=ocpus,
            memory_gb=memory,
            is_flex=is_flex,
            gpus=gpus,
            processor_description=getattr(item, "processor_description", None),
            raw=raw,
        )

    def _items(self, response: Any) -> list[Any]:
        data = getattr(response, "data", response)
        return data if isinstance(data, list) else [data]

    def _number(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _raw(self, item: Any) -> dict[str, Any]:
        if hasattr(item, "to_dict"):
            try:
                return item.to_dict()
            except Exception:
                pass
        return dict(getattr(item, "__dict__", {}))


class ShapeLimitResolver:
    """Conservative mapping from a discovered Compute shape to discovered limits.

    A limit is considered verified only when both the shape family and resource
    metric are visible in OCI limit definition names/descriptions. This avoids a
    silent fallback to E4 or any other family.
    """

    CORE_WORDS = ("core", "ocpu", "cpu")
    MEMORY_WORDS = ("memory", "mem")

    def __init__(self, limits_client, tenancy_compartment_id: str):
        self.client = limits_client
        self.tenancy_compartment_id = tenancy_compartment_id

    def resolve(self, shape: ComputeShape | str, requested_metrics: set[str]) -> dict[str, str]:
        shape_name = shape.name if isinstance(shape, ComputeShape) else shape
        definitions = self._list_compute_limit_definitions()
        definition_names = {getattr(item, "name", "") for item in definitions}
        quota_names = self._quota_names(shape) if isinstance(shape, ComputeShape) else []
        mapping: dict[str, str] = {}
        if "ocpus" in requested_metrics:
            mapping["ocpus"] = self._from_quota_names(quota_names, definition_names, self.CORE_WORDS) or self._find_limit(shape_name, definitions, self.CORE_WORDS)
        if "memory_gb" in requested_metrics:
            memory_limit = self._from_quota_names(quota_names, definition_names, self.MEMORY_WORDS) or self._find_limit(shape_name, definitions, self.MEMORY_WORDS, required=False)
            if memory_limit:
                mapping["memory_gb"] = memory_limit
        return mapping

    def _from_quota_names(self, quota_names: list[str], definition_names: set[str], metric_words: tuple[str, ...]) -> str | None:
        candidates = [
            name for name in quota_names
            if name in definition_names
            and any(word in name.lower() for word in metric_words)
            and not self._is_excluded_limit(name)
        ]
        unique = sorted(set(candidates))
        return unique[0] if len(unique) == 1 else None

    def _find_limit(self, shape_name: str, definitions: list[Any], metric_words: tuple[str, ...], required: bool = True) -> str | None:
        shape_tokens = self._shape_tokens(shape_name)
        candidates = []
        for definition in definitions:
            name = getattr(definition, "name", "") or ""
            description = getattr(definition, "description", "") or ""
            if self._is_excluded_limit(name):
                continue
            haystack = f"{name} {description}".lower()
            if not all(token in haystack for token in shape_tokens):
                continue
            if not any(word in haystack for word in metric_words):
                continue
            candidates.append(name)
        unique = sorted(set(candidates))
        if len(unique) == 1:
            return unique[0]
        if required:
            detail = "no verified match" if not unique else f"ambiguous matches: {', '.join(unique)}"
            raise ValueError(f"Capacity Preflight could not reliably map Compute shape {shape_name} to the applicable OCI service limit ({detail}).")
        return None

    def _is_excluded_limit(self, limit_name: str) -> bool:
        lower = limit_name.lower()
        return "reserved" in lower or "reservable" in lower or lower.startswith("dvh-")

    def _quota_names(self, shape: ComputeShape) -> list[str]:
        names = shape.raw.get("quota_names") or shape.raw.get("_quota_names") or []
        return list(names or [])

    def _shape_tokens(self, shape_name: str) -> list[str]:
        lower = shape_name.lower()
        family = re.search(r"\b(?:vm|bm)\.([a-z]+)\.([a-z0-9]+)", lower)
        if not family:
            raise ValueError(f"Capacity Preflight could not identify the Compute shape family for {shape_name}.")
        return [family.group(1), family.group(2)]

    def _list_compute_limit_definitions(self) -> list[Any]:
        items = []
        page = None
        while True:
            response = self.client.list_limit_definitions(self.tenancy_compartment_id, service_name="compute", page=page)
            data = getattr(response, "data", response)
            items.extend(data if isinstance(data, list) else [data])
            page = response.headers.get("opc-next-page") if hasattr(response, "headers") else None
            if not page:
                return items
