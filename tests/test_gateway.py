import asyncio
from datetime import datetime, timezone

from textual.widgets import DataTable, OptionList, Static, TextArea

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.gateway import (
    GATEWAY,
    GATEWAY_CLASS,
    HTTP_ROUTE,
    GatewayDetail,
    GatewaySummary,
    is_namespaced,
)
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.ui.nav import groups_for
from roomlamp.ui.screens.gateway import GatewayDetailScreen, GatewayListScreen, sort_gateway
from roomlamp.ui.screens.kinds import KindPickerScreen
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _summary(
    kind: str,
    name: str,
    namespace: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> GatewaySummary:
    return GatewaySummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
    )


class FakeCluster:
    def __init__(self, *, kinds: tuple[str, ...] = (GATEWAY, GATEWAY_CLASS, HTTP_ROUTE)) -> None:
        self._kinds = kinds
        self.gateway = {
            GATEWAY: [
                _summary(
                    GATEWAY,
                    'web',
                    'default',
                    ('default', 'web', 'nginx', '192.0.2.10', '1', 'Accepted', '1d'),
                    ('default', 'web', 'nginx', '192.0.2.10', 1, 'Accepted', 1.0),
                ),
                _summary(
                    GATEWAY,
                    'edge',
                    'kube-system',
                    ('kube-system', 'edge', 'nginx', '', '1', '', '2d'),
                    ('kube-system', 'edge', 'nginx', '', 1, '', 2.0),
                ),
            ],
            GATEWAY_CLASS: [
                _summary(
                    GATEWAY_CLASS,
                    'nginx',
                    '',
                    ('nginx', 'gateway.nginx.org/nginx-gateway-fabric', 'Accepted', '1d'),
                    ('nginx', 'gateway.nginx.org/nginx-gateway-fabric', 'Accepted', 1.0),
                ),
            ],
            HTTP_ROUTE: [
                _summary(
                    HTTP_ROUTE,
                    'www',
                    'default',
                    ('default', 'www', 'example.com', 'Gateway/web', '1', '1d'),
                    ('default', 'www', 'example.com', 'Gateway/web', 1, 1.0),
                ),
            ],
        }

    def available_gateway_kinds(self) -> tuple[str, ...]:
        return self._kinds

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_gateway(self, kind: str, namespace: str) -> list[GatewaySummary]:
        items = list(self.gateway.get(kind, []))
        if not is_namespaced(kind) or namespace == ALL_NAMESPACES:
            return items
        return [item for item in items if item.namespace == namespace]

    def get_gateway(self, kind: str, namespace: str, name: str) -> GatewayDetail:
        return GatewayDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=(('app', name),),
            fields=(('Class Name', 'nginx'),),
        )

    def get_gateway_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        ns = f'  namespace: {namespace}\n' if namespace else ''
        return f'apiVersion: gateway.networking.k8s.io/v1\nkind: {kind}\nmetadata:\n  name: {name}\n{ns}'


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


def test_groups_for_hides_gateway_when_api_is_empty() -> None:
    cluster = FakeCluster(kinds=())
    groups = groups_for(cluster)
    gateway = next(group for group in groups if group.id == 'gateway')
    assert gateway.implemented is False


def test_groups_for_lists_served_kinds_only() -> None:
    cluster = FakeCluster(kinds=(GATEWAY, HTTP_ROUTE))
    groups = groups_for(cluster)
    gateway = next(group for group in groups if group.id == 'gateway')
    assert [item.kind for item in gateway.kinds] == [GATEWAY, HTTP_ROUTE]


def test_gateway_list_filters_by_namespace() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, GATEWAY)
            screen = app.screen
            assert isinstance(screen, GatewayListScreen)
            table = screen.query_one('#gateway', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'web' in row
            assert 'edge' not in row
            assert 'pick_namespace' in enabled_actions(screen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_gateway_detail_and_yaml() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, GATEWAY)
            screen = app.screen
            assert isinstance(screen, GatewayListScreen)
            await screen._open_detail('default/web')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, GatewayDetailScreen)
            text = str(detail.query_one('#gateway-detail', Static).content)
            assert 'Gateway' in text
            assert 'web' in text
            assert 'nginx' in text
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: Gateway' in yaml_text
            assert 'name: web' in yaml_text

    asyncio.run(_run())


def test_gateway_class_hides_namespace_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, GATEWAY_CLASS)
            screen = app.screen
            assert isinstance(screen, GatewayListScreen)
            table = screen.query_one('#gateway', DataTable)
            assert 'nginx' in table.get_row_at(0)
            assert 'pick_namespace' not in enabled_actions(screen)
            await screen._open_detail('nginx')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, GatewayDetailScreen)
            text = str(detail.query_one('#gateway-detail', Static).content)
            assert 'GatewayClass' in text
            assert 'Namespace' not in text

    asyncio.run(_run())


def test_http_route_list_and_menu_key() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, HTTP_ROUTE)
            screen = app.screen
            assert isinstance(screen, GatewayListScreen)
            table = screen.query_one('#gateway', DataTable)
            assert 'www' in table.get_row_at(0)
            assert 'example.com' in table.get_row_at(0)
            assert 'pick_namespace' in enabled_actions(screen)
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_menu_gateway_opens_served_kinds() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 4
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            labels = [str(kind_list.get_option_at_index(i).prompt) for i in range(kind_list.option_count)]
            assert labels == ['Gateways', 'Gateway Classes', 'HTTP Routes', 'Back']
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, GatewayListScreen)
            assert screen.kind == GATEWAY
            assert 'pick_namespace' in enabled_actions(screen)

    asyncio.run(_run())


def test_menu_gateway_stays_empty_without_crds() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(kinds=()), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 4
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_sort_gateway_by_column() -> None:
    items = [
        _summary(
            GATEWAY,
            'web',
            'default',
            ('default', 'web', 'nginx', '192.0.2.10', '1', 'Accepted', '1d'),
            ('default', 'web', 'nginx', '192.0.2.10', 1, 'Accepted', 1.0),
        ),
        _summary(
            GATEWAY,
            'api',
            'default',
            ('default', 'api', 'istio', '', '2', '', '2d'),
            ('default', 'api', 'istio', '', 2, '', 2.0),
        ),
    ]
    by_name = [item.name for item in sort_gateway(items, 1, True)]
    assert by_name == ['api', 'web']
    by_class = [item.cells[2] for item in sort_gateway(items, 2, True)]
    assert by_class == ['istio', 'nginx']
