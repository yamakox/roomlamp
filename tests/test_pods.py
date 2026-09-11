import asyncio

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.ui.screens.namespaces import NamespaceScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.screens.pods import PodListScreen, sort_pods
from textual.widgets import DataTable, Static


class FakeCluster:
    def __init__(self) -> None:
        self.pods = [
            PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a'),
            PodSummary('dns', 'kube-system', 'Running', '1/1', 1, 'node-b'),
        ]

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_pods(self, namespace: str) -> list[PodSummary]:
        if namespace == ALL_NAMESPACES:
            return list(self.pods)
        return [pod for pod in self.pods if pod.namespace == namespace]

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        return PodDetail(
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            phase='Running',
            ready='1/1',
            restarts=0,
            node='node-a',
            pod_ip='10.1.0.5',
            labels=(('app', name),),
            containers=(f'{name}: running',),
        )


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


def test_pod_list_shows_namespace_pods() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, PodListScreen)
            table = app.query_one('#pods', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'web' in row
            assert 'dns' not in row
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_pod_detail_opens_from_row() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            await screen._open_detail('default/web')
            await pilot.pause()
            assert isinstance(app.screen, PodDetailScreen)
            detail = app.screen.query_one('#pod-detail', Static)
            assert 'web' in str(detail.content)
            assert '10.1.0.5' in str(detail.content)

    asyncio.run(_run())


def test_namespace_key_opens_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            assert isinstance(app.screen, NamespaceScreen)

    asyncio.run(_run())


def test_sort_pods_toggles_column_direction() -> None:
    pods = [
        PodSummary('web', 'default', 'Running', '1/1', 0, 'node-b'),
        PodSummary('dns', 'kube-system', 'Pending', '0/1', 3, 'node-a'),
        PodSummary('api', 'default', 'Running', '2/2', 1, 'node-a'),
    ]
    by_name_asc = [pod.name for pod in sort_pods(pods, 1, True)]
    assert by_name_asc == ['api', 'dns', 'web']
    by_name_desc = [pod.name for pod in sort_pods(pods, 1, False)]
    assert by_name_desc == ['web', 'dns', 'api']
    by_restarts_asc = [pod.restarts for pod in sort_pods(pods, 4, True)]
    assert by_restarts_asc == [0, 1, 3]


def test_header_click_sorts_then_reverses() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            table = app.query_one('#pods', DataTable)
            columns = table.columns
            name_key = next(key for key, column in columns.items() if column.label.plain == 'Name')
            screen.on_data_table_header_selected(DataTable.HeaderSelected(table, name_key, 1, columns[name_key].label))
            assert [table.get_row_at(i)[1] for i in range(table.row_count)] == ['dns', 'web']
            assert screen.sort_column == 1
            assert screen.sort_ascending is True
            screen.on_data_table_header_selected(DataTable.HeaderSelected(table, name_key, 1, columns[name_key].label))
            assert [table.get_row_at(i)[1] for i in range(table.row_count)] == ['web', 'dns']
            assert screen.sort_ascending is False
            ns_key = next(key for key, column in columns.items() if column.label.plain == 'Namespace')
            screen.on_data_table_header_selected(DataTable.HeaderSelected(table, ns_key, 0, columns[ns_key].label))
            assert screen.sort_column == 0
            assert screen.sort_ascending is True

    asyncio.run(_run())
