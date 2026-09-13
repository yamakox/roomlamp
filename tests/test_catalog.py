import asyncio
from datetime import datetime, timezone

from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input, Static, TextArea

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.apply import AppliedObject
from roomlamp.k8s.catalog import NAMESPACE, NODE, CatalogDetail, CatalogSummary, is_namespaced
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.delete import ACTION_DELETE, DeletedObject
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.ui.screens.catalog import CatalogDetailScreen, CatalogListScreen, sort_catalog
from roomlamp.ui.screens.delete import DeleteConfirmScreen
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _summary(
    kind: str,
    name: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
    confirm_name: str | None = None,
) -> CatalogSummary:
    return CatalogSummary(
        kind=kind,
        name=name,
        namespace='',
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
        confirm_name=confirm_name,
    )


class FakeCluster:
    def __init__(self) -> None:
        self.catalog = {
            NAMESPACE: [
                _summary(NAMESPACE, 'apps', ('apps', 'Active', '1d'), ('apps', 'Active', 1.0)),
                _summary(
                    NAMESPACE,
                    'kube-system',
                    ('kube-system', 'Active', '2d'),
                    ('kube-system', 'Active', 2.0),
                    confirm_name='kube-system',
                ),
            ],
            NODE: [
                _summary(
                    NODE,
                    'node-a',
                    ('node-a', 'Yes', '', 'control-plane', '10.0.0.1', '', 'v1.34.0', '1d'),
                    ('node-a', True, '', 'control-plane', '10.0.0.1', '', 'v1.34.0', 1.0),
                ),
            ],
        }
        self.labels: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}
        self.deleted: list[tuple[str, str, str | None, bool]] = []

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_catalog(self, kind: str, namespace: str) -> list[CatalogSummary]:
        items: list[CatalogSummary] = []
        for item in self.catalog.get(kind, []):
            if is_namespaced(kind) and namespace != ALL_NAMESPACES and item.namespace != namespace:
                continue
            items.append(item)
        return items

    def get_catalog(self, kind: str, namespace: str, name: str) -> CatalogDetail:
        if kind == NAMESPACE:
            fields: tuple[tuple[str, str], ...] = (('Status', 'Active'),)
            confirm = 'kube-system' if name == 'kube-system' else None
        else:
            fields = (
                ('Roles', 'control-plane'),
                ('Taints', '(none)'),
                ('Ready', 'Yes'),
                ('Conditions', 'Scheduling Enabled'),
                ('InternalIP', '10.0.0.1'),
                ('Kubelet Version', 'v1.34.0'),
            )
            confirm = None
        return CatalogDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=self.labels.get((kind, name), (('kubernetes.io/metadata.name', name),)),
            fields=fields,
            confirm_name=confirm,
        )

    def get_catalog_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        return f'apiVersion: v1\nkind: {kind}\nmetadata:\n  name: {name}\n'

    def apply_yaml(self, text: str, dry_run: bool = False, default_namespace: str = 'default'):
        if not dry_run:
            self.labels[(NODE, 'node-a')] = (('kubernetes.io/hostname', 'saved'),)
        return [AppliedObject(NODE, 'node-a', None, dry_run)]

    def delete_resource(
        self, kind: str, name: str, *, namespace: str | None = None, force: bool = False
    ) -> DeletedObject:
        self.deleted.append((kind, name, namespace, force))
        self.catalog[kind] = [item for item in self.catalog.get(kind, []) if item.name != name]
        return DeletedObject(kind=kind, name=name, namespace=namespace, force=force, action=ACTION_DELETE)


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


def test_namespace_list_hides_namespace_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, NAMESPACE)
            screen = app.screen
            assert isinstance(screen, CatalogListScreen)
            table = screen.query_one('#catalog', DataTable)
            assert table.row_count == 2
            names = [str(table.get_row_at(index)[0]) for index in range(table.row_count)]
            assert names == ['apps', 'kube-system']
            assert 'pick_namespace' not in enabled_actions(screen)
            assert screen.sub_title == 'test-context / Namespaces'

    asyncio.run(_run())


