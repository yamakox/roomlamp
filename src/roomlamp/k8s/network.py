"""List and get Network objects: Service, Endpoints, EndpointSlice, Ingress."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api, DiscoveryV1Api, NetworkingV1Api

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time
from roomlamp.k8s.workloads import format_age

SERVICE = 'Service'
ENDPOINTS = 'Endpoints'
ENDPOINT_SLICE = 'EndpointSlice'
INGRESS = 'Ingress'

NETWORK_KINDS = (SERVICE, ENDPOINTS, ENDPOINT_SLICE, INGRESS)

DISCOVERY_GROUP = 'discovery.k8s.io'
NETWORKING_GROUP = 'networking.k8s.io'


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


NETWORK_SPECS: dict[str, KindSpec] = {
    SERVICE: KindSpec(
        SERVICE,
        'Services',
        '',
        'v1',
        'services',
        True,
        'list_namespaced_service',
        'list_service_for_all_namespaces',
        'read_namespaced_service',
        ('Namespace', 'Name', 'Type', 'Cluster IP', 'External IP', 'Ports', 'Selector', 'Age'),
    ),
    ENDPOINTS: KindSpec(
        ENDPOINTS,
        'Endpoints',
        '',
        'v1',
        'endpoints',
        True,
        'list_namespaced_endpoints',
        'list_endpoints_for_all_namespaces',
        'read_namespaced_endpoints',
        ('Namespace', 'Name', 'Addresses', 'Age'),
    ),
    ENDPOINT_SLICE: KindSpec(
        ENDPOINT_SLICE,
        'Endpoint Slices',
        DISCOVERY_GROUP,
        'v1',
        'endpointslices',
        True,
        'list_namespaced_endpoint_slice',
        'list_endpoint_slice_for_all_namespaces',
        'read_namespaced_endpoint_slice',
        ('Namespace', 'Name', 'Endpoints', 'Ports', 'Address Type', 'Age'),
    ),
    INGRESS: KindSpec(
        INGRESS,
        'Ingresses',
        NETWORKING_GROUP,
        'v1',
        'ingresses',
        True,
        'list_namespaced_ingress',
        'list_ingress_for_all_namespaces',
        'read_namespaced_ingress',
        ('Namespace', 'Name', 'Class', 'Hosts', 'Address', 'Ports', 'Age'),
    ),
}

NETWORK_LABELS = {spec.kind: spec.label for spec in NETWORK_SPECS.values()}


@dataclass(frozen=True)
class NetworkSummary:
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
class NetworkDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]


class NetworkReader(Protocol):
    def list_network(self, kind: str, namespace: str) -> list[NetworkSummary]: ...

    def get_network(self, kind: str, namespace: str, name: str) -> NetworkDetail: ...

    def get_network_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str: ...


class ApiNetworkReader:
    """Network reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._core = CoreV1Api(api_client)
        self._discovery = DiscoveryV1Api(api_client)
        self._networking = NetworkingV1Api(api_client)

    def list_network(self, kind: str, namespace: str) -> list[NetworkSummary]:
        items = self._list_network_raw(kind, namespace)
        return [summarize_network(kind, item) for item in items]

    def get_network(self, kind: str, namespace: str, name: str) -> NetworkDetail:
        return detail_network(kind, self._read_network(kind, namespace, name))

    def get_network_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        spec = _require_kind(kind)
        raw = self._read_network(kind, namespace, name)
        return dump_resource(
            raw,
            kind=kind,
            api_version=spec.api_version,
            hide_managed_fields=hide_managed_fields,
        )

    def network_list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._network_api(spec)
        if not spec.namespaced or namespace == ALL_NAMESPACES:
            return getattr(api, spec.list_all), ()
        return getattr(api, spec.list_namespaced), (namespace,)

    def _list_network_raw(self, kind: str, namespace: str) -> list[object]:
        list_fn, args = self.network_list_call(kind, namespace)
        listed = list_fn(*args)
        return list(listed.items or [])

    def _read_network(self, kind: str, namespace: str, name: str) -> object:
        spec = _require_kind(kind)
        api = self._network_api(spec)
        if spec.namespaced:
            return getattr(api, spec.read)(name, namespace)
        return getattr(api, spec.read)(name)

    def _network_api(self, spec: KindSpec) -> CoreV1Api | DiscoveryV1Api | NetworkingV1Api:
        if spec.group == DISCOVERY_GROUP:
            return self._discovery
        if spec.group == NETWORKING_GROUP:
            return self._networking
        return self._core


