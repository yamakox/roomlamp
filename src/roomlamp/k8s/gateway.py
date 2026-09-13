"""List and get Gateway API objects: Gateway, GatewayClass, HTTPRoute."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from kubernetes.client import ApiClient, CustomObjectsApi
from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time
from roomlamp.k8s.workloads import format_age

GATEWAY = 'Gateway'
GATEWAY_CLASS = 'GatewayClass'
HTTP_ROUTE = 'HTTPRoute'

GATEWAY_KINDS = (GATEWAY, GATEWAY_CLASS, HTTP_ROUTE)

GATEWAY_GROUP = 'gateway.networking.k8s.io'
GATEWAY_VERSIONS = ('v1', 'v1beta1')


@dataclass(frozen=True)
class KindSpec:
    kind: str
    label: str
    group: str
    version: str
    resource: str
    namespaced: bool
    columns: tuple[str, ...]

    @property
    def api_version(self) -> str:
        return f'{self.group}/{self.version}'


GATEWAY_SPECS: dict[str, KindSpec] = {
    GATEWAY: KindSpec(
        GATEWAY,
        'Gateways',
        GATEWAY_GROUP,
        'v1',
        'gateways',
        True,
        ('Namespace', 'Name', 'Class', 'Addresses', 'Listeners', 'Conditions', 'Age'),
    ),
    GATEWAY_CLASS: KindSpec(
        GATEWAY_CLASS,
        'Gateway Classes',
        GATEWAY_GROUP,
        'v1',
        'gatewayclasses',
        False,
        ('Name', 'Controller', 'Conditions', 'Age'),
    ),
    HTTP_ROUTE: KindSpec(
        HTTP_ROUTE,
        'HTTP Routes',
        GATEWAY_GROUP,
        'v1',
        'httproutes',
        True,
        ('Namespace', 'Name', 'Hostnames', 'Parents', 'Rules', 'Age'),
    ),
}

GATEWAY_LABELS = {spec.kind: spec.label for spec in GATEWAY_SPECS.values()}


@dataclass(frozen=True)
class GatewaySummary:
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
class GatewayDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]


class GatewayReader(Protocol):
    def available_gateway_kinds(self) -> tuple[str, ...]: ...

    def list_gateway(self, kind: str, namespace: str) -> list[GatewaySummary]: ...

    def get_gateway(self, kind: str, namespace: str, name: str) -> GatewayDetail: ...

    def get_gateway_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str: ...


class ApiGatewayReader:
    """Gateway API reads through ``CustomObjectsApi``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._api_client = api_client
        self._custom = CustomObjectsApi(api_client)
        self._available: dict[str, str] | None = None

    def available_gateway_kinds(self) -> tuple[str, ...]:
        discovered = self._discovered()
        return tuple(kind for kind in GATEWAY_KINDS if kind in discovered)

    def list_gateway(self, kind: str, namespace: str) -> list[GatewaySummary]:
        items = self._list_gateway_raw(kind, namespace)
        return [summarize_gateway(kind, item) for item in items]

    def get_gateway(self, kind: str, namespace: str, name: str) -> GatewayDetail:
        return detail_gateway(kind, self._read_gateway(kind, namespace, name))

    def get_gateway_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        spec = _require_kind(kind)
        raw = self._read_gateway(kind, namespace, name)
        version = self._version_for(kind)
        return dump_resource(
            raw,
            kind=kind,
            api_version=f'{spec.group}/{version}',
            hide_managed_fields=hide_managed_fields,
        )

    def gateway_list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._gateway_api()
        version = self._version_for(kind)
        if not spec.namespaced:
            return api.list_cluster_custom_object, (spec.group, version, spec.resource)
        if namespace == ALL_NAMESPACES:
            return api.list_custom_object_for_all_namespaces, (spec.group, version, spec.resource)
        return api.list_namespaced_custom_object, (spec.group, version, namespace, spec.resource)

    def _list_gateway_raw(self, kind: str, namespace: str) -> list[object]:
        list_fn, args = self.gateway_list_call(kind, namespace)
        listed = list_fn(*args)
        if isinstance(listed, dict):
            return list(listed.get('items') or [])
        return list(getattr(listed, 'items', None) or [])

    def _read_gateway(self, kind: str, namespace: str, name: str) -> object:
        spec = _require_kind(kind)
        api = self._gateway_api()
        version = self._version_for(kind)
        if spec.namespaced:
            return api.get_namespaced_custom_object(spec.group, version, namespace, spec.resource, name)
        return api.get_cluster_custom_object(spec.group, version, spec.resource, name)

    def _gateway_api(self) -> CustomObjectsApi:
        return self._custom

    def _discovered(self) -> dict[str, str]:
        if self._available is None:
            self._available = discover_gateway_kinds(self._api_client)
        return self._available

    def _version_for(self, kind: str) -> str:
        return self._discovered().get(kind) or _require_kind(kind).version