def test_namespace_detail_yaml_and_menu() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, NAMESPACE)
            screen = app.screen
            assert isinstance(screen, CatalogListScreen)
            await screen._open_detail('apps')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, CatalogDetailScreen)
            text = str(detail.query_one('#catalog-detail', Static).content)
            assert 'Namespace' in text
            assert 'apps' in text
            assert 'Active' in text
            assert 'refresh' in enabled_actions(detail)
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: Namespace' in yaml_text
            assert 'name: apps' in yaml_text
            await pilot.press('escape')
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_node_list_detail_and_yaml_apply_reloads() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, NODE)
            screen = app.screen
            assert isinstance(screen, CatalogListScreen)
            table = screen.query_one('#catalog', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'node-a' in row
            assert 'Yes' in row
            assert 'pick_namespace' not in enabled_actions(screen)
            await screen._open_detail('node-a')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, CatalogDetailScreen)
            text = str(detail.query_one('#catalog-detail', Static).content)
            assert 'Node' in text
            assert 'control-plane' in text
            assert 'Scheduling Enabled' in text
            cluster.labels[(NODE, 'node-a')] = (('kubernetes.io/hostname', 'refreshed'),)
            await detail.action_refresh()
            await pilot.pause()
            text = str(detail.query_one('#catalog-detail', Static).content)
            assert 'kubernetes.io/hostname=refreshed' in text
            await detail.action_show_yaml()
            await pilot.pause()
            yaml_screen = app.screen
            assert isinstance(yaml_screen, YamlViewScreen)
            yaml_screen.query_one('#yaml-view', TextArea).load_text(
                yaml_screen.query_one('#yaml-view', TextArea).text + 'spec:\n  unschedulable: true\n'
            )
            await yaml_screen.action_apply()
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, CatalogDetailScreen)
            text = str(detail.query_one('#catalog-detail', Static).content)
            assert 'kubernetes.io/hostname=saved' in text

    asyncio.run(_run())


def test_catalog_detail_scrolls_long_text() -> None:
    class TallCluster(FakeCluster):
        def get_catalog(self, kind: str, namespace: str, name: str) -> CatalogDetail:
            fields = tuple((f'Capacity extra-{index:02d}', str(index)) for index in range(40))
            return CatalogDetail(
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
            await open_kind(app, pilot, NODE)
            screen = app.screen
            assert isinstance(screen, CatalogListScreen)
            await screen._open_detail('node-a')
            await pilot.pause()
            wrap = app.screen.query_one('#catalog-detail-wrap', VerticalScroll)
            assert wrap.max_scroll_y > 0
            wrap.scroll_end(animate=False)
            await pilot.pause()
            assert wrap.scroll_offset.y == wrap.max_scroll_y
            text = str(app.screen.query_one('#catalog-detail', Static).content)
            assert 'Capacity extra-39' in text

    asyncio.run(_run())


def test_protected_namespace_delete_requires_typed_name() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, NAMESPACE)
            screen = app.screen
            assert isinstance(screen, CatalogListScreen)
            await screen._open_detail('kube-system')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, CatalogDetailScreen)
            detail.action_delete()
            await pilot.pause()
            confirm = app.screen
            assert isinstance(confirm, DeleteConfirmScreen)
            assert confirm.require_typed_name == 'kube-system'
            warning = str(confirm.query_one('#delete-warning').content)
            assert 'system namespace' in warning
            await pilot.press('enter')
            await pilot.pause()
            assert cluster.deleted == []
            assert isinstance(app.screen, DeleteConfirmScreen)
            app.screen.query_one('#delete-confirm-input', Input).value = 'kube-system'
            await pilot.press('enter')
            await pilot.pause()
            assert cluster.deleted == [(NAMESPACE, 'kube-system', None, False)]
            assert isinstance(app.screen, CatalogListScreen)

    asyncio.run(_run())


def test_sort_catalog_by_column() -> None:
    items = [
        _summary(NAMESPACE, 'kube-system', ('kube-system', 'Active', '2d'), ('kube-system', 'Active', 2.0)),
        _summary(NAMESPACE, 'apps', ('apps', 'Terminating', '1d'), ('apps', 'Terminating', 1.0)),
    ]
    by_name = [item.name for item in sort_catalog(items, 0, True)]
    assert by_name == ['apps', 'kube-system']
    by_status = [item.cells[1] for item in sort_catalog(items, 1, True)]
    assert by_status == ['Active', 'Terminating']