def is_network_kind(kind: str) -> bool:
    return kind in NETWORK_SPECS


def is_namespaced(kind: str) -> bool:
    return _require_kind(kind).namespaced


def split_network_key(kind: str, key: str) -> tuple[str, str]:
    if is_namespaced(kind):
        namespace, name = key.split('/', 1)
        return namespace, name
    return '', key


def summarize_network(kind: str, obj: object, now: datetime | None = None) -> NetworkSummary:
    spec = _require_kind(kind)
    return _SUMMARIZERS[kind](obj, spec, now)


def detail_network(kind: str, obj: object, now: datetime | None = None) -> NetworkDetail:
    _require_kind(kind)
    summary = summarize_network(kind, obj, now)
    meta = getattr(obj, 'metadata', None)
    labels = ()
    if meta and getattr(meta, 'labels', None):
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and getattr(meta, 'creation_timestamp', None):
        created = _format_time(meta.creation_timestamp)
    return NetworkDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=getattr(meta, 'uid', None) if meta else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, obj),
    )


def _require_kind(kind: str) -> KindSpec:
    spec = NETWORK_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown network kind: {kind}')
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
) -> NetworkSummary:
    return NetworkSummary(
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


def _selector_text(spec: object | None) -> str:
    selector = getattr(spec, 'selector', None) if spec else None
    if not selector:
        return ''
    return ', '.join(f'{key}={value}' for key, value in sorted(selector.items()))


def _external_addresses(obj: object) -> str:
    spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    parts: list[str] = []
    seen: set[str] = set()
    for item in _lb_ingress(status):
        address = str(getattr(item, 'hostname', None) or getattr(item, 'ip', None) or '')
        if address and address not in seen:
            seen.add(address)
            parts.append(address)
    for ip in getattr(spec, 'external_ips', None) or []:
        text = str(ip)
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
    return ', '.join(parts)


def _lb_ingress(status: object | None) -> list[object]:
    if status is None:
        return []
    load_balancer = getattr(status, 'load_balancer', None)
    return list(getattr(load_balancer, 'ingress', None) or [])


def _format_service_port(port: object) -> str:
    number = getattr(port, 'port', None)
    node_port = getattr(port, 'node_port', None)
    target = getattr(port, 'target_port', None)
    protocol = str(getattr(port, 'protocol', None) or '')
    same_port = target is not None and str(target) == str(number)
    secondary = node_port if node_port is not None else (None if same_port else target)
    label = f'{number}:{secondary}' if secondary is not None else f'{number}'
    return f'{label}/{protocol}' if protocol else label


def _service_ports(spec: object | None) -> str:
    ports = getattr(spec, 'ports', None) if spec else None
    if not ports:
        return ''
    return ', '.join(_format_service_port(port) for port in ports)


def _endpoint_addresses(obj: object) -> list[str]:
    addresses: list[str] = []
    for subset in getattr(obj, 'subsets', None) or []:
        ports = getattr(subset, 'ports', None) or []
        ready = getattr(subset, 'addresses', None) or []
        for port in ports:
            number = getattr(port, 'port', None)
            for address in ready:
                ip = str(getattr(address, 'ip', None) or '')
                if not ip:
                    continue
                addresses.append(f'{ip}:{number}' if number is not None else ip)
    return addresses


def _slice_addresses(obj: object) -> str:
    parts: list[str] = []
    for endpoint in getattr(obj, 'endpoints', None) or []:
        parts.extend(str(item) for item in (getattr(endpoint, 'addresses', None) or []) if item)
    return ', '.join(parts)


def _slice_ports(obj: object) -> str:
    ports = getattr(obj, 'ports', None) or []
    return _join(getattr(port, 'port', None) for port in ports)


def _ingress_hosts(spec: object | None) -> str:
    hosts: list[str] = []
    for rule in getattr(spec, 'rules', None) or []:
        hosts.append(str(getattr(rule, 'host', None) or '*'))
    return ', '.join(hosts)


def _ingress_backend(backend: object | None) -> str:
    if backend is None:
        return ''
    service = getattr(backend, 'service', None)
    if service is not None:
        name = str(getattr(service, 'name', None) or '')
        port = getattr(service, 'port', None)
        port_text = ''
        if port is not None:
            number = getattr(port, 'number', None)
            port_text = str(number if number is not None else getattr(port, 'name', None) or '')
        if name and port_text:
            return f'{name}:{port_text}'
        return name or port_text
    resource = getattr(backend, 'resource', None)
    if resource is None:
        return ''
    kind = str(getattr(resource, 'kind', None) or '')
    name = str(getattr(resource, 'name', None) or '')
    if kind and name:
        return f'{kind}:{name}'
    return name


def _ingress_default_backend(spec: object | None) -> str:
    backend = getattr(spec, 'default_backend', None) if spec else None
    if backend is None:
        return '-'
    service = getattr(backend, 'service', None)
    if service is not None:
        name = str(getattr(service, 'name', None) or '')
        port = getattr(service, 'port', None)
        port_text = '-'
        if port is not None:
            number = getattr(port, 'number', None)
            port_text = str(number if number is not None else getattr(port, 'name', None) or '-')
        return f'{name}:{port_text}'
    resource = getattr(backend, 'resource', None)
    if resource is None:
        return '-'
    kind = str(getattr(resource, 'kind', None) or '')
    name = str(getattr(resource, 'name', None) or '')
    if kind and name:
        return f'{kind}/{name}'
    return name or '-'


def _ingress_ports(spec: object | None) -> str:
    ports: list[str] = []
    for rule in getattr(spec, 'rules', None) or []:
        http = getattr(rule, 'http', None)
        for path in getattr(http, 'paths', None) or []:
            backend = getattr(path, 'backend', None)
            service = getattr(backend, 'service', None) if backend else None
            if service is not None:
                port = getattr(service, 'port', None)
                if port is not None:
                    number = getattr(port, 'number', None)
                    text = str(number if number is not None else getattr(port, 'name', None) or '')
                    if text:
                        ports.append(text)
            else:
                resource = getattr(backend, 'resource', None) if backend else None
                if resource is not None:
                    kind = str(getattr(resource, 'kind', None) or '')
                    name = str(getattr(resource, 'name', None) or '')
                    if kind and name:
                        ports.append(f'{kind}:{name}')
                    elif name:
                        ports.append(name)
    if getattr(spec, 'tls', None):
        ports.append('443')
    unique = sorted(set(ports), key=_port_sort_key)
    return ', '.join(unique)


def _port_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _ingress_address(obj: object) -> str:
    parts: list[str] = []
    for item in _lb_ingress(getattr(obj, 'status', None)):
        address = str(getattr(item, 'hostname', None) or getattr(item, 'ip', None) or '')
        if address:
            parts.append(address)
    return ', '.join(parts)


def _ingress_rules(spec: object | None) -> str:
    lines: list[str] = []
    for rule in getattr(spec, 'rules', None) or []:
        host = str(getattr(rule, 'host', None) or '*')
        http = getattr(rule, 'http', None)
        paths = getattr(http, 'paths', None) or []
        if not paths:
            lines.append(host)
            continue
        for path in paths:
            path_text = str(getattr(path, 'path', None) or '')
            path_type = str(getattr(path, 'path_type', None) or '')
            target = _ingress_backend(getattr(path, 'backend', None))
            suffix = f' ({path_type})' if path_type else ''
            if path_text and target:
                lines.append(f'{host} {path_text}{suffix} › {target}')
            elif path_text:
                lines.append(f'{host} {path_text}{suffix}')
            elif target:
                lines.append(f'{host} › {target}')
            else:
                lines.append(host)
    return '; '.join(lines)


def _ingress_tls(spec: object | None) -> str:
    parts: list[str] = []
    for item in getattr(spec, 'tls', None) or []:
        secret = str(getattr(item, 'secret_name', None) or '')
        hosts = _join(getattr(item, 'hosts', None))
        if secret and hosts:
            parts.append(f'{secret} › {hosts}')
        elif secret:
            parts.append(secret)
        elif hosts:
            parts.append(hosts)
    return ', '.join(parts)


def _session_affinity(spec: object | None) -> str:
    affinity = str(getattr(spec, 'session_affinity', None) or '') if spec else ''
    if not affinity or affinity == 'None':
        return ''
    if affinity == 'ClientIP':
        config = getattr(spec, 'session_affinity_config', None)
        client_ip = getattr(config, 'client_ip', None) if config else None
        timeout = getattr(client_ip, 'timeout_seconds', None) if client_ip else None
        if timeout is not None:
            return f'{affinity} ({timeout}s)'
    return affinity


def _cluster_ips_text(spec: object | None) -> str:
    cluster_ip = str(getattr(spec, 'cluster_ip', None) or '') if spec else ''
    cluster_ips = [str(item) for item in (getattr(spec, 'cluster_ips', None) or []) if item]
    if not cluster_ips or cluster_ips == [cluster_ip]:
        return ''
    return ', '.join(cluster_ips)


def _summarize_service(obj: object, spec: KindSpec, now: datetime | None) -> NetworkSummary:
    name, namespace, created = _meta_name(obj)
    service_spec = getattr(obj, 'spec', None)
    service_type = str(getattr(service_spec, 'type', None) or '')
    cluster_ip = str(getattr(service_spec, 'cluster_ip', None) or '')
    external = _external_addresses(obj)
    ports = _service_ports(service_spec)
    selector = _selector_text(service_spec)
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, service_type, cluster_ip, external, ports, selector, age),
        (namespace, name, service_type, cluster_ip, external, ports, selector, age_key),
    )