def discover_gateway_kinds(api_client: ApiClient) -> dict[str, str]:
    """Return served Gateway kinds mapped to preferred version (v1 before v1beta1)."""
    found: dict[str, str] = {}
    for version in GATEWAY_VERSIONS:
        for kind in _kinds_in_version(api_client, version):
            if kind not in found:
                found[kind] = version
    return found


def is_gateway_kind(kind: str) -> bool:
    return kind in GATEWAY_SPECS


def is_namespaced(kind: str) -> bool:
    return _require_kind(kind).namespaced


def split_gateway_key(kind: str, key: str) -> tuple[str, str]:
    if is_namespaced(kind):
        namespace, name = key.split('/', 1)
        return namespace, name
    return '', key


def summarize_gateway(kind: str, obj: object, now: datetime | None = None) -> GatewaySummary:
    spec = _require_kind(kind)
    return _SUMMARIZERS[kind](_as_mapping(obj), spec, now)


def detail_gateway(kind: str, obj: object, now: datetime | None = None) -> GatewayDetail:
    _require_kind(kind)
    data = _as_mapping(obj)
    summary = summarize_gateway(kind, data, now)
    meta = _meta_map(data)
    labels = _labels(meta)
    created = None
    stamp = meta.get('creationTimestamp')
    if stamp:
        created = _format_time(stamp if isinstance(stamp, datetime) else str(stamp))
    uid = meta.get('uid')
    return GatewayDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=str(uid) if uid else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, data),
    )


def _kinds_in_version(api_client: ApiClient, version: str) -> set[str]:
    try:
        body = api_client.call_api(
            f'/apis/{GATEWAY_GROUP}/{version}',
            'GET',
            header_params={'Accept': 'application/json'},
            response_types_map={200: 'object'},
            auth_settings=['BearerToken'],
            _return_http_data_only=True,
        )
    except ApiException:
        return set()
    except Exception:
        return set()
    resources = _resources_from_body(body)
    served: set[str] = set()
    for resource in resources:
        kind, name, verbs = _resource_fields(resource)
        if '/' in name:
            continue
        if kind in GATEWAY_SPECS and 'list' in verbs:
            served.add(kind)
    return served


def _resources_from_body(body: object) -> list[object]:
    if isinstance(body, dict):
        resources = body.get('resources')
    else:
        resources = getattr(body, 'resources', None)
    if not resources:
        return []
    return list(resources)


def _resource_fields(resource: object) -> tuple[str, str, list[str]]:
    if isinstance(resource, dict):
        kind = str(resource.get('kind') or '')
        name = str(resource.get('name') or '')
        verbs = [str(verb) for verb in (resource.get('verbs') or [])]
        return kind, name, verbs
    kind = str(getattr(resource, 'kind', None) or '')
    name = str(getattr(resource, 'name', None) or '')
    verbs = [str(verb) for verb in (getattr(resource, 'verbs', None) or [])]
    return kind, name, verbs


def _require_kind(kind: str) -> KindSpec:
    spec = GATEWAY_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown gateway kind: {kind}')
    return spec


def _as_mapping(obj: object) -> dict[str, object]:
    if isinstance(obj, dict):
        return obj
    raise TypeError('gateway object must be a mapping')


def _meta_map(obj: dict[str, object]) -> dict[str, object]:
    meta = obj.get('metadata')
    if isinstance(meta, dict):
        return meta
    return {}


def _spec_map(obj: dict[str, object]) -> dict[str, object]:
    spec = obj.get('spec')
    if isinstance(spec, dict):
        return spec
    return {}


def _status_map(obj: dict[str, object]) -> dict[str, object]:
    status = obj.get('status')
    if isinstance(status, dict):
        return status
    return {}


