"""List and get Configuration objects: ConfigMap and Secret."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time
from roomlamp.k8s.workloads import format_age

CONFIG_MAP = 'ConfigMap'
SECRET = 'Secret'

CONFIGURATION_KINDS = (CONFIG_MAP, SECRET)


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


CONFIGURATION_SPECS: dict[str, KindSpec] = {
    CONFIG_MAP: KindSpec(
        CONFIG_MAP,
        'Config Maps',
        '',
        'v1',
        'configmaps',
        True,
        'list_namespaced_config_map',
        'list_config_map_for_all_namespaces',
        'read_namespaced_config_map',
        ('Namespace', 'Name', 'Data', 'Age'),
    ),
    SECRET: KindSpec(
        SECRET,
        'Secrets',
        '',
        'v1',
        'secrets',
        True,
        'list_namespaced_secret',
        'list_secret_for_all_namespaces',
        'read_namespaced_secret',
        ('Namespace', 'Name', 'Type', 'Data', 'Age'),
    ),
}

CONFIGURATION_LABELS = {spec.kind: spec.label for spec in CONFIGURATION_SPECS.values()}


@dataclass(frozen=True)
class ConfigurationSummary:
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
class ConfigurationDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]


class ConfigurationReader(Protocol):
    def list_configuration(self, kind: str, namespace: str) -> list[ConfigurationSummary]: ...

    def get_configuration(self, kind: str, namespace: str, name: str) -> ConfigurationDetail: ...

    def get_configuration_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str: ...


class ApiConfigReader:
    """Configuration reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._core = CoreV1Api(api_client)

    def list_configuration(self, kind: str, namespace: str) -> list[ConfigurationSummary]:
        items = self._list_config_raw(kind, namespace)
        return [summarize_configuration(kind, item) for item in items]

    def get_configuration(self, kind: str, namespace: str, name: str) -> ConfigurationDetail:
        return detail_configuration(kind, self._read_config(kind, namespace, name))

    def get_configuration_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        spec = _require_kind(kind)
        raw = self._read_config(kind, namespace, name)
        return dump_resource(
            raw,
            kind=kind,
            api_version=spec.api_version,
            hide_managed_fields=hide_managed_fields,
        )

    def config_list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._config_api()
        if not spec.namespaced or namespace == ALL_NAMESPACES:
            return getattr(api, spec.list_all), ()
        return getattr(api, spec.list_namespaced), (namespace,)

    def _list_config_raw(self, kind: str, namespace: str) -> list[object]:
        list_fn, args = self.config_list_call(kind, namespace)
        listed = list_fn(*args)
        return list(listed.items or [])

    def _read_config(self, kind: str, namespace: str, name: str) -> object:
        spec = _require_kind(kind)
        api = self._config_api()
        if spec.namespaced:
            return getattr(api, spec.read)(name, namespace)
        return getattr(api, spec.read)(name)

    def _config_api(self) -> CoreV1Api:
        return self._core


def is_configuration_kind(kind: str) -> bool:
    return kind in CONFIGURATION_SPECS


def is_namespaced(kind: str) -> bool:
    return _require_kind(kind).namespaced


def split_configuration_key(kind: str, key: str) -> tuple[str, str]:
    if is_namespaced(kind):
        namespace, name = key.split('/', 1)
        return namespace, name
    return '', key


def summarize_configuration(kind: str, obj: object, now: datetime | None = None) -> ConfigurationSummary:
    spec = _require_kind(kind)
    return _SUMMARIZERS[kind](obj, spec, now)


def detail_configuration(kind: str, obj: object, now: datetime | None = None) -> ConfigurationDetail:
    _require_kind(kind)
    summary = summarize_configuration(kind, obj, now)
    meta = getattr(obj, 'metadata', None)
    labels = ()
    if meta and getattr(meta, 'labels', None):
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and getattr(meta, 'creation_timestamp', None):
        created = _format_time(meta.creation_timestamp)
    return ConfigurationDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=getattr(meta, 'uid', None) if meta else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, obj),
    )


def _require_kind(kind: str) -> KindSpec:
    spec = CONFIGURATION_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown configuration kind: {kind}')
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
) -> ConfigurationSummary:
    return ConfigurationSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=created,
        cells=cells,
        sort_keys=sort_keys,
    )


def _mapping(value: object | None) -> dict[str, object]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    return dict(value)


def _data_count(*values: object | None) -> int:
    return sum(len(_mapping(value)) for value in values)


def _secret_byte_count(value: object) -> int:
    """Decoded size of a Secret data entry. Does not return the bytes."""
    if value is None:
        return 0
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    text = str(value)
    try:
        return len(base64.b64decode(text, validate=False))
    except Exception:
        return len(text.encode())


def _config_text(value: object) -> str:
    if value is None:
        return ''
    if isinstance(value, (bytes, bytearray)):
        return value.decode('utf-8', errors='replace')
    return str(value)


def _summarize_config_map(obj: object, spec: KindSpec, now: datetime | None) -> ConfigurationSummary:
    name, namespace, created = _meta_name(obj)
    data = _data_count(getattr(obj, 'data', None), getattr(obj, 'binary_data', None))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, str(data), age),
        (namespace, name, data, age_key),
    )


def _summarize_secret(obj: object, spec: KindSpec, now: datetime | None) -> ConfigurationSummary:
    name, namespace, created = _meta_name(obj)
    secret_type = str(getattr(obj, 'type', None) or '')
    data = _data_count(getattr(obj, 'data', None))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, secret_type, str(data), age),
        (namespace, name, secret_type, data, age_key),
    )


_SUMMARIZERS = {
    CONFIG_MAP: _summarize_config_map,
    SECRET: _summarize_secret,
}


def _detail_fields(kind: str, obj: object) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    if kind == CONFIG_MAP:
        data = _mapping(getattr(obj, 'data', None))
        binary = _mapping(getattr(obj, 'binary_data', None))
        if not data:
            fields.append(('Data', '(none)'))
        else:
            for key in sorted(data):
                fields.append((f'Data {key}', _config_text(data[key])))
        if not binary:
            fields.append(('Binary Data', '(none)'))
        else:
            for key in sorted(binary):
                fields.append((f'Binary Data {key}', _config_text(binary[key])))
    elif kind == SECRET:
        fields.append(('Type', str(getattr(obj, 'type', None) or '')))
        data = _mapping(getattr(obj, 'data', None))
        if not data:
            fields.append(('Data', '(none)'))
        else:
            for key in sorted(data):
                fields.append((f'Data {key}', f'{_secret_byte_count(data[key])} bytes'))
    return tuple(fields)