def _summarize_endpoints(obj: object, spec: KindSpec, now: datetime | None) -> NetworkSummary:
    name, namespace, created = _meta_name(obj)
    addresses = ', '.join(_endpoint_addresses(obj))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, addresses, age),
        (namespace, name, addresses, age_key),
    )


def _summarize_endpoint_slice(obj: object, spec: KindSpec, now: datetime | None) -> NetworkSummary:
    name, namespace, created = _meta_name(obj)
    endpoints = _slice_addresses(obj)
    ports = _slice_ports(obj)
    address_type = str(getattr(obj, 'address_type', None) or '')
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, endpoints, ports, address_type, age),
        (namespace, name, endpoints, ports, address_type, age_key),
    )


def _summarize_ingress(obj: object, spec: KindSpec, now: datetime | None) -> NetworkSummary:
    name, namespace, created = _meta_name(obj)
    ingress_spec = getattr(obj, 'spec', None)
    class_name = str(getattr(ingress_spec, 'ingress_class_name', None) or '')
    hosts = _ingress_hosts(ingress_spec)
    address = _ingress_address(obj)
    ports = _ingress_ports(ingress_spec)
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, class_name, hosts, address, ports, age),
        (namespace, name, class_name, hosts, address, ports, age_key),
    )


_SUMMARIZERS = {
    SERVICE: _summarize_service,
    ENDPOINTS: _summarize_endpoints,
    ENDPOINT_SLICE: _summarize_endpoint_slice,
    INGRESS: _summarize_ingress,
}


