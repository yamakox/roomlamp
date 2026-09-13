"""List and get Security objects: ServiceAccount, Role, RoleBinding.

Role and RoleBinding lists also include cluster-scoped ClusterRole and
ClusterRoleBinding rows, matching Headlamp's Security screens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api, RbacAuthorizationV1Api

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time
from roomlamp.k8s.workloads import format_age

SERVICE_ACCOUNT = 'ServiceAccount'
ROLE = 'Role'
CLUSTER_ROLE = 'ClusterRole'
ROLE_BINDING = 'RoleBinding'
CLUSTER_ROLE_BINDING = 'ClusterRoleBinding'

SECURITY_KINDS = (SERVICE_ACCOUNT, ROLE, ROLE_BINDING)
_LIST_COMPANIONS = {
    ROLE: CLUSTER_ROLE,
    ROLE_BINDING: CLUSTER_ROLE_BINDING,
}

RBAC_GROUP = 'rbac.authorization.k8s.io'


@dataclass(frozen=True)
class KindSpec:
    kind: str
    label: str
    group: str
    version: str
    resource: str
    namespaced: bool
    list_namespaced: str
    list_all: str
    read: str
    columns: tuple[str, ...]

    @property
    def api_version(self) -> str:
        if self.group:
            return f'{self.group}/{self.version}'
        return self.version


SECURITY_SPECS: dict[str, KindSpec] = {
    SERVICE_ACCOUNT: KindSpec(
        SERVICE_ACCOUNT,
        'Service Accounts',
        '',
        'v1',
        'serviceaccounts',
        True,
        'list_namespaced_service_account',
        'list_service_account_for_all_namespaces',
        'read_namespaced_service_account',
        ('Namespace', 'Name', 'Secrets', 'Age'),
    ),
    ROLE: KindSpec(
        ROLE,
        'Roles',
        RBAC_GROUP,
        'v1',
        'roles',
        True,
        'list_namespaced_role',
        'list_role_for_all_namespaces',
        'read_namespaced_role',
        ('Kind', 'Name', 'Namespace', 'Age'),
    ),
    CLUSTER_ROLE: KindSpec(
        CLUSTER_ROLE,
        'Cluster Roles',
        RBAC_GROUP,
        'v1',
        'clusterroles',
        False,
        '',
        'list_cluster_role',
        'read_cluster_role',
        ('Kind', 'Name', 'Namespace', 'Age'),
    ),
    ROLE_BINDING: KindSpec(
        ROLE_BINDING,
        'Role Bindings',
        RBAC_GROUP,
        'v1',
        'rolebindings',
        True,
        'list_namespaced_role_binding',
        'list_role_binding_for_all_namespaces',
        'read_namespaced_role_binding',
        ('Kind', 'Name', 'Namespace', 'Role', 'Users', 'Groups', 'Service Accounts', 'Age'),
    ),
    CLUSTER_ROLE_BINDING: KindSpec(
        CLUSTER_ROLE_BINDING,
        'Cluster Role Bindings',
        RBAC_GROUP,
        'v1',
        'clusterrolebindings',
        False,
        '',
        'list_cluster_role_binding',
        'read_cluster_role_binding',
        ('Kind', 'Name', 'Namespace', 'Role', 'Users', 'Groups', 'Service Accounts', 'Age'),
    ),
}

SECURITY_LABELS = {spec.kind: spec.label for spec in SECURITY_SPECS.values()}


@dataclass(frozen=True)
class SecuritySummary:
    kind: str
    name: str
    namespace: str
    created: datetime | None
    cells: tuple[str, ...]
    sort_keys: tuple[object, ...]

    @property
    def key(self) -> str:
        if self.namespace:
            return f'{self.namespace}/{self.name}'
        return self.name


@dataclass(frozen=True)
class SecurityDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]


class SecurityReader(Protocol):
    def list_security(self, kind: str, namespace: str) -> list[SecuritySummary]: ...

    def get_security(self, kind: str, namespace: str, name: str) -> SecurityDetail: ...

    def get_security_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str: ...


class ApiSecurityReader:
    """Security reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._core = CoreV1Api(api_client)
        self._rbac = RbacAuthorizationV1Api(api_client)

    def list_security(self, kind: str, namespace: str) -> list[SecuritySummary]:
        items: list[SecuritySummary] = []
        for listed in list_kinds_for(kind):
            watch_ns = namespace if is_namespaced(listed) else ALL_NAMESPACES
            items.extend(summarize_security(listed, item) for item in self._list_security_raw(listed, watch_ns))
        return items

    def get_security(self, kind: str, namespace: str, name: str) -> SecurityDetail:
        return detail_security(kind, self._read_security(kind, namespace, name))

    def get_security_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        spec = _require_kind(kind)
        raw = self._read_security(kind, namespace, name)
        return dump_resource(
            raw,
            kind=kind,
            api_version=spec.api_version,
            hide_managed_fields=hide_managed_fields,
        )

    def security_list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._security_api(spec)
        if not spec.namespaced or namespace == ALL_NAMESPACES:
            return getattr(api, spec.list_all), ()
        return getattr(api, spec.list_namespaced), (namespace,)

    def _list_security_raw(self, kind: str, namespace: str) -> list[object]:
        list_fn, args = self.security_list_call(kind, namespace)
        listed = list_fn(*args)
        return list(listed.items or [])

    def _read_security(self, kind: str, namespace: str, name: str) -> object:
        spec = _require_kind(kind)
        api = self._security_api(spec)
        if spec.namespaced:
            return getattr(api, spec.read)(name, namespace)
        return getattr(api, spec.read)(name)

    def _security_api(self, spec: KindSpec) -> CoreV1Api | RbacAuthorizationV1Api:
        if spec.group == RBAC_GROUP:
            return self._rbac
        return self._core


