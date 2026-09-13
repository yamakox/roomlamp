"""List and get Cluster catalog objects: Namespace and Node."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from kubernetes.client import ApiClient, CoreV1Api

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.nodes import ROLE_PREFIX
from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time
from roomlamp.k8s.workloads import format_age

NAMESPACE = 'Namespace'
NODE = 'Node'

CLUSTER_KINDS = (NAMESPACE, NODE)

# Headlamp Namespace.PROTECTED_NAMESPACES.
PROTECTED_NAMESPACES = ('kube-system', 'kube-node-lease', 'kube-public', 'default')
METADATA_NAME_LABEL = 'kubernetes.io/metadata.name'

# Headlamp Node Details extraInfo resource keys (API kebab-case).
NODE_RESOURCE_KEYS = ('cpu', 'memory', 'pods', 'ephemeral-storage')


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


CLUSTER_SPECS: dict[str, KindSpec] = {
    NAMESPACE: KindSpec(
        NAMESPACE,
        'Namespaces',
        '',
        'v1',
        'namespaces',
        False,
        '',
        'list_namespace',
        'read_namespace',
        ('Name', 'Status', 'Age'),
    ),
    NODE: KindSpec(
        NODE,
        'Nodes',
        '',
        'v1',
        'nodes',
        False,
        '',
        'list_node',
        'read_node',
        ('Name', 'Ready', 'Taints', 'Roles', 'Internal IP', 'External IP', 'Version', 'Age'),
    ),
}

CLUSTER_LABELS = {spec.kind: spec.label for spec in CLUSTER_SPECS.values()}


@dataclass(frozen=True)
class CatalogSummary:
    kind: str
    name: str
    namespace: str
    created: datetime | None
    cells: tuple[str, ...]
    sort_keys: tuple[object, ...]
    confirm_name: str | None = None

    @property
    def key(self) -> str:
        if self.namespace:
            return f'{self.namespace}/{self.name}'
        return self.name


@dataclass(frozen=True)
class CatalogDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]
    confirm_name: str | None = None


class CatalogReader(Protocol):
    def list_catalog(self, kind: str, namespace: str) -> list[CatalogSummary]: ...

    def get_catalog(self, kind: str, namespace: str, name: str) -> CatalogDetail: ...

    def get_catalog_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str: ...


class ApiCatalogReader:
    """Cluster catalog reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        if not hasattr(self, '_api_client'):
            self._api_client = api_client
        if not hasattr(self, '_core'):
            self._core = CoreV1Api(api_client)

    def list_catalog(self, kind: str, namespace: str) -> list[CatalogSummary]:
        items = self._list_catalog_raw(kind, namespace)
        return [summarize_catalog(kind, item) for item in items]

    def get_catalog(self, kind: str, namespace: str, name: str) -> CatalogDetail:
        return detail_catalog(kind, self._read_catalog(kind, namespace, name))

    def get_catalog_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        spec = _require_kind(kind)
        raw = self._read_catalog(kind, namespace, name)
        return dump_resource(
            raw,
            kind=kind,
            api_version=spec.api_version,
            hide_managed_fields=hide_managed_fields,
        )

    def catalog_list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._catalog_api()
        if not spec.namespaced or namespace == ALL_NAMESPACES:
            return getattr(api, spec.list_all), ()
        return getattr(api, spec.list_namespaced), (namespace,)

    def _list_catalog_raw(self, kind: str, namespace: str) -> list[object]:
        list_fn, args = self.catalog_list_call(kind, namespace)
        listed = list_fn(*args)
        return list(listed.items or [])

    def _read_catalog(self, kind: str, namespace: str, name: str) -> object:
        spec = _require_kind(kind)
        api = self._catalog_api()
        if spec.namespaced:
            return getattr(api, spec.read)(name, namespace)
        return getattr(api, spec.read)(name)

    def _catalog_api(self) -> CoreV1Api:
        return self._core


def is_catalog_kind(kind: str) -> bool:
    return kind in CLUSTER_SPECS


def is_namespaced(kind: str) -> bool:
    return _require_kind(kind).namespaced


def split_catalog_key(kind: str, key: str) -> tuple[str, str]:
    if is_namespaced(kind):
        namespace, name = key.split('/', 1)
        return namespace, name
    return '', key


def namespace_confirm_name(name: str, labels: Mapping[str, str] | None = None) -> str:
    """Name Headlamp asks the user to type. Label first, then object name."""
    if labels:
        labeled = labels.get(METADATA_NAME_LABEL)
        if labeled:
            return labeled
    return name


