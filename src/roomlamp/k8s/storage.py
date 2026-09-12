"""List and get Storage objects: PVC, PV, and StorageClass."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api, StorageV1Api

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time
from roomlamp.k8s.workloads import format_age

PVC = 'PersistentVolumeClaim'
PV = 'PersistentVolume'
STORAGE_CLASS = 'StorageClass'

STORAGE_KINDS = (PVC, PV, STORAGE_CLASS)

DEFAULT_STORAGE_CLASS_ANNOTATION = 'storageclass.kubernetes.io/is-default-class'

# Headlamp frontend/src/lib/k8s/persistentVolume.ts PV_SOURCE_TYPES (camelCase display).
PV_SOURCE_TYPES = (
    ('csi', 'csi'),
    ('hostPath', 'host_path'),
    ('nfs', 'nfs'),
    ('local', 'local'),
    ('iscsi', 'iscsi'),
    ('cephfs', 'cephfs'),
    ('rbd', 'rbd'),
    ('glusterfs', 'glusterfs'),
    ('awsElasticBlockStore', 'aws_elastic_block_store'),
    ('gcePersistentDisk', 'gce_persistent_disk'),
    ('azureDisk', 'azure_disk'),
    ('azureFile', 'azure_file'),
    ('fc', 'fc'),
    ('flexVolume', 'flex_volume'),
    ('flocker', 'flocker'),
    ('photonPersistentDisk', 'photon_persistent_disk'),
    ('portworxVolume', 'portworx_volume'),
    ('scaleIO', 'scale_io'),
    ('storageos', 'storageos'),
    ('vsphereVolume', 'vsphere_volume'),
)


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


STORAGE_SPECS: dict[str, KindSpec] = {
    PVC: KindSpec(
        PVC,
        'Persistent Volume Claims',
        '',
        'v1',
        'persistentvolumeclaims',
        True,
        'list_namespaced_persistent_volume_claim',
        'list_persistent_volume_claim_for_all_namespaces',
        'read_namespaced_persistent_volume_claim',
        ('Namespace', 'Name', 'Status', 'Volume', 'Capacity', 'Access Modes', 'Storage Class', 'Age'),
    ),
    PV: KindSpec(
        PV,
        'Persistent Volumes',
        '',
        'v1',
        'persistentvolumes',
        False,
        '',
        'list_persistent_volume',
        'read_persistent_volume',
        ('Name', 'Capacity', 'Access Modes', 'Reclaim Policy', 'Status', 'Claim', 'Storage Class', 'Age'),
    ),
    STORAGE_CLASS: KindSpec(
        STORAGE_CLASS,
        'Storage Classes',
        'storage.k8s.io',
        'v1',
        'storageclasses',
        False,
        '',
        'list_storage_class',
        'read_storage_class',
        (
            'Name',
            'Provisioner',
            'Default',
            'Reclaim Policy',
            'Volume Binding Mode',
            'Allow Volume Expansion',
            'Age',
        ),
    ),
}

STORAGE_LABELS = {spec.kind: spec.label for spec in STORAGE_SPECS.values()}


@dataclass(frozen=True)
class StorageSummary:
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
class StorageDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]


class StorageReader(Protocol):
    def list_storage(self, kind: str, namespace: str) -> list[StorageSummary]: ...

    def get_storage(self, kind: str, namespace: str, name: str) -> StorageDetail: ...

    def get_storage_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str: ...


class ApiStorageReader:
    """Storage reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._core = CoreV1Api(api_client)
        self._storage = StorageV1Api(api_client)

    def list_storage(self, kind: str, namespace: str) -> list[StorageSummary]:
        items = self._list_storage_raw(kind, namespace)
        return [summarize_storage(kind, item) for item in items]

    def get_storage(self, kind: str, namespace: str, name: str) -> StorageDetail:
        return detail_storage(kind, self._read_storage(kind, namespace, name))

    def get_storage_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        spec = _require_kind(kind)
        raw = self._read_storage(kind, namespace, name)
        return dump_resource(
            raw,
            kind=kind,
            api_version=spec.api_version,
            hide_managed_fields=hide_managed_fields,
        )

    def storage_list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._storage_api(spec)
        if not spec.namespaced or namespace == ALL_NAMESPACES:
            return getattr(api, spec.list_all), ()
        return getattr(api, spec.list_namespaced), (namespace,)

    def _list_storage_raw(self, kind: str, namespace: str) -> list[object]:
        list_fn, args = self.storage_list_call(kind, namespace)
        listed = list_fn(*args)
        return list(listed.items or [])

    def _read_storage(self, kind: str, namespace: str, name: str) -> object:
        spec = _require_kind(kind)
        api = self._storage_api(spec)
        if spec.namespaced:
            return getattr(api, spec.read)(name, namespace)
        return getattr(api, spec.read)(name)

    def _storage_api(self, spec: KindSpec) -> CoreV1Api | StorageV1Api:
        return self._storage if spec.group else self._core


