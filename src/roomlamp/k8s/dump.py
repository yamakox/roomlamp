"""Serialize Kubernetes objects to YAML for a read-only view."""

from __future__ import annotations

from typing import Any

import yaml
from kubernetes.client import ApiClient


def dump_resource(
    obj: object,
    *,
    kind: str,
    api_version: str,
    hide_managed_fields: bool = True,
) -> str:
    """Return kubectl-style YAML. Headlamp's view hides managedFields by default."""
    data = ApiClient().sanitize_for_serialization(obj)
    if not isinstance(data, dict):
        raise TypeError('resource did not serialize to a mapping')
    data = _omit_nones(data)
    data.setdefault('apiVersion', api_version)
    data.setdefault('kind', kind)
    if hide_managed_fields:
        metadata = data.get('metadata')
        if isinstance(metadata, dict):
            metadata.pop('managedFields', None)
    return yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _omit_nones(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _omit_nones(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_omit_nones(item) for item in value if item is not None]
    return value
