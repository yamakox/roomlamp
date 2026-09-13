"""Serialize Kubernetes objects to YAML for a read-only view."""

from __future__ import annotations

from typing import Any

import yaml
from kubernetes.client import ApiClient

# js-yaml dump() default (Headlamp EditorDialog / DryRunPreviewDialog).
# Folded ``>`` wraps long lines (lineWidth 80). Literal ``|`` keeps short
# multiline values (ConfigMap data) without inserting blank lines; folded
# style would, because a single newline there loads as a space.
FOLD_WIDTH = 80


class ResourceDumper(yaml.SafeDumper):
    """Dump strings the way Headlamp's js-yaml dump does."""


def _string_style(data: str) -> str | None:
    """Pick ``|`` or ``>`` the way js-yaml ``chooseScalarStyle`` does."""
    has_line_break = '\n' in data
    foldable = any(len(line) > FOLD_WIDTH and not line.startswith(' ') for line in data.split('\n'))
    if has_line_break and not foldable:
        return '|'
    if has_line_break or foldable:
        return '>'
    return None


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    style = _string_style(data)
    if style is None:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data)
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style=style)


ResourceDumper.add_representer(str, _represent_str)


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
    return yaml.dump(
        data,
        Dumper=ResourceDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


def _omit_nones(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _omit_nones(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_omit_nones(item) for item in value if item is not None]
    return value
