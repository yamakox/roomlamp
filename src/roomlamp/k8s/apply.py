"""Apply YAML or JSON to the cluster. Matches Headlamp ``lib/k8s/api/v1/apply.ts``."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import yaml
from kubernetes.client.exceptions import ApiException

# Headlamp retries PUT when POST cannot create because the object already exists
# (409) or create is forbidden but update is allowed (403).
_RETRY_PUT_STATUSES = frozenset({403, 409})


@dataclass(frozen=True)
class AppliedObject:
    kind: str
    name: str
    namespace: str | None
    dry_run: bool

    @property
    def label(self) -> str:
        if self.namespace:
            return f'{self.kind} {self.namespace}/{self.name}'
        return f'{self.kind} {self.name}'


class ResourceApi(Protocol):
    namespaced: bool

    def create(
        self,
        body: dict[str, Any] | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> object: ...

    def replace(
        self,
        body: dict[str, Any] | None = None,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> object: ...


ResourceGetter = Callable[[str, str], ResourceApi]


def looks_like_json(code: str) -> bool:
    stripped = code.lstrip()
    return bool(stripped) and stripped[0] in '{['


def parse_objects(code: str) -> list[dict[str, Any]]:
    """Parse YAML documents or JSON into resource mappings. Headlamp uses ``yaml.loadAll``."""
    text = code.strip()
    if not text:
        raise ValueError('YAML is empty')
    if looks_like_json(text):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Invalid JSON: {exc.msg}') from exc
        items = parsed if isinstance(parsed, list) else [parsed]
    else:
        try:
            items = list(yaml.safe_load_all(text))
        except yaml.YAMLError as exc:
            raise ValueError(f'Invalid YAML: {exc}') from exc
    objects: list[dict[str, Any]] = []
    for item in items:
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError('each document must be a mapping')
        objects.append(item)
    if not objects:
        raise ValueError('YAML is empty')
    return objects


def apply_yaml(
    text: str,
    get_resource: ResourceGetter,
    *,
    dry_run: bool = False,
    default_namespace: str = 'default',
) -> list[AppliedObject]:
    """Apply every document. Stops at the first failure."""
    applied: list[AppliedObject] = []
    for obj in parse_objects(text):
        api_version = obj.get('apiVersion')
        kind = obj.get('kind')
        if not isinstance(api_version, str) or not api_version or not isinstance(kind, str) or not kind:
            raise ValueError('apiVersion and kind are required')
        resource = get_resource(api_version, kind)
        applied.append(apply_object(obj, resource, dry_run=dry_run, default_namespace=default_namespace))
    return applied


def apply_object(
    body: dict[str, Any],
    resource: ResourceApi,
    *,
    dry_run: bool = False,
    default_namespace: str = 'default',
) -> AppliedObject:
    """POST, then PUT on 409/403. Drops ``resourceVersion`` for create and restores it for replace."""
    payload = copy.deepcopy(body)
    kind = payload.get('kind')
    api_version = payload.get('apiVersion')
    if not isinstance(kind, str) or not kind or not isinstance(api_version, str) or not api_version:
        raise ValueError('apiVersion and kind are required')
    metadata = payload.setdefault('metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('metadata must be a mapping')
    name = metadata.get('name')
    namespace: str | None = None
    if resource.namespaced:
        raw_namespace = metadata.get('namespace')
        namespace = raw_namespace if isinstance(raw_namespace, str) and raw_namespace else default_namespace
        metadata['namespace'] = namespace
    resource_version = metadata.pop('resourceVersion', None)
    extra: dict[str, Any] = {'dry_run': 'All'} if dry_run else {}
    try:
        _create(resource, payload, namespace, extra)
    except ApiException as exc:
        if exc.status not in _RETRY_PUT_STATUSES:
            raise
        if resource_version is not None:
            metadata['resourceVersion'] = resource_version
        if not isinstance(name, str) or not name:
            raise ValueError(f'name is required to update {kind}') from exc
        _replace(resource, payload, name, namespace, extra)
    applied_name = name if isinstance(name, str) and name else str(metadata.get('name') or '')
    return AppliedObject(kind=kind, name=applied_name, namespace=namespace, dry_run=dry_run)


def apply_error_message(exc: BaseException) -> str:
    """User-facing apply error without kubeconfig or other secrets."""
    summary = getattr(exc, 'summary', None)
    if callable(summary):
        try:
            text = summary()
        except Exception:
            text = None
        if text:
            return str(text)
    body = getattr(exc, 'body', None)
    if isinstance(body, bytes):
        body = body.decode('utf-8', errors='replace')
    if isinstance(body, str) and body:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body[:500]
        if isinstance(data, dict) and data.get('message'):
            return str(data['message'])
        return body[:500]
    return str(exc)


def _create(
    resource: ResourceApi,
    body: dict[str, Any],
    namespace: str | None,
    extra: dict[str, Any],
) -> object:
    if namespace is not None:
        return resource.create(body=body, namespace=namespace, **extra)
    return resource.create(body=body, **extra)


def _replace(
    resource: ResourceApi,
    body: dict[str, Any],
    name: str,
    namespace: str | None,
    extra: dict[str, Any],
) -> object:
    if namespace is not None:
        return resource.replace(body=body, name=name, namespace=namespace, **extra)
    return resource.replace(body=body, name=name, **extra)
