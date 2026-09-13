"""RBAC checks via SelfSubjectAccessReview. Headlamp AuthVisible / KubeObject.getAuthorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from kubernetes.client import V1ResourceAttributes, V1SelfSubjectAccessReview, V1SelfSubjectAccessReviewSpec

from roomlamp.k8s.gateway import GATEWAY_SPECS
from roomlamp.k8s.network import NETWORK_SPECS
from roomlamp.k8s.storage import STORAGE_SPECS
from roomlamp.k8s.workloads import KIND_SPECS, POD_KIND

# https://kubernetes.io/docs/reference/access-authn-authz/authorization/#determine-the-request-verb
VALID_AUTH_VERBS = frozenset(
    {
        'create',
        'get',
        'list',
        'watch',
        'update',
        'patch',
        'delete',
        'deletecollection',
    }
)

SUBRESOURCE_LOG = 'log'
SUBRESOURCE_EXEC = 'exec'
SUBRESOURCE_EVICTION = 'eviction'


@dataclass(frozen=True)
class ApiResourceRef:
    group: str
    version: str
    resource: str


@dataclass(frozen=True)
class ResourceActions:
    """Which operator actions the current user may perform on one object."""

    update: bool
    delete: bool
    evict: bool
    logs: bool
    exec: bool

    @classmethod
    def none(cls) -> ResourceActions:
        return cls(update=False, delete=False, evict=False, logs=False, exec=False)

    @classmethod
    def allow_all(cls, kind: str) -> ResourceActions:
        is_pod = kind == POD_KIND
        return cls(update=True, delete=True, evict=is_pod, logs=is_pod, exec=is_pod)

    @property
    def can_remove(self) -> bool:
        return self.delete or self.evict


class AccessReviewApi(Protocol):
    def create_self_subject_access_review(self, body: V1SelfSubjectAccessReview, **kwargs: Any) -> object: ...


class AccessChecker(Protocol):
    def check_access(
        self,
        verb: str,
        kind: str,
        *,
        namespace: str | None = None,
        name: str | None = None,
        subresource: str | None = None,
    ) -> bool: ...


def api_resource_for_kind(kind: str) -> ApiResourceRef:
    """Group / version / plural resource name for a SelfSubjectAccessReview."""
    if kind == POD_KIND:
        return ApiResourceRef('', 'v1', 'pods')
    spec = KIND_SPECS.get(kind)
    if spec is not None:
        return ApiResourceRef(spec.group, 'v1', f'{kind.lower()}s')
    storage = STORAGE_SPECS.get(kind)
    if storage is not None:
        return ApiResourceRef(storage.group, storage.version, storage.resource)
    network = NETWORK_SPECS.get(kind)
    if network is not None:
        return ApiResourceRef(network.group, network.version, network.resource)
    gateway = GATEWAY_SPECS.get(kind)
    if gateway is not None:
        return ApiResourceRef(gateway.group, gateway.version, gateway.resource)
    raise ValueError(f'unsupported kind: {kind}')


def has_access_checker(cluster: object) -> bool:
    return callable(getattr(cluster, 'check_access', None))


def initial_actions(cluster: object, kind: str) -> ResourceActions:
    """Hide gated keys until SSAR returns when the cluster can check RBAC."""
    if has_access_checker(cluster):
        return ResourceActions.none()
    return ResourceActions.allow_all(kind)


def review_access(
    api: AccessReviewApi,
    verb: str,
    kind: str,
    *,
    namespace: str | None = None,
    name: str | None = None,
    subresource: str | None = None,
) -> bool:
    """Return whether SelfSubjectAccessReview.status.allowed is true.

    Invalid verbs, unknown kinds, and API errors fail closed (not allowed),
    matching Headlamp AuthVisible's default of hidden until allowed.
    """
    if verb not in VALID_AUTH_VERBS:
        return False
    try:
        ref = api_resource_for_kind(kind)
    except ValueError:
        return False
    body = V1SelfSubjectAccessReview(
        api_version='authorization.k8s.io/v1',
        kind='SelfSubjectAccessReview',
        spec=V1SelfSubjectAccessReviewSpec(
            resource_attributes=V1ResourceAttributes(
                verb=verb,
                group=ref.group,
                version=ref.version,
                resource=ref.resource,
                namespace=namespace or None,
                name=name or None,
                subresource=subresource or None,
            )
        ),
    )
    try:
        result = api.create_self_subject_access_review(body)
    except Exception:
        return False
    status = getattr(result, 'status', None)
    return bool(getattr(status, 'allowed', False))


def resource_actions(checker: AccessChecker, kind: str, namespace: str, name: str) -> ResourceActions:
    """Check Headlamp AuthVisible verbs for YAML, delete, logs, and exec."""
    is_pod = kind == POD_KIND
    return ResourceActions(
        update=checker.check_access('update', kind, namespace=namespace, name=name),
        delete=checker.check_access('delete', kind, namespace=namespace, name=name),
        evict=(
            is_pod
            and checker.check_access(
                'create',
                kind,
                namespace=namespace,
                name=name,
                subresource=SUBRESOURCE_EVICTION,
            )
        ),
        logs=(
            is_pod
            and checker.check_access(
                'get',
                kind,
                namespace=namespace,
                name=name,
                subresource=SUBRESOURCE_LOG,
            )
        ),
        exec=(
            is_pod
            and checker.check_access(
                'create',
                kind,
                namespace=namespace,
                name=name,
                subresource=SUBRESOURCE_EXEC,
            )
        ),
    )


def actions_for(cluster: object, kind: str, namespace: str, name: str) -> ResourceActions:
    if not has_access_checker(cluster):
        return ResourceActions.allow_all(kind)
    return resource_actions(cluster, kind, namespace, name)