def _append_if(fields: list[tuple[str, str]], label: str, value: str) -> None:
    if value:
        fields.append((label, value))


def _condition_text(conditions: object | None) -> str:
    if conditions is None:
        return ''
    parts: list[str] = []
    for name in ('ready', 'serving', 'terminating'):
        value = getattr(conditions, name, None)
        if value is None:
            continue
        parts.append(name.capitalize() if value else f'not {name.capitalize()}')
    return ', '.join(parts)


def _subset_address_lines(subset: object) -> str:
    lines: list[str] = []
    for address in getattr(subset, 'addresses', None) or []:
        ip = str(getattr(address, 'ip', None) or '')
        hostname = str(getattr(address, 'hostname', None) or '')
        target = getattr(address, 'target_ref', None)
        target_name = str(getattr(target, 'name', None) or '') if target else ''
        extra: list[str] = []
        if hostname:
            extra.append(hostname)
        if target_name and target_name != hostname:
            extra.append(target_name)
        if extra:
            lines.append(f'{ip} ({", ".join(extra)})' if ip else ', '.join(extra))
        elif ip:
            lines.append(ip)
    return ', '.join(lines)


def _subset_port_lines(subset: object) -> str:
    return _named_ports(getattr(subset, 'ports', None))


def _slice_endpoint_lines(obj: object) -> str:
    lines: list[str] = []
    for endpoint in getattr(obj, 'endpoints', None) or []:
        addresses = _join(getattr(endpoint, 'addresses', None))
        hostname = str(getattr(endpoint, 'hostname', None) or '')
        node = str(getattr(endpoint, 'node_name', None) or '')
        zone = str(getattr(endpoint, 'zone', None) or '')
        conditions = _condition_text(getattr(endpoint, 'conditions', None))
        bits = [part for part in (addresses, hostname, node, zone, conditions) if part]
        if bits:
            lines.append(', '.join(bits))
    return '; '.join(lines)


