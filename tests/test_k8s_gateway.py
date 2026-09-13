from datetime import datetime, timezone

from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.gateway import (
    GATEWAY,
    GATEWAY_CLASS,
    GATEWAY_GROUP,
    GATEWAY_SPECS,
    HTTP_ROUTE,
    ApiGatewayReader,
    detail_gateway,
    discover_gateway_kinds,
    is_namespaced,
    split_gateway_key,
    summarize_gateway,
)
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.k8s.watch import apply_watch_event

CREATED = '2026-01-02T00:00:00Z'
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _gateway() -> dict[str, object]:
    return {
        'apiVersion': 'gateway.networking.k8s.io/v1',
        'kind': 'Gateway',
        'metadata': {
            'name': 'web',
            'namespace': 'default',
            'uid': 'uid-1',
            'creationTimestamp': CREATED,
            'labels': {'app': 'web'},
        },
        'spec': {
            'gatewayClassName': 'nginx',
            'listeners': [
                {'name': 'http', 'protocol': 'HTTP', 'port': 80, 'hostname': 'example.com'},
            ],
        },
        'status': {
            'addresses': [{'type': 'IPAddress', 'value': '192.0.2.10'}],
            'listeners': [
                {
                    'name': 'http',
                    'attachedRoutes': 2,
                    'conditions': [{'type': 'Programmed', 'status': 'True', 'reason': 'Ready'}],
                }
            ],
            'conditions': [
                {'type': 'Accepted', 'status': 'True', 'reason': 'Accepted'},
                {'type': 'Programmed', 'status': 'True', 'reason': 'Ready'},
            ],
        },
    }


def _gateway_class() -> dict[str, object]:
    return {
        'apiVersion': 'gateway.networking.k8s.io/v1',
        'kind': 'GatewayClass',
        'metadata': {
            'name': 'nginx',
            'uid': 'uid-2',
            'creationTimestamp': CREATED,
        },
        'spec': {'controllerName': 'gateway.nginx.org/nginx-gateway-fabric'},
        'status': {
            'conditions': [{'type': 'Accepted', 'status': 'True', 'reason': 'Accepted'}],
        },
    }


def _http_route() -> dict[str, object]:
    return {
        'apiVersion': 'gateway.networking.k8s.io/v1',
        'kind': 'HTTPRoute',
        'metadata': {
            'name': 'www',
            'namespace': 'default',
            'uid': 'uid-3',
            'creationTimestamp': CREATED,
            'labels': {'app': 'www'},
        },
        'spec': {
            'hostnames': ['example.com', ''],
            'parentRefs': [{'kind': 'Gateway', 'name': 'web', 'namespace': 'nginx-gateway'}],
            'rules': [
                {
                    'name': 'api',
                    'matches': [{'method': 'GET', 'path': {'type': 'PathPrefix', 'value': '/api'}}],
                    'backendRefs': [{'kind': 'Service', 'name': 'web', 'port': 80, 'weight': 1}],
                    'filters': [{'type': 'RequestHeaderModifier'}],
                }
            ],
        },
    }