def is_security_kind(kind: str) -> bool:
    return kind in SECURITY_SPECS


def list_kinds_for(kind: str) -> tuple[str, ...]:
    """Kinds shown on one Security list. Role includes ClusterRole; RoleBinding includes ClusterRoleBinding."""
    _require_kind(kind)
    companion = _LIST_COMPANIONS.get(kind)
    if companion is None:
        return (kind,)
    return (kind, companion)


def is_namespaced(kind: str) -> bool:
    return _require_kind(kind).namespaced


def split_security_key(kind: str, key: str) -> tuple[str, str]:
    if is_namespaced(kind):
        namespace, name = key.split('/', 1)
        return namespace, name
    return '', key


def summarize_security(kind: str, obj: object, now: datetime | None = None) -> SecuritySummary:
    spec = _require_kind(kind)
    return _SUMMARIZERS[kind](obj, spec, now)


def detail_security(kind: str, obj: object, now: datetime | None = None) -> SecurityDetail:
    _require_kind(kind)
    summary = summarize_security(kind, obj, now)
    meta = getattr(obj, 'metadata', None)
    labels = ()
    if meta and getattr(meta, 'labels', None):
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and getattr(meta, 'creation_timestamp', None):
        created = _format_time(meta.creation_timestamp)
    return SecurityDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=getattr(meta, 'uid', None) if meta else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, obj),
    )


def _require_kind(kind: str) -> KindSpec:
    spec = SECURITY_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown security kind: {kind}')
    return spec


def _meta_name(obj: object) -> tuple[str, str, datetime | None]:
    meta = getattr(obj, 'metadata', None)
    name = getattr(meta, 'name', None) if meta else None
    namespace = getattr(meta, 'namespace', None) if meta else None
    created = getattr(meta, 'creation_timestamp', None) if meta else None
    return name or '', namespace or '', created


def _age_parts(created: datetime | None, now: datetime | None) -> tuple[str, float]:
    return format_age(created, now), created.timestamp() if created is not None else 0.0


def _make_summary(
    kind: str,
    name: str,
    namespace: str,
    created: datetime | None,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> SecuritySummary:
    return SecuritySummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=created,
        cells=cells,
        sort_keys=sort_keys,
    )


def _join(values: object | None) -> str:
    if not values:
        return ''
    return ', '.join(str(item) for item in values if item is not None and str(item) != '')


def _ref_names(items: object | None) -> list[str]:
    names: list[str] = []
    for item in items or []:
        name = str(getattr(item, 'name', None) or '')
        if name:
            names.append(name)
    return names


def _subject_names(subjects: object | None, kind: str) -> str:
    names: list[str] = []
    for subject in subjects or []:
        if str(getattr(subject, 'kind', None) or '') != kind:
            continue
        name = str(getattr(subject, 'name', None) or '')
        if name:
            names.append(name)
    return ', '.join(names)