def _parse_created(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _meta_name(obj: dict[str, object]) -> tuple[str, str, datetime | None]:
    meta = _meta_map(obj)
    name = str(meta.get('name') or '')
    namespace = str(meta.get('namespace') or '')
    created = _parse_created(meta.get('creationTimestamp'))
    return name, namespace, created


def _labels(meta: dict[str, object]) -> tuple[tuple[str, str], ...]:
    labels = meta.get('labels')
    if not isinstance(labels, dict):
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _age_parts(created: datetime | None, now: datetime | None) -> tuple[str, float]:
    return format_age(created, now), created.timestamp() if created is not None else 0.0


def _make_summary(
    kind: str,
    name: str,
    namespace: str,
    created: datetime | None,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> GatewaySummary:
    return GatewaySummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=created,
        cells=cells,
        sort_keys=sort_keys,
    )


def _mapping_list(value: object | None) -> list[dict[str, object]]:
    if not value:
        return []
    return [item for item in value if isinstance(item, dict)]


def _true_condition_types(status: dict[str, object]) -> str:
    types: list[str] = []
    for condition in _mapping_list(status.get('conditions')):
        if str(condition.get('status') or '') != 'True':
            continue
        name = str(condition.get('type') or '')
        if name:
            types.append(name)
    return ', '.join(types)


def _condition_text(conditions: object | None) -> str:
    parts: list[str] = []
    for condition in _mapping_list(conditions):
        name = str(condition.get('type') or '')
        if not name:
            continue
        status = str(condition.get('status') or '')
        reason = str(condition.get('reason') or '')
        text = f'{name}={status}' if status else name
        if reason:
            text = f'{text} ({reason})'
        parts.append(text)
    return ', '.join(parts)


def _address_values(status: dict[str, object]) -> str:
    values: list[str] = []
    for item in _mapping_list(status.get('addresses')):
        value = str(item.get('value') or '')
        if value:
            values.append(value)
    return ', '.join(values)


def _address_lines(status: dict[str, object]) -> str:
    parts: list[str] = []
    for item in _mapping_list(status.get('addresses')):
        value = str(item.get('value') or '')
        kind = str(item.get('type') or '')
        if value and kind:
            parts.append(f'{kind}={value}')
        elif value:
            parts.append(value)
    return ', '.join(parts)


def _listener_count(spec: dict[str, object]) -> int:
    return len(_mapping_list(spec.get('listeners')))


def _listener_status_by_name(status: dict[str, object]) -> dict[str, dict[str, object]]:
    by_name: dict[str, dict[str, object]] = {}
    for item in _mapping_list(status.get('listeners')):
        name = str(item.get('name') or '')
        if name:
            by_name[name] = item
    return by_name


def _listener_lines(spec: dict[str, object], status: dict[str, object]) -> str:
    statuses = _listener_status_by_name(status)
    lines: list[str] = []
    for listener in _mapping_list(spec.get('listeners')):
        name = str(listener.get('name') or '')
        protocol = str(listener.get('protocol') or '')
        port = listener.get('port')
        hostname = str(listener.get('hostname') or '')
        endpoint = f'{protocol}:{port}' if protocol and port is not None else protocol or str(port or '')
        bits = [part for part in (name, endpoint, hostname) if part]
        listener_status = statuses.get(name) or {}
        attached = listener_status.get('attachedRoutes')
        if attached is not None:
            bits.append(f'routes={attached}')
        conditions = _true_condition_types(listener_status)
        if conditions:
            bits.append(conditions)
        if bits:
            lines.append(' '.join(bits))
    return '; '.join(lines)


def _hostnames(spec: dict[str, object]) -> str:
    hosts = spec.get('hostnames')
    if not hosts:
        return ''
    parts: list[str] = []
    for host in hosts:
        text = str(host) if host else '*'
        parts.append(text)
    return ', '.join(parts)


def _parent_ref_text(ref: dict[str, object]) -> str:
    kind = str(ref.get('kind') or 'Gateway')
    name = str(ref.get('name') or '')
    namespace = str(ref.get('namespace') or '')
    section = str(ref.get('sectionName') or '')
    label = f'{kind}/{namespace}/{name}' if namespace else f'{kind}/{name}'
    if section:
        label = f'{label}#{section}'
    return label


def _parent_refs(spec: dict[str, object]) -> str:
    return ', '.join(_parent_ref_text(ref) for ref in _mapping_list(spec.get('parentRefs')))


def _match_text(match: dict[str, object]) -> str:
    method = str(match.get('method') or '')
    path = match.get('path') if isinstance(match.get('path'), dict) else {}
    path_type = str(path.get('type') or '') if isinstance(path, dict) else ''
    path_value = str(path.get('value') or '') if isinstance(path, dict) else ''
    return ' '.join(part for part in (method, path_type, path_value) if part)


def _backend_text(ref: dict[str, object]) -> str:
    kind = str(ref.get('kind') or 'Service')
    name = str(ref.get('name') or '')
    port = ref.get('port')
    weight = ref.get('weight')
    text = f'{kind}/{name}' if name else kind
    if port is not None:
        text = f'{text}:{port}'
    if weight is not None:
        text = f'{text} w={weight}'
    return text


def _rule_line(rule: dict[str, object], index: int) -> str:
    name = str(rule.get('name') or '') or f'Rule {index}'
    matches = [_match_text(match) for match in _mapping_list(rule.get('matches'))]
    matches = [item for item in matches if item]
    backends = [_backend_text(ref) for ref in _mapping_list(rule.get('backendRefs'))]
    filters = [str(item.get('type') or '') for item in _mapping_list(rule.get('filters')) if item.get('type')]
    bits = [name]
    if matches:
        bits.append(', '.join(matches))
    if backends:
        bits.append('› ' + ', '.join(backends))
    if filters:
        bits.append('filters ' + ', '.join(filters))
    return ' '.join(bits)


def _rules_text(spec: dict[str, object]) -> str:
    rules = _mapping_list(spec.get('rules'))
    if not rules:
        return ''
    return '; '.join(_rule_line(rule, index) for index, rule in enumerate(rules, start=1))


def _summarize_gateway(obj: dict[str, object], spec: KindSpec, now: datetime | None) -> GatewaySummary:
    name, namespace, created = _meta_name(obj)
    gateway_spec = _spec_map(obj)
    status = _status_map(obj)
    class_name = str(gateway_spec.get('gatewayClassName') or '')
    addresses = _address_values(status)
    listeners = str(_listener_count(gateway_spec))
    conditions = _true_condition_types(status)
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, class_name, addresses, listeners, conditions, age),
        (namespace, name, class_name, addresses, int(listeners), conditions, age_key),
    )


