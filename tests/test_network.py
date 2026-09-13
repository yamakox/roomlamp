import asyncio
from datetime import datetime, timezone

from textual.widgets import DataTable, Static, TextArea

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.network import (
    ENDPOINT_SLICE,
    ENDPOINTS,
    INGRESS,
    SERVICE,
    NetworkDetail,
    NetworkSummary,
    is_namespaced,
)
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.network import NetworkDetailScreen, NetworkListScreen, sort_network
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _summary(
    kind: str,
    name: str,
    namespace: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> NetworkSummary:
    return NetworkSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
    )


class FakeCluster:
    def __init__(self) -> None:
        self.network = {
            SERVICE: [
                _summary(
                    SERVICE,
                    'web',
                    'default',
                    ('default', 'web', 'ClusterIP', '10.96.0.10', '', '80/TCP', 'app=web', '1d'),
                    ('default', 'web', 'ClusterIP', '10.96.0.10', '', '80/TCP', 'app=web', 1.0),
                ),
                _summary(
                    SERVICE,
                    'dns',
                    'kube-system',
                    ('kube-system', 'dns', 'ClusterIP', '10.96.0.10', '', '53/UDP', '', '2d'),
                    ('kube-system', 'dns', 'ClusterIP', '10.96.0.10', '', '53/UDP', '', 2.0),
                ),
            ],
            ENDPOINTS: [
                _summary(
                    ENDPOINTS,
                    'web',
                    'default',
                    ('default', 'web', '10.1.0.5:80', '1d'),
                    ('default', 'web', '10.1.0.5:80', 1.0),
                ),
            ],
            ENDPOINT_SLICE: [
                _summary(
                    ENDPOINT_SLICE,
                    'web-abc',
                    'default',
                    ('default', 'web-abc', '10.1.0.5', '80', 'IPv4', '1d'),
                    ('default', 'web-abc', '10.1.0.5', '80', 'IPv4', 1.0),
                ),
            ],
            INGRESS: [
                _summary(
                    INGRESS,
                    'www',
                    'default',
                    ('default', 'www', 'nginx', 'example.com', '192.0.2.10', '80, 443', '1d'),
                    ('default', 'www', 'nginx', 'example.com', '192.0.2.10', '80, 443', 1.0),
                ),
            ],
        }

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_network(self, kind: str, namespace: str) -> list[NetworkSummary]:
        items = list(self.network.get(kind, []))
        if not is_namespaced(kind) or namespace == ALL_NAMESPACES:
            return items
        return [item for item in items if item.namespace == namespace]

    def get_network(self, kind: str, namespace: str, name: str) -> NetworkDetail:
        return NetworkDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=(('app', name),),
            fields=(('Type', 'ClusterIP'), ('Cluster IP', '10.96.0.10')),
        )

    def get_network_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        ns = f'  namespace: {namespace}\n' if namespace else ''
        version = NETWORK_VERSIONS[kind]
        return f'apiVersion: {version}\nkind: {kind}\nmetadata:\n  name: {name}\n{ns}'


NETWORK_VERSIONS = {
    SERVICE: 'v1',
    ENDPOINTS: 'v1',
    ENDPOINT_SLICE: 'discovery.k8s.io/v1',
    INGRESS: 'networking.k8s.io/v1',
}


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


def enabled_actions(screen) -> set[str]:
    return {info.binding.action for info in screen.active_bindings.values() if info.enabled}


def test_service_list_filters_by_namespace() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SERVICE)
            screen = app.screen
            assert isinstance(screen, NetworkListScreen)
            table = screen.query_one('#network', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'web' in row
            assert 'dns' not in row
            assert 'pick_namespace' in enabled_actions(screen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_service_detail_and_yaml() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SERVICE)
            screen = app.screen
            assert isinstance(screen, NetworkListScreen)
            await screen._open_detail('default/web')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, NetworkDetailScreen)
            text = str(detail.query_one('#network-detail', Static).content)
            assert 'Service' in text
            assert 'web' in text
            assert 'ClusterIP' in text
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: Service' in yaml_text
            assert 'name: web' in yaml_text

    asyncio.run(_run())


def test_endpoints_and_slices_keep_namespace_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, ENDPOINTS)
            screen = app.screen
            assert isinstance(screen, NetworkListScreen)
            table = screen.query_one('#network', DataTable)
            assert 'web' in table.get_row_at(0)
            assert '10.1.0.5:80' in table.get_row_at(0)
            assert 'pick_namespace' in enabled_actions(screen)
            await open_kind(app, pilot, ENDPOINT_SLICE)
            slice_screen = app.screen
            assert isinstance(slice_screen, NetworkListScreen)
            slice_table = slice_screen.query_one('#network', DataTable)
            assert 'web-abc' in slice_table.get_row_at(0)
            assert 'IPv4' in slice_table.get_row_at(0)
            assert 'pick_namespace' in enabled_actions(slice_screen)

    asyncio.run(_run())


def test_ingress_list_and_menu_key() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, INGRESS)
            screen = app.screen
            assert isinstance(screen, NetworkListScreen)
            table = screen.query_one('#network', DataTable)
            assert 'www' in table.get_row_at(0)
            assert 'nginx' in table.get_row_at(0)
            await screen._open_detail('default/www')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, NetworkDetailScreen)
            text = str(detail.query_one('#network-detail', Static).content)
            assert 'Ingress' in text
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_sort_network_by_column() -> None:
    items = [
        _summary(
            SERVICE,
            'web',
            'default',
            ('default', 'web', 'ClusterIP', '10.96.0.10', '', '80/TCP', 'app=web', '1d'),
            ('default', 'web', 'ClusterIP', '10.96.0.10', '', '80/TCP', 'app=web', 1.0),
        ),
        _summary(
            SERVICE,
            'api',
            'default',
            ('default', 'api', 'NodePort', '10.96.0.11', '', '80:30080/TCP', 'app=api', '2d'),
            ('default', 'api', 'NodePort', '10.96.0.11', '', '80:30080/TCP', 'app=api', 2.0),
        ),
    ]
    by_name = [item.name for item in sort_network(items, 1, True)]
    assert by_name == ['api', 'web']
    by_type = [item.cells[2] for item in sort_network(items, 2, True)]
    assert by_type == ['ClusterIP', 'NodePort']