def _summarize_service_account(obj: object, spec: KindSpec, now: datetime | None) -> SecuritySummary:
    name, namespace, created = _meta_name(obj)
    secrets = len(getattr(obj, 'secrets', None) or [])
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, str(secrets), age),
        (namespace, name, secrets, age_key),
    )


def _summarize_role(obj: object, spec: KindSpec, now: datetime | None) -> SecuritySummary:
    name, namespace, created = _meta_name(obj)
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (spec.kind, name, namespace, age),
        (spec.kind, name, namespace, age_key),
    )


def _summarize_role_binding(obj: object, spec: KindSpec, now: datetime | None) -> SecuritySummary:
    name, namespace, created = _meta_name(obj)
    role_ref = getattr(obj, 'role_ref', None)
    role_name = str(getattr(role_ref, 'name', None) or '') if role_ref else ''
    subjects = getattr(obj, 'subjects', None)
    users = _subject_names(subjects, 'User')
    groups = _subject_names(subjects, 'Group')
    service_accounts = _subject_names(subjects, 'ServiceAccount')
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (spec.kind, name, namespace, role_name, users, groups, service_accounts, age),
        (spec.kind, name, namespace, role_name, users, groups, service_accounts, age_key),
    )


_SUMMARIZERS = {
    SERVICE_ACCOUNT: _summarize_service_account,
    ROLE: _summarize_role,
    CLUSTER_ROLE: _summarize_role,
    ROLE_BINDING: _summarize_role_binding,
    CLUSTER_ROLE_BINDING: _summarize_role_binding,
}


def _append_if(fields: list[tuple[str, str]], label: str, value: str) -> None:
    if value:
        fields.append((label, value))


def _yes_no(value: bool) -> str:
    return 'Yes' if value else 'No'


def _detail_fields(kind: str, obj: object) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    if kind == SERVICE_ACCOUNT:
        _append_if(fields, 'Secrets', _join(_ref_names(getattr(obj, 'secrets', None))))
        _append_if(fields, 'Image Pull Secrets', _join(_ref_names(getattr(obj, 'image_pull_secrets', None))))
        automount = getattr(obj, 'automount_service_account_token', None)
        if automount is not None:
            fields.append(('Automount Service Account Token', _yes_no(bool(automount))))
    elif kind in {ROLE, CLUSTER_ROLE}:
        rules = list(getattr(obj, 'rules', None) or [])
        if not rules:
            fields.append(('Rules', '(none)'))
        else:
            for index, rule in enumerate(rules, start=1):
                prefix = f'Rule {index}' if len(rules) > 1 else 'Rule'
                _append_if(fields, f'{prefix} API Groups', _join(getattr(rule, 'api_groups', None)))
                _append_if(fields, f'{prefix} Resources', _join(getattr(rule, 'resources', None)))
                _append_if(fields, f'{prefix} Non Resources', _join(getattr(rule, 'non_resource_urls', None)))
                _append_if(fields, f'{prefix} Verbs', _join(getattr(rule, 'verbs', None)))
    elif kind in {ROLE_BINDING, CLUSTER_ROLE_BINDING}:
        role_ref = getattr(obj, 'role_ref', None)
        _append_if(fields, 'Reference Kind', str(getattr(role_ref, 'kind', None) or '') if role_ref else '')
        _append_if(fields, 'Reference Name', str(getattr(role_ref, 'name', None) or '') if role_ref else '')
        _append_if(fields, 'Ref. API Group', str(getattr(role_ref, 'api_group', None) or '') if role_ref else '')
        subjects = list(getattr(obj, 'subjects', None) or [])
        if not subjects:
            fields.append(('Subjects', '(none)'))
        else:
            for index, subject in enumerate(subjects, start=1):
                prefix = f'Subject {index}' if len(subjects) > 1 else 'Subject'
                _append_if(fields, f'{prefix} Kind', str(getattr(subject, 'kind', None) or ''))
                _append_if(fields, f'{prefix} Name', str(getattr(subject, 'name', None) or ''))
                _append_if(fields, f'{prefix} Namespace', str(getattr(subject, 'namespace', None) or ''))
    return tuple(fields)