def _summarize_gateway_class(obj: dict[str, object], spec: KindSpec, now: datetime | None) -> GatewaySummary:
    name, namespace, created = _meta_name(obj)
    controller = str(_spec_map(obj).get('controllerName') or '')
    conditions = _true_condition_types(_status_map(obj))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (name, controller, conditions, age),
        (name, controller, conditions, age_key),
    )


def _summarize_http_route(obj: dict[str, object], spec: KindSpec, now: datetime | None) -> GatewaySummary:
    name, namespace, created = _meta_name(obj)
    route_spec = _spec_map(obj)
    hostnames = _hostnames(route_spec)
    parents = _parent_refs(route_spec)
    rules = str(len(_mapping_list(route_spec.get('rules'))))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, hostnames, parents, rules, age),
        (namespace, name, hostnames, parents, int(rules), age_key),
    )


_SUMMARIZERS = {
    GATEWAY: _summarize_gateway,
    GATEWAY_CLASS: _summarize_gateway_class,
    HTTP_ROUTE: _summarize_http_route,
}


def _append_if(fields: list[tuple[str, str]], label: str, value: str) -> None:
    if value:
        fields.append((label, value))


def _detail_fields(kind: str, obj: dict[str, object]) -> tuple[tuple[str, str], ...]:
    spec = _spec_map(obj)
    status = _status_map(obj)
    fields: list[tuple[str, str]] = []
    if kind == GATEWAY:
        _append_if(fields, 'Class Name', str(spec.get('gatewayClassName') or ''))
        _append_if(fields, 'Addresses', _address_lines(status))
        _append_if(fields, 'Listeners', _listener_lines(spec, status))
        _append_if(fields, 'Conditions', _condition_text(status.get('conditions')))
    elif kind == GATEWAY_CLASS:
        _append_if(fields, 'Controller Name', str(spec.get('controllerName') or ''))
        _append_if(fields, 'Conditions', _condition_text(status.get('conditions')))
    elif kind == HTTP_ROUTE:
        _append_if(fields, 'Hostnames', _hostnames(spec))
        _append_if(fields, 'Parent Refs', _parent_refs(spec))
        _append_if(fields, 'Rules', _rules_text(spec))
    return tuple(fields)