class FakeDiscoveryClient:
    def __init__(
        self,
        versions: dict[str, object] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.versions = versions or {}
        self.errors = errors or {}
        self.paths: list[str] = []

    def call_api(self, path: str, method: str, **kwargs: object) -> object:
        self.paths.append(path)
        version = path.rsplit('/', 1)[-1]
        if version in self.errors:
            raise self.errors[version]
        return self.versions.get(version, {'resources': []})


class FakeCustomApi:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def _items_for(self, plural: str, namespace: str | None = None) -> list[dict[str, object]]:
        kind = {
            'gateways': GATEWAY,
            'gatewayclasses': GATEWAY_CLASS,
            'httproutes': HTTP_ROUTE,
        }[plural]
        items = [item for item in self.items if item.get('kind') == kind]
        if namespace is not None:
            items = [item for item in items if (item.get('metadata') or {}).get('namespace') == namespace]
        return items

    def list_cluster_custom_object(self, group: str, version: str, plural: str) -> dict[str, object]:
        self.calls.append(('cluster', (group, version, plural)))
        return {'items': self._items_for(plural)}

    def list_custom_object_for_all_namespaces(
        self, group: str, version: str, resource_plural: str
    ) -> dict[str, object]:
        self.calls.append(('all', (group, version, resource_plural)))
        return {'items': self._items_for(resource_plural)}

    def list_namespaced_custom_object(self, group: str, version: str, namespace: str, plural: str) -> dict[str, object]:
        self.calls.append(('namespaced', (group, version, namespace, plural)))
        return {'items': self._items_for(plural, namespace)}

    def get_namespaced_custom_object(
        self, group: str, version: str, namespace: str, plural: str, name: str
    ) -> dict[str, object]:
        for item in self.items:
            meta = item.get('metadata') or {}
            if meta.get('namespace') == namespace and meta.get('name') == name:
                return item
        raise AssertionError('missing object')

    def get_cluster_custom_object(self, group: str, version: str, plural: str, name: str) -> dict[str, object]:
        for item in self.items:
            meta = item.get('metadata') or {}
            if meta.get('name') == name:
                return item
        raise AssertionError('missing object')


def _v1_resources() -> dict[str, object]:
    return {
        'resources': [
            {'kind': 'Gateway', 'name': 'gateways', 'verbs': ['list', 'get', 'watch']},
            {'kind': 'Gateway', 'name': 'gateways/status', 'verbs': ['get', 'update']},
            {'kind': 'GatewayClass', 'name': 'gatewayclasses', 'verbs': ['list', 'get']},
            {'kind': 'HTTPRoute', 'name': 'httproutes', 'verbs': ['list', 'get']},
            {'kind': 'GRPCRoute', 'name': 'grpcroutes', 'verbs': ['list', 'get']},
            {'kind': 'TCPRoute', 'name': 'tcproutes', 'verbs': ['list']},
        ]
    }


def test_summarize_gateway_matches_headlamp() -> None:
    summary = summarize_gateway(GATEWAY, _gateway(), now=NOW)
    assert summary.key == 'default/web'
    assert summary.cells == (
        'default',
        'web',
        'nginx',
        '192.0.2.10',
        '1',
        'Accepted, Programmed',
        '1d',
    )
    detail = detail_gateway(GATEWAY, _gateway(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Class Name'] == 'nginx'
    assert fields['Addresses'] == 'IPAddress=192.0.2.10'
    assert 'http HTTP:80 example.com routes=2 Programmed' in fields['Listeners']
    assert 'Accepted=True (Accepted)' in fields['Conditions']
    assert detail.labels == (('app', 'web'),)
    assert detail.namespace == 'default'


def test_summarize_gateway_class_is_cluster_scoped() -> None:
    summary = summarize_gateway(GATEWAY_CLASS, _gateway_class(), now=NOW)
    assert summary.key == 'nginx'
    assert summary.cells == ('nginx', 'gateway.nginx.org/nginx-gateway-fabric', 'Accepted', '1d')
    assert is_namespaced(GATEWAY_CLASS) is False
    assert split_gateway_key(GATEWAY_CLASS, 'nginx') == ('', 'nginx')
    detail = detail_gateway(GATEWAY_CLASS, _gateway_class(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Controller Name'] == 'gateway.nginx.org/nginx-gateway-fabric'
    assert detail.namespace == ''


def test_summarize_http_route_rules_and_parents() -> None:
    summary = summarize_gateway(HTTP_ROUTE, _http_route(), now=NOW)
    assert summary.key == 'default/www'
    assert summary.cells == (
        'default',
        'www',
        'example.com, *',
        'Gateway/nginx-gateway/web',
        '1',
        '1d',
    )
    detail = detail_gateway(HTTP_ROUTE, _http_route(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Hostnames'] == 'example.com, *'
    assert fields['Parent Refs'] == 'Gateway/nginx-gateway/web'
    assert 'GET PathPrefix /api' in fields['Rules']
    assert 'Service/web:80 w=1' in fields['Rules']
    assert 'RequestHeaderModifier' in fields['Rules']


def test_gateway_specs_and_unknown_kind() -> None:
    assert GATEWAY_SPECS[GATEWAY].api_version == 'gateway.networking.k8s.io/v1'
    assert GATEWAY_SPECS[GATEWAY_CLASS].resource == 'gatewayclasses'
    assert GATEWAY_SPECS[HTTP_ROUTE].namespaced is True
    try:
        summarize_gateway('GRPCRoute', {})
    except ValueError as exc:
        assert 'Unknown gateway kind' in str(exc)
    else:
        raise AssertionError('expected unknown kind to fail')


def test_discover_gateway_kinds_prefers_v1_and_hides_low() -> None:
    client = FakeDiscoveryClient({'v1': _v1_resources(), 'v1beta1': {'resources': []}})
    found = discover_gateway_kinds(client)
    assert found == {
        GATEWAY: 'v1',
        GATEWAY_CLASS: 'v1',
        HTTP_ROUTE: 'v1',
    }
    assert client.paths == [
        f'/apis/{GATEWAY_GROUP}/v1',
        f'/apis/{GATEWAY_GROUP}/v1beta1',
    ]


def test_discover_gateway_kinds_falls_back_to_v1beta1() -> None:
    client = FakeDiscoveryClient(
        {'v1beta1': {'resources': [{'kind': 'Gateway', 'name': 'gateways', 'verbs': ['list']}]}},
        errors={'v1': ApiException(status=404, reason='Not Found')},
    )
    found = discover_gateway_kinds(client)
    assert found == {GATEWAY: 'v1beta1'}


def test_discover_gateway_kinds_empty_on_missing_group() -> None:
    client = FakeDiscoveryClient(
        errors={
            'v1': ApiException(status=404, reason='Not Found'),
            'v1beta1': ApiException(status=404, reason='Not Found'),
        }
    )
    assert discover_gateway_kinds(client) == {}


def test_api_gateway_reader_lists_and_dumps(monkeypatch) -> None:
    fake = FakeCustomApi([_gateway(), _gateway_class(), _http_route()])
    monkeypatch.setattr('roomlamp.k8s.gateway.CustomObjectsApi', lambda _client: fake)
    reader = ApiGatewayReader(FakeDiscoveryClient({'v1': _v1_resources()}))
    assert reader.available_gateway_kinds() == (GATEWAY, GATEWAY_CLASS, HTTP_ROUTE)
    namespaced = reader.list_gateway(GATEWAY, 'default')
    assert [item.name for item in namespaced] == ['web']
    all_ns = reader.list_gateway(GATEWAY, ALL_NAMESPACES)
    assert fake.calls[-1][0] == 'all'
    assert [item.name for item in all_ns] == ['web']
    classes = reader.list_gateway(GATEWAY_CLASS, ALL_NAMESPACES)
    assert [item.name for item in classes] == ['nginx']
    detail = reader.get_gateway(GATEWAY, 'default', 'web')
    assert detail.name == 'web'
    text = reader.get_gateway_yaml(GATEWAY, 'default', 'web')
    assert 'kind: Gateway' in text
    assert 'gatewayClassName: nginx' in text
    dumped = dump_resource(_gateway(), kind=GATEWAY, api_version='gateway.networking.k8s.io/v1')
    assert 'managedFields' not in dumped


def test_apply_watch_event_gateway() -> None:
    item = summarize_gateway(GATEWAY, _gateway(), now=NOW)
    updated = apply_watch_event({}, 'ADDED', item)
    assert updated[item.key] == item
    gone = apply_watch_event(updated, 'DELETED', item)
    assert gone == {}