def is_protected_namespace(name: str, labels: Mapping[str, str] | None = None) -> bool:
    return namespace_confirm_name(name, labels) in PROTECTED_NAMESPACES


def protected_confirm_name(kind: str, name: str, labels: Mapping[str, str] | None = None) -> str | None:
    """Return the typed-confirm name for a protected Namespace, else None."""
    if kind != NAMESPACE:
        return None
    confirm = namespace_confirm_name(name, labels)
    if confirm in PROTECTED_NAMESPACES:
        return confirm
    return None


def summarize_catalog(kind: str, obj: object, now: datetime | None = None) -> CatalogSummary:
    spec = _require_kind(kind)
    return _SUMMARIZERS[kind](obj, spec, now)


def detail_catalog(kind: str, obj: object, now: datetime | None = None) -> CatalogDetail:
    _require_kind(kind)
    summary = summarize_catalog(kind, obj, now)
    meta = getattr(obj, 'metadata', None)
    labels = ()
    if meta and getattr(meta, 'labels', None):
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and getattr(meta, 'creation_timestamp', None):
        created = _format_time(meta.creation_timestamp)
    return CatalogDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=getattr(meta, 'uid', None) if meta else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, obj),
        confirm_name=summary.confirm_name,
    )


def _require_kind(kind: str) -> KindSpec:
    spec = CLUSTER_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown cluster kind: {kind}')
    return spec


def _meta_name(obj: object) -> tuple[str, str, datetime | None]:
    meta = getattr(obj, 'metadata', None)
    name = getattr(meta, 'name', None) if meta else None
    namespace = getattr(meta, 'namespace', None) if meta else None
    created = getattr(meta, 'creation_timestamp', None) if meta else None
    return name or '', namespace or '', created


def _meta_labels(obj: object) -> dict[str, str]:
    meta = getattr(obj, 'metadata', None)
    labels = getattr(meta, 'labels', None) if meta else None
    if not labels:
        return {}
    if isinstance(labels, dict):
        return {str(key): str(value) for key, value in labels.items()}
    return {str(key): str(value) for key, value in dict(labels).items()}


def _age_parts(created: datetime | None, now: datetime | None) -> tuple[str, float]:
    return format_age(created, now), created.timestamp() if created is not None else 0.0


def _make_summary(
    kind: str,
    name: str,
    namespace: str,
    created: datetime | None,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
    confirm_name: str | None = None,
) -> CatalogSummary:
    return CatalogSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=created,
        cells=cells,
        sort_keys=sort_keys,
        confirm_name=confirm_name,
    )


def _mapping(value: object | None) -> dict[str, object]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    return dict(value)


def _summarize_namespace(obj: object, spec: KindSpec, now: datetime | None) -> CatalogSummary:
    name, _namespace, created = _meta_name(obj)
    status = getattr(obj, 'status', None)
    phase = str(getattr(status, 'phase', None) or '')
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        '',
        created,
        (name, phase, age),
        (name, phase, age_key),
        confirm_name=protected_confirm_name(NAMESPACE, name, _meta_labels(obj)),
    )


def _summarize_node(obj: object, spec: KindSpec, now: datetime | None) -> CatalogSummary:
    name, _namespace, created = _meta_name(obj)
    ready = _node_ready(obj)
    taints = _taint_list(obj)
    roles = _node_roles(obj)
    internal_ip = _node_address(obj, 'InternalIP')
    external_ip = _node_address(obj, 'ExternalIP')
    version = _kubelet_version(obj)
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        '',
        created,
        (name, 'Yes' if ready else 'No', taints, roles, internal_ip, external_ip, version, age),
        (name, ready, taints, roles, internal_ip, external_ip, version, age_key),
    )


_SUMMARIZERS = {
    NAMESPACE: _summarize_namespace,
    NODE: _summarize_node,
}


def _detail_fields(kind: str, obj: object) -> tuple[tuple[str, str], ...]:
    if kind == NAMESPACE:
        return _namespace_fields(obj)
    if kind == NODE:
        return _node_fields(obj)
    return ()


