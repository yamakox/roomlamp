import asyncio
from datetime import datetime, timezone

from textual.widgets import DataTable, Static, TextArea

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.k8s.workloads import DEPLOYMENT, REPLICASET, WorkloadDetail, WorkloadSummary
from roomlamp.ui.screens.kinds import WorkloadKindScreen
from roomlamp.ui.screens.pods import PodListScreen
from roomlamp.ui.screens.workloads import WorkloadDetailScreen, WorkloadListScreen, sort_workloads
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _summary(
    kind: str,
    name: str,
    namespace: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> WorkloadSummary:
    return WorkloadSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
    )


class FakeCluster:
    def __init__(self) -> None:
        self.pods = [
            PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a'),
        ]
        self.workloads = {
            DEPLOYMENT: [
                _summary(
                    DEPLOYMENT,
                    'web',
                    'default',
                    ('default', 'web', '2/3', '3', '2', '1d'),
                    ('default', 'web', (2, 3), 3, 2, 1.0),
                ),
                _summary(
                    DEPLOYMENT,
                    'dns',
                    'kube-system',
                    ('kube-system', 'dns', '1/1', '1', '1', '2d'),
                    ('kube-system', 'dns', (1, 1), 1, 1, 2.0),
                ),
            ],
            REPLICASET: [
                _summary(
                    REPLICASET,
                    'web-abc',
                    'default',
                    ('default', 'web-abc', '3', '3', '2', '1d'),
                    ('default', 'web-abc', 3, 3, 2, 1.0),
                ),
            ],
        }

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

    def list_workloads(self, kind: str, namespace: str) -> list[WorkloadSummary]:
        items = list(self.workloads.get(kind, []))
        if namespace == ALL_NAMESPACES:
            return items
        return [item for item in items if item.namespace == namespace]

    def get_workload(self, kind: str, namespace: str, name: str) -> WorkloadDetail:
        return WorkloadDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=(('app', name),),
            fields=(('Ready', '2/3'), ('Selector', 'app=web')),
            containers=(f'{name}: image=nginx:1',),
        )

    def get_workload_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        return f'apiVersion: apps/v1\nkind: {kind}\nmetadata:\n  name: {name}\n  namespace: {namespace}\n'


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


def test_workload_list_shows_namespace_deployments() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen._on_kind_chosen(DEPLOYMENT)
            await pilot.pause()
            assert isinstance(app.screen, WorkloadListScreen)
            table = app.screen.query_one('#workloads', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'web' in row
            assert 'dns' not in row
            assert '2/3' in row
            current = app.screen
            assert isinstance(current, WorkloadListScreen)
            current.namespace = ALL_NAMESPACES
            current._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_workload_detail_opens_from_row() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen._on_kind_chosen(DEPLOYMENT)
            await pilot.pause()
            current = app.screen
            assert isinstance(current, WorkloadListScreen)
            await current._open_detail('default/web')
            await pilot.pause()
            assert isinstance(app.screen, WorkloadDetailScreen)
            detail = app.screen.query_one('#workload-detail', Static)
            text = str(detail.content)
            assert 'Deployment' in text
            assert 'web' in text
            assert 'nginx:1' in text

    asyncio.run(_run())


def test_workload_key_opens_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('w')
            await pilot.pause()
            assert isinstance(app.screen, WorkloadKindScreen)

    asyncio.run(_run())


def test_switch_to_replicaset_list() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen._on_kind_chosen(DEPLOYMENT)
            await pilot.pause()
            current = app.screen
            assert isinstance(current, WorkloadListScreen)
            current._on_kind_chosen(REPLICASET)
            await pilot.pause()
            assert isinstance(app.screen, WorkloadListScreen)
            table = app.screen.query_one('#workloads', DataTable)
            assert table.row_count == 1
            assert 'web-abc' in table.get_row_at(0)

    asyncio.run(_run())


def test_sort_workloads_by_column() -> None:
    items = [
        _summary(
            DEPLOYMENT,
            'web',
            'default',
            ('default', 'web', '2/3', '3', '2', '1d'),
            ('default', 'web', (2, 3), 3, 2, 1.0),
        ),
        _summary(
            DEPLOYMENT,
            'api',
            'default',
            ('default', 'api', '1/1', '1', '1', '2d'),
            ('default', 'api', (1, 1), 1, 1, 2.0),
        ),
        _summary(
            DEPLOYMENT,
            'dns',
            'kube-system',
            ('kube-system', 'dns', '0/1', '1', '0', '3d'),
            ('kube-system', 'dns', (0, 1), 1, 0, 3.0),
        ),
    ]
    by_name = [item.name for item in sort_workloads(items, 1, True)]
    assert by_name == ['api', 'dns', 'web']
    by_ready = [item.cells[2] for item in sort_workloads(items, 2, True)]
    assert by_ready == ['0/1', '1/1', '2/3']


def test_workload_yaml_opens_from_detail() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen._on_kind_chosen(DEPLOYMENT)
            await pilot.pause()
            current = app.screen
            assert isinstance(current, WorkloadListScreen)
            await current._open_detail('default/web')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, WorkloadDetailScreen)
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_view = app.screen.query_one('#yaml-view', TextArea)
            text = yaml_view.text
            assert 'kind: Deployment' in text
            assert 'name: web' in text

    asyncio.run(_run())
