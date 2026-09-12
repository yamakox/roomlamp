import asyncio
from datetime import datetime, timezone

from textual.widgets import DataTable, Static, TextArea

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.k8s.storage import PV, PVC, STORAGE_CLASS, StorageDetail, StorageSummary, is_namespaced
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.storage import StorageDetailScreen, StorageListScreen, sort_storage
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _summary(
    kind: str,
    name: str,
    namespace: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> StorageSummary:
    return StorageSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
    )


class FakeCluster:
    def __init__(self) -> None:
        self.storage = {
            PVC: [
                _summary(
                    PVC,
                    'data',
                    'default',
                    ('default', 'data', 'Bound', 'pvc-abc', '8Gi', 'ReadWriteOnce', 'standard', '1d'),
                    ('default', 'data', 'Bound', 'pvc-abc', '8Gi', 'ReadWriteOnce', 'standard', 1.0),
                ),
                _summary(
                    PVC,
                    'logs',
                    'kube-system',
                    ('kube-system', 'logs', 'Pending', '', '1Gi', 'ReadWriteOnce', 'standard', '2d'),
                    ('kube-system', 'logs', 'Pending', '', '1Gi', 'ReadWriteOnce', 'standard', 2.0),
                ),
            ],
            PV: [
                _summary(
                    PV,
                    'pv-disk',
                    '',
                    ('pv-disk', '10Gi', 'ReadWriteOnce', 'Retain', 'Bound', 'default/data', 'standard', '1d'),
                    ('pv-disk', '10Gi', 'ReadWriteOnce', 'Retain', 'Bound', 'default/data', 'standard', 1.0),
                ),
            ],
            STORAGE_CLASS: [
                _summary(
                    STORAGE_CLASS,
                    'standard',
                    '',
                    ('standard', 'csi.test', 'Yes', 'Delete', 'WaitForFirstConsumer', 'Yes', '1d'),
                    ('standard', 'csi.test', 'Yes', 'Delete', 'WaitForFirstConsumer', 'Yes', 1.0),
                ),
            ],
        }

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_storage(self, kind: str, namespace: str) -> list[StorageSummary]:
        items = list(self.storage.get(kind, []))
        if not is_namespaced(kind) or namespace == ALL_NAMESPACES:
            return items
        return [item for item in items if item.namespace == namespace]

    def get_storage(self, kind: str, namespace: str, name: str) -> StorageDetail:
        return StorageDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=(('app', name),),
            fields=(('Status', 'Bound'), ('Capacity', '8Gi')),
        )

    def get_storage_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        ns = f'  namespace: {namespace}\n' if namespace else ''
        version = 'storage.k8s.io/v1' if kind == STORAGE_CLASS else 'v1'
        return f'apiVersion: {version}\nkind: {kind}\nmetadata:\n  name: {name}\n{ns}'


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


def test_pvc_list_filters_by_namespace() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, PVC)
            screen = app.screen
            assert isinstance(screen, StorageListScreen)
            table = screen.query_one('#storage', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'data' in row
            assert 'logs' not in row
            assert 'pick_namespace' in enabled_actions(screen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_pvc_detail_and_yaml() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, PVC)
            screen = app.screen
            assert isinstance(screen, StorageListScreen)
            await screen._open_detail('default/data')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, StorageDetailScreen)
            text = str(detail.query_one('#storage-detail', Static).content)
            assert 'PersistentVolumeClaim' in text
            assert 'data' in text
            assert 'Bound' in text
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: PersistentVolumeClaim' in yaml_text
            assert 'name: data' in yaml_text

    asyncio.run(_run())


def test_pv_list_hides_namespace_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, PV)
            screen = app.screen
            assert isinstance(screen, StorageListScreen)
            table = screen.query_one('#storage', DataTable)
            assert table.row_count == 1
            assert 'pv-disk' in table.get_row_at(0)
            assert 'pick_namespace' not in enabled_actions(screen)
            assert 'show_menu' in enabled_actions(screen)
            await screen._open_detail('pv-disk')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, StorageDetailScreen)
            text = str(detail.query_one('#storage-detail', Static).content)
            assert 'PersistentVolume' in text
            assert 'Namespace' not in text

    asyncio.run(_run())


def test_storage_class_list_and_menu_key() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, STORAGE_CLASS)
            screen = app.screen
            assert isinstance(screen, StorageListScreen)
            table = screen.query_one('#storage', DataTable)
            assert 'standard' in table.get_row_at(0)
            assert 'csi.test' in table.get_row_at(0)
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_sort_storage_by_column() -> None:
    items = [
        _summary(
            PVC,
            'data',
            'default',
            ('default', 'data', 'Bound', 'pvc-abc', '8Gi', 'ReadWriteOnce', 'standard', '1d'),
            ('default', 'data', 'Bound', 'pvc-abc', '8Gi', 'ReadWriteOnce', 'standard', 1.0),
        ),
        _summary(
            PVC,
            'cache',
            'default',
            ('default', 'cache', 'Pending', '', '1Gi', 'ReadWriteOnce', 'standard', '2d'),
            ('default', 'cache', 'Pending', '', '1Gi', 'ReadWriteOnce', 'standard', 2.0),
        ),
    ]
    by_name = [item.name for item in sort_storage(items, 1, True)]
    assert by_name == ['cache', 'data']
    by_status = [item.cells[2] for item in sort_storage(items, 2, True)]
    assert by_status == ['Bound', 'Pending']