def is_storage_kind(kind: str) -> bool:
    return kind in STORAGE_SPECS


def is_namespaced(kind: str) -> bool:
    return _require_kind(kind).namespaced


def split_storage_key(kind: str, key: str) -> tuple[str, str]:
    if is_namespaced(kind):
        namespace, name = key.split('/', 1)
        return namespace, name
    return '', key


def summarize_storage(kind: str, obj: object, now: datetime | None = None) -> StorageSummary:
    spec = _require_kind(kind)
    return _SUMMARIZERS[kind](obj, spec, now)


def detail_storage(kind: str, obj: object, now: datetime | None = None) -> StorageDetail:
    _require_kind(kind)
    summary = summarize_storage(kind, obj, now)
    meta = getattr(obj, 'metadata', None)
    labels = ()
    if meta and getattr(meta, 'labels', None):
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and getattr(meta, 'creation_timestamp', None):
        created = _format_time(meta.creation_timestamp)
    return StorageDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=getattr(meta, 'uid', None) if meta else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, obj),
    )


def _require_kind(kind: str) -> KindSpec:
    spec = STORAGE_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown storage kind: {kind}')
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
) -> StorageSummary:
    return StorageSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=created,
        cells=cells,
        sort_keys=sort_keys,
    )


def _qty(value: object | None, key: str = 'storage') -> str:
    if value is None:
        return ''
    if isinstance(value, dict):
        item = value.get(key)
        return str(item) if item is not None else ''
    item = getattr(value, key, None)
    return str(item) if item is not None else ''


def _join(values: object | None) -> str:
    if not values:
        return ''
    return ', '.join(str(item) for item in values)


def _yes_no(value: bool) -> str:
    return 'Yes' if value else 'No'


def _is_default_class(obj: object) -> bool:
    meta = getattr(obj, 'metadata', None)
    annotations = getattr(meta, 'annotations', None) if meta else None
    if not annotations:
        return False
    return str(annotations.get(DEFAULT_STORAGE_CLASS_ANNOTATION, '')).lower() == 'true'


def _requested_storage(spec: object | None) -> str:
    resources = getattr(spec, 'resources', None) if spec else None
    requests = getattr(resources, 'requests', None) if resources else None
    return _qty(requests)


def _claim_text(spec: object | None) -> str:
    ref = getattr(spec, 'claim_ref', None) if spec else None
    if ref is None:
        return ''
    name = getattr(ref, 'name', None) or ''
    namespace = getattr(ref, 'namespace', None) or ''
    if namespace and name:
        return f'{namespace}/{name}'
    return name


def _source_type(spec: object | None) -> str:
    if spec is None:
        return ''
    for label, attr in PV_SOURCE_TYPES:
        if getattr(spec, attr, None) is not None:
            return label
    return ''


def _expand_text(value: object | None) -> str:
    if value is None:
        return ''
    return _yes_no(bool(value))


def _summarize_pvc(obj: object, spec: KindSpec, now: datetime | None) -> StorageSummary:
    name, namespace, created = _meta_name(obj)
    claim_spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    phase = str(getattr(status, 'phase', None) or '')
    volume = str(getattr(claim_spec, 'volume_name', None) or '')
    capacity = _qty(getattr(status, 'capacity', None) if status else None) or _requested_storage(claim_spec)
    modes = _join(getattr(claim_spec, 'access_modes', None))
    storage_class = str(getattr(claim_spec, 'storage_class_name', None) or '')
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, phase, volume, capacity, modes, storage_class, age),
        (namespace, name, phase, volume, capacity, modes, storage_class, age_key),
    )


