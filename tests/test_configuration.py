import asyncio
from datetime import datetime, timezone

from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static, TextArea

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.apply import AppliedObject
from roomlamp.k8s.configuration import CONFIG_MAP, SECRET, ConfigurationDetail, ConfigurationSummary, is_namespaced
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.ui.screens.configuration import (
    ConfigurationDetailScreen,
    ConfigurationListScreen,
    sort_configuration,
)
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)

SECRET_PLAIN = 'secret-value'


def _summary(
    kind: str,
    name: str,
    namespace: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> ConfigurationSummary:
    return ConfigurationSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
    )


class FakeCluster:
    def __init__(self) -> None:
        self.configuration = {
            CONFIG_MAP: [
                _summary(
                    CONFIG_MAP,
                    'app-config',
                    'default',
                    ('default', 'app-config', '2', '1d'),
                    ('default', 'app-config', 2, 1.0),
                ),
                _summary(
                    CONFIG_MAP,
                    'coredns',
                    'kube-system',
                    ('kube-system', 'coredns', '1', '2d'),
                    ('kube-system', 'coredns', 1, 2.0),
                ),
            ],
            SECRET: [
                _summary(
                    SECRET,
                    'db',
                    'default',
                    ('default', 'db', 'Opaque', '1', '1d'),
                    ('default', 'db', 'Opaque', 1, 1.0),
                ),
            ],
        }
        self.labels: dict[tuple[str, str, str], tuple[tuple[str, str], ...]] = {}

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_configuration(self, kind: str, namespace: str) -> list[ConfigurationSummary]:
        items: list[ConfigurationSummary] = []
        for item in self.configuration.get(kind, []):
            if is_namespaced(kind) and namespace != ALL_NAMESPACES and item.namespace != namespace:
                continue
            items.append(item)
        return items

    def get_configuration(self, kind: str, namespace: str, name: str) -> ConfigurationDetail:
        if kind == CONFIG_MAP:
            fields: tuple[tuple[str, str], ...] = (('Data app', 'web'), ('Binary Data', '(none)'))
        else:
            fields = (('Type', 'Opaque'), ('Data password', '12 bytes'))
        return ConfigurationDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=self.labels.get((kind, namespace, name), (('app', name),)),
            fields=fields,
        )

    def get_configuration_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        ns = f'  namespace: {namespace}\n' if namespace else ''
        return f'apiVersion: v1\nkind: {kind}\nmetadata:\n  name: {name}\n{ns}'

    def apply_yaml(self, text: str, dry_run: bool = False, default_namespace: str = 'default'):
        if not dry_run:
            self.labels[(CONFIG_MAP, 'default', 'app-config')] = (('app', 'saved'),)
        return [AppliedObject(CONFIG_MAP, 'app-config', 'default', dry_run)]


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


def test_config_map_list_filters_by_namespace() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, CONFIG_MAP)
            screen = app.screen
            assert isinstance(screen, ConfigurationListScreen)
            table = screen.query_one('#configuration', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'app-config' in row
            assert 'coredns' not in row
            assert 'pick_namespace' in enabled_actions(screen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_config_map_detail_and_yaml() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, CONFIG_MAP)
            screen = app.screen
            assert isinstance(screen, ConfigurationListScreen)
            await screen._open_detail('default/app-config')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, ConfigurationDetailScreen)
            text = str(detail.query_one('#configuration-detail', Static).content)
            assert 'ConfigMap' in text
            assert 'app-config' in text
            assert 'web' in text
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: ConfigMap' in yaml_text
            assert 'name: app-config' in yaml_text
            assert 'refresh' in enabled_actions(detail)

    asyncio.run(_run())


def test_config_map_detail_scrolls_long_text() -> None:
    class TallCluster(FakeCluster):
        def get_configuration(self, kind: str, namespace: str, name: str) -> ConfigurationDetail:
            fields = tuple((f'Data k{index:02d}', f'value {index}') for index in range(40))
            return ConfigurationDetail(
                kind=kind,
                name=name,
                namespace=namespace,
                uid='uid-1',
                created='2026-01-02T00:00:00+00:00',
                labels=(),
                fields=fields,
            )

    app = RoomlampApp(_info(), cluster=TallCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await open_kind(app, pilot, CONFIG_MAP)
            screen = app.screen
            assert isinstance(screen, ConfigurationListScreen)
            await screen._open_detail('default/app-config')
            await pilot.pause()
            wrap = app.screen.query_one('#configuration-detail-wrap', VerticalScroll)
            assert wrap.max_scroll_y > 0
            wrap.scroll_end(animate=False)
            await pilot.pause()
            assert wrap.scroll_offset.y == wrap.max_scroll_y
            text = str(app.screen.query_one('#configuration-detail', Static).content)
            assert 'Data k39' in text

    asyncio.run(_run())


def test_secret_list_keeps_namespace_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SECRET)
            screen = app.screen
            assert isinstance(screen, ConfigurationListScreen)
            table = screen.query_one('#configuration', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'db' in row
            assert 'Opaque' in row
            assert 'pick_namespace' in enabled_actions(screen)

    asyncio.run(_run())


def test_secret_detail_hides_values_and_opens_menu() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SECRET)
            screen = app.screen
            assert isinstance(screen, ConfigurationListScreen)
            await screen._open_detail('default/db')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, ConfigurationDetailScreen)
            text = str(detail.query_one('#configuration-detail', Static).content)
            assert 'Secret' in text
            assert 'Opaque' in text
            assert '12 bytes' in text
            assert SECRET_PLAIN not in text
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_configuration_detail_refresh_and_yaml_apply_reloads() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, CONFIG_MAP)
            screen = app.screen
            assert isinstance(screen, ConfigurationListScreen)
            await screen._open_detail('default/app-config')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, ConfigurationDetailScreen)
            text = str(detail.query_one('#configuration-detail', Static).content)
            assert 'app=app-config' in text
            cluster.labels[(CONFIG_MAP, 'default', 'app-config')] = (('app', 'refreshed'),)
            await detail.action_refresh()
            await pilot.pause()
            text = str(detail.query_one('#configuration-detail', Static).content)
            assert 'app=refreshed' in text
            await detail.action_show_yaml()
            await pilot.pause()
            yaml_screen = app.screen
            assert isinstance(yaml_screen, YamlViewScreen)
            yaml_screen.query_one('#yaml-view', TextArea).load_text(
                yaml_screen.query_one('#yaml-view', TextArea).text + '  labels:\n    app: saved\n'
            )
            await yaml_screen.action_apply()
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, ConfigurationDetailScreen)
            text = str(detail.query_one('#configuration-detail', Static).content)
            assert 'app=saved' in text

    asyncio.run(_run())


def test_sort_configuration_by_column() -> None:
    items = [
        _summary(
            CONFIG_MAP,
            'app-config',
            'default',
            ('default', 'app-config', '2', '1d'),
            ('default', 'app-config', 2, 1.0),
        ),
        _summary(
            CONFIG_MAP,
            'api',
            'default',
            ('default', 'api', '0', '2d'),
            ('default', 'api', 0, 2.0),
        ),
    ]
    by_name = [item.name for item in sort_configuration(items, 1, True)]
    assert by_name == ['api', 'app-config']
    by_data = [item.cells[2] for item in sort_configuration(items, 2, True)]
    assert by_data == ['0', '2']