def _named_ports(ports: object | None) -> str:
    parts: list[str] = []
    for port in ports or []:
        name = str(getattr(port, 'name', None) or '')
        number = getattr(port, 'port', None)
        protocol = str(getattr(port, 'protocol', None) or '')
        label = f'{number}' if number is not None else ''
        if protocol:
            label = f'{label}/{protocol}' if label else protocol
        if name:
            label = f'{name} {label}'.strip()
        if label:
            parts.append(label)
    return ', '.join(parts)


def _detail_fields(kind: str, obj: object) -> tuple[tuple[str, str], ...]:
    spec = getattr(obj, 'spec', None)
    fields: list[tuple[str, str]] = []
    if kind == SERVICE:
        _append_if(fields, 'Type', str(getattr(spec, 'type', None) or ''))
        _append_if(fields, 'Cluster IP', str(getattr(spec, 'cluster_ip', None) or ''))
        _append_if(fields, 'Cluster IPs', _cluster_ips_text(spec))
        _append_if(fields, 'External IP', _external_addresses(obj))
        _append_if(fields, 'External Name', str(getattr(spec, 'external_name', None) or ''))
        _append_if(fields, 'IP Families', _join(getattr(spec, 'ip_families', None)))
        _append_if(fields, 'IP Family Policy', str(getattr(spec, 'ip_family_policy', None) or ''))
        _append_if(fields, 'Session Affinity', _session_affinity(spec))
        _append_if(fields, 'External Traffic Policy', str(getattr(spec, 'external_traffic_policy', None) or ''))
        _append_if(fields, 'Internal Traffic Policy', str(getattr(spec, 'internal_traffic_policy', None) or ''))
        health = getattr(spec, 'health_check_node_port', None)
        if health:
            fields.append(('Health Check Node Port', str(health)))
        _append_if(fields, 'Load Balancer Class', str(getattr(spec, 'load_balancer_class', None) or ''))
        _append_if(fields, 'Load Balancer Source Ranges', _join(getattr(spec, 'load_balancer_source_ranges', None)))
        _append_if(fields, 'Traffic Distribution', str(getattr(spec, 'traffic_distribution', None) or ''))
        _append_if(fields, 'Selector', _selector_text(spec))
        _append_if(fields, 'Ports', _service_ports(spec))
    elif kind == ENDPOINTS:
        subsets = getattr(obj, 'subsets', None) or []
        if not subsets:
            fields.append(('Subsets', '(none)'))
        else:
            for index, subset in enumerate(subsets, start=1):
                prefix = f'Subset {index}' if len(subsets) > 1 else 'Subset'
                _append_if(fields, f'{prefix} Addresses', _subset_address_lines(subset))
                _append_if(fields, f'{prefix} Ports', _subset_port_lines(subset))
                not_ready = getattr(subset, 'not_ready_addresses', None) or []
                if not_ready:
                    ips = _join(getattr(address, 'ip', None) for address in not_ready)
                    _append_if(fields, f'{prefix} Not Ready', ips)
    elif kind == ENDPOINT_SLICE:
        _append_if(fields, 'Address Type', str(getattr(obj, 'address_type', None) or ''))
        _append_if(fields, 'Endpoints', _slice_endpoint_lines(obj))
        _append_if(fields, 'Ports', _named_ports(getattr(obj, 'ports', None)))
    elif kind == INGRESS:
        _append_if(fields, 'Address', _ingress_address(obj))
        fields.append(('Default Backend', _ingress_default_backend(spec)))
        _append_if(fields, 'Ports', _ingress_ports(spec))
        _append_if(fields, 'TLS', _ingress_tls(spec))
        _append_if(fields, 'Class Name', str(getattr(spec, 'ingress_class_name', None) or ''))
        _append_if(fields, 'Rules', _ingress_rules(spec))
    return tuple(fields)