def _summarize_pv(obj: object, spec: KindSpec, now: datetime | None) -> StorageSummary:
    name, _namespace, created = _meta_name(obj)
    pv_spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    capacity = _qty(getattr(pv_spec, 'capacity', None) if pv_spec else None)
    modes = _join(getattr(pv_spec, 'access_modes', None) if pv_spec else None)
    reclaim = str(getattr(pv_spec, 'persistent_volume_reclaim_policy', None) or '')
    phase = str(getattr(status, 'phase', None) or '')
    claim = _claim_text(pv_spec)
    storage_class = str(getattr(pv_spec, 'storage_class_name', None) or '')
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        '',
        created,
        (name, capacity, modes, reclaim, phase, claim, storage_class, age),
        (name, capacity, modes, reclaim, phase, claim, storage_class, age_key),
    )


def _summarize_storage_class(obj: object, spec: KindSpec, now: datetime | None) -> StorageSummary:
    name, _namespace, created = _meta_name(obj)
    provisioner = str(getattr(obj, 'provisioner', None) or '')
    default = 'Yes' if _is_default_class(obj) else ''
    reclaim = str(getattr(obj, 'reclaim_policy', None) or '')
    binding = str(getattr(obj, 'volume_binding_mode', None) or '')
    expand = _expand_text(getattr(obj, 'allow_volume_expansion', None))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        '',
        created,
        (name, provisioner, default, reclaim, binding, expand, age),
        (name, provisioner, default, reclaim, binding, expand, age_key),
    )


_SUMMARIZERS = {
    PVC: _summarize_pvc,
    PV: _summarize_pv,
    STORAGE_CLASS: _summarize_storage_class,
}


def _append_if(fields: list[tuple[str, str]], label: str, value: str) -> None:
    if value:
        fields.append((label, value))


def _detail_fields(kind: str, obj: object) -> tuple[tuple[str, str], ...]:
    spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    fields: list[tuple[str, str]] = []
    if kind == PVC:
        _append_if(fields, 'Status', str(getattr(status, 'phase', None) or ''))
        _append_if(fields, 'Volume', str(getattr(spec, 'volume_name', None) or ''))
        _append_if(fields, 'Requested', _requested_storage(spec))
        capacity = _qty(getattr(status, 'capacity', None) if status else None) or _requested_storage(spec)
        _append_if(fields, 'Capacity', capacity)
        modes = _join(getattr(status, 'access_modes', None) if status else None) or _join(
            getattr(spec, 'access_modes', None)
        )
        _append_if(fields, 'Access Modes', modes)
        _append_if(fields, 'Volume Mode', str(getattr(spec, 'volume_mode', None) or ''))
        _append_if(fields, 'Storage Class', str(getattr(spec, 'storage_class_name', None) or ''))
    elif kind == PV:
        _append_if(fields, 'Status', str(getattr(status, 'phase', None) or ''))
        _append_if(fields, 'Capacity', _qty(getattr(spec, 'capacity', None) if spec else None))
        _append_if(fields, 'Access Modes', _join(getattr(spec, 'access_modes', None) if spec else None))
        _append_if(fields, 'Volume Mode', str(getattr(spec, 'volume_mode', None) or ''))
        _append_if(fields, 'Reclaim Policy', str(getattr(spec, 'persistent_volume_reclaim_policy', None) or ''))
        _append_if(fields, 'Storage Class', str(getattr(spec, 'storage_class_name', None) or ''))
        _append_if(fields, 'Claim', _claim_text(spec))
        _append_if(fields, 'Source', _source_type(spec))
        _append_if(fields, 'Reason', str(getattr(status, 'reason', None) or ''))
        _append_if(fields, 'Message', str(getattr(status, 'message', None) or ''))
    elif kind == STORAGE_CLASS:
        fields.append(('Provisioner', str(getattr(obj, 'provisioner', None) or '')))
        _append_if(fields, 'Reclaim Policy', str(getattr(obj, 'reclaim_policy', None) or ''))
        _append_if(fields, 'Binding Mode', str(getattr(obj, 'volume_binding_mode', None) or ''))
        fields.append(('Default', _yes_no(_is_default_class(obj))))
        expand = getattr(obj, 'allow_volume_expansion', None)
        if expand is not None:
            fields.append(('Allow Volume Expansion', _yes_no(bool(expand))))
        parameters = getattr(obj, 'parameters', None) or {}
        if parameters:
            text = ', '.join(f'{key}={value}' for key, value in sorted(parameters.items()))
            fields.append(('Parameters', text))
        _append_if(fields, 'Mount Options', _join(getattr(obj, 'mount_options', None)))
    return tuple(fields)
