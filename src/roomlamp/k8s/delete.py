"""Delete cluster objects. Matches Headlamp ``KubeObject.delete`` and Pod ``evict``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from kubernetes.client import V1Eviction, V1ObjectMeta

from roomlamp.k8s.resources import POD_API_VERSION
from roomlamp.k8s.storage import STORAGE_SPECS
from roomlamp.k8s.workloads import JOB, KIND_SPECS, POD_KIND

ACTION_DELETE = 'delete'
ACTION_EVICT = 'evict'


@dataclass(frozen=True)
class DeletedObject:
    kind: str
    name: str
    namespace: str | None
    force: bool
    action: str

    @property
    def label(self) -> str:
        if self.namespace:
            return f'{self.kind} {self.namespace}/{self.name}'
        return f'{self.kind} {self.name}'


class DeletableResource(Protocol):
    namespaced: bool

    def delete(
        self,
        name: str | None = None,
        namespace: str | None = None,
        **kwargs: Any,
    ) -> object: ...


class EvictionApi(Protocol):
    def create_namespaced_pod_eviction(
        self,
        name: str,
        namespace: str,
        body: object,
        **kwargs: Any,
    ) -> object: ...


def api_version_for_kind(kind: str) -> str:
    """API version used with DynamicClient for kinds Roomlamp can delete."""
    if kind == POD_KIND:
        return POD_API_VERSION
    spec = KIND_SPECS.get(kind)
    if spec is not None:
        return f'{spec.group}/v1'
    storage = STORAGE_SPECS.get(kind)
    if storage is not None:
        return storage.api_version
    raise ValueError(f'unsupported kind: {kind}')


def delete_params(kind: str, force: bool) -> dict[str, Any]:
    """Headlamp: Jobs use Background deletion; force sets gracePeriodSeconds=0."""
    extra: dict[str, Any] = {}
    if kind == JOB:
        extra['propagation_policy'] = 'Background'
    if force:
        extra['grace_period_seconds'] = 0
    return extra


def delete_object(
    resource: DeletableResource,
    name: str,
    *,
    kind: str,
    namespace: str | None = None,
    force: bool = False,
) -> DeletedObject:
    """DELETE one object. Namespaced kinds require ``namespace``."""
    if not name:
        raise ValueError('name is required')
    extra = delete_params(kind, force)
    if resource.namespaced:
        if not namespace:
            raise ValueError(f'namespace is required to delete {kind}')
        resource.delete(name=name, namespace=namespace, **extra)
        deleted_namespace = namespace
    else:
        resource.delete(name=name, **extra)
        deleted_namespace = None
    return DeletedObject(
        kind=kind,
        name=name,
        namespace=deleted_namespace,
        force=force,
        action=ACTION_DELETE,
    )


def evict_pod(core: EvictionApi, namespace: str, name: str) -> DeletedObject:
    """POST ``pods/eviction``. Headlamp sends only name and namespace in metadata."""
    if not name:
        raise ValueError('name is required')
    if not namespace:
        raise ValueError('namespace is required to evict a Pod')
    body = V1Eviction(metadata=V1ObjectMeta(name=name, namespace=namespace))
    core.create_namespaced_pod_eviction(name, namespace, body)
    return DeletedObject(
        kind=POD_KIND,
        name=name,
        namespace=namespace,
        force=False,
        action=ACTION_EVICT,
    )