def _namespace_fields(obj: object) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    status = getattr(obj, 'status', None)
    phase = str(getattr(status, 'phase', None) or '')
    fields.append(('Status', phase or '(none)'))
    for condition in getattr(status, 'conditions', None) or []:
        cond_type = str(getattr(condition, 'type', None) or '')
        cond_status = str(getattr(condition, 'status', None) or '')
        reason = str(getattr(condition, 'reason', None) or '')
        message = str(getattr(condition, 'message', None) or '')
        extra = ', '.join(part for part in (reason, message) if part)
        value = f'{cond_status} ({extra})' if extra else cond_status
        fields.append((f'Condition {cond_type}', value))
    return tuple(fields)


def _node_fields(obj: object) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    roles = _node_roles(obj)
    taints = _taint_list(obj)
    unschedulable = bool(getattr(spec, 'unschedulable', None)) if spec is not None else False
    fields.append(('Roles', roles or '(none)'))
    fields.append(('Taints', taints or '(none)'))
    fields.append(('Ready', 'Yes' if _node_ready(obj) else 'No'))
    fields.append(('Conditions', 'Scheduling Disabled' if unschedulable else 'Scheduling Enabled'))
    pod_cidr = str(getattr(spec, 'pod_cidr', None) or '') if spec is not None else ''
    if pod_cidr:
        fields.append(('Pod CIDR', pod_cidr))
    for address in getattr(status, 'addresses', None) or []:
        addr_type = str(getattr(address, 'type', None) or '')
        addr_value = str(getattr(address, 'address', None) or '')
        if addr_type:
            fields.append((addr_type, addr_value))
    capacity = _mapping(getattr(status, 'capacity', None) if status is not None else None)
    allocatable = _mapping(getattr(status, 'allocatable', None) if status is not None else None)
    for key in NODE_RESOURCE_KEYS:
        if key in capacity and capacity[key] is not None:
            fields.append((f'Capacity {key}', str(capacity[key])))
    for key in NODE_RESOURCE_KEYS:
        if key in allocatable and allocatable[key] is not None:
            fields.append((f'Allocatable {key}', str(allocatable[key])))
    info = getattr(status, 'node_info', None) if status is not None else None
    if info is not None:
        for label, attr in (
            ('Architecture', 'architecture'),
            ('Boot ID', 'boot_id'),
            ('System UUID', 'system_uuid'),
            ('OS', 'operating_system'),
            ('Image', 'os_image'),
            ('Kernel Version', 'kernel_version'),
            ('Machine ID', 'machine_id'),
            ('Kube Proxy Version', 'kube_proxy_version'),
            ('Kubelet Version', 'kubelet_version'),
            ('Container Runtime Version', 'container_runtime_version'),
        ):
            value = getattr(info, attr, None)
            if value:
                fields.append((label, str(value)))
    for condition in getattr(status, 'conditions', None) or []:
        cond_type = str(getattr(condition, 'type', None) or '')
        cond_status = str(getattr(condition, 'status', None) or '')
        if cond_type:
            fields.append((f'Condition {cond_type}', cond_status))
    return tuple(fields)


def _node_ready(obj: object) -> bool:
    status = getattr(obj, 'status', None)
    if status is None:
        return False
    for condition in getattr(status, 'conditions', None) or []:
        if getattr(condition, 'type', None) == 'Ready' and getattr(condition, 'status', None) == 'True':
            return True
    return False


def _node_address(obj: object, address_type: str) -> str:
    status = getattr(obj, 'status', None)
    if status is None:
        return ''
    for address in getattr(status, 'addresses', None) or []:
        if getattr(address, 'type', None) == address_type:
            return str(getattr(address, 'address', None) or '')
    return ''


def _kubelet_version(obj: object) -> str:
    status = getattr(obj, 'status', None)
    info = getattr(status, 'node_info', None) if status is not None else None
    version = getattr(info, 'kubelet_version', None) if info is not None else None
    return str(version) if version else ''


def _node_roles(obj: object) -> str:
    labels = _meta_labels(obj)
    roles = tuple(sorted(key.removeprefix(ROLE_PREFIX) for key in labels if key.startswith(ROLE_PREFIX)))
    return ', '.join(roles)


def _taint_list(obj: object) -> str:
    spec = getattr(obj, 'spec', None)
    taints = getattr(spec, 'taints', None) if spec is not None else None
    if not taints:
        return ''
    return ', '.join(_format_taint(item) for item in taints)


def _format_taint(taint: object) -> str:
    key = str(getattr(taint, 'key', None) or '')
    value = getattr(taint, 'value', None)
    effect = str(getattr(taint, 'effect', None) or '')
    if value:
        return f'{key}={value}:{effect}'
    return f'{key}:{effect}'
