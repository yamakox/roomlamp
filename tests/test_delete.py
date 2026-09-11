import asyncio

from kubernetes.client.exceptions import ApiException
from textual.widgets import DataTable, OptionList

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.delete import ACTION_DELETE, ACTION_EVICT, DeletedObject
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.k8s.workloads import DEPLOYMENT, WorkloadDetail, WorkloadSummary
from roomlamp.ui.screens.delete import DeleteConfirmScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.screens.pods import PodListScreen
from roomlamp.ui.screens.workloads import WorkloadDetailScreen, WorkloadListScreen


class FakeCluster:
    def __init__(self) -> None:
        self.pods = [PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a')]
        self.workloads = {
            DEPLOYMENT: [
                WorkloadSummary(
                    kind=DEPLOYMENT,
                    name='web',
                    namespace='default',
                    created=None,
                    cells=('default', 'web', '1/1', '1', '1', '1d'),
                    sort_keys=('default', 'web', (1, 1), 1, 1, 1.0),
                )
            ]
        }
        self.deleted: list[tuple[str, str, str | None, bool]] = []
        self.evicted: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def list_namespaces(self) -> list[str]:
        return ['default']

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
            container_names=('app',),
            default_container='app',
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
            fields=(('Ready', '1/1'),),
            containers=(f'{name}: image=nginx:1',),
        )

    def delete_resource(
        self, kind: str, name: str, *, namespace: str | None = None, force: bool = False
    ) -> DeletedObject:
        if self.error is not None:
            raise self.error
        self.deleted.append((kind, name, namespace, force))
        self.pods = [pod for pod in self.pods if not (pod.name == name and pod.namespace == namespace)]
        if kind in self.workloads:
            self.workloads[kind] = [
                item for item in self.workloads[kind] if not (item.name == name and item.namespace == namespace)
            ]
        return DeletedObject(kind=kind, name=name, namespace=namespace, force=force, action=ACTION_DELETE)

    def evict_pod(self, namespace: str, name: str) -> DeletedObject:
        if self.error is not None:
            raise self.error
        self.evicted.append((namespace, name))
        self.pods = [pod for pod in self.pods if not (pod.name == name and pod.namespace == namespace)]
        return DeletedObject(kind='Pod', name=name, namespace=namespace, force=False, action=ACTION_EVICT)


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


def test_pod_detail_delete_confirms_then_pops_to_list() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await _open_pod_detail(app, pilot)
            app.screen.action_delete()
            await pilot.pause()
            assert isinstance(app.screen, DeleteConfirmScreen)
            options = app.screen.query_one('#delete-list', OptionList)
            assert options.option_count == 3
            await pilot.press('enter')
            await pilot.pause()
            assert cluster.deleted == [('Pod', 'web', 'default', False)]
            assert cluster.evicted == []
            assert isinstance(app.screen, PodListScreen)

    asyncio.run(_run())


def test_pod_detail_force_delete_and_evict() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await _open_pod_detail(app, pilot)
            app.screen.action_delete()
            await pilot.pause()
            await pilot.press('down', 'enter')
            await pilot.pause()
            assert cluster.deleted == [('Pod', 'web', 'default', True)]

    asyncio.run(_run())

    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _evict() -> None:
        async with app.run_test() as pilot:
            await _open_pod_detail(app, pilot)
            app.screen.action_delete()
            await pilot.pause()
            await pilot.press('down', 'down', 'enter')
            await pilot.pause()
            assert cluster.evicted == [('default', 'web')]
            assert cluster.deleted == []
            assert isinstance(app.screen, PodListScreen)

    asyncio.run(_evict())


def test_pod_detail_delete_cancel_and_error() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _cancel() -> None:
        async with app.run_test() as pilot:
            await _open_pod_detail(app, pilot)
            app.screen.action_delete()
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            assert cluster.deleted == []
            assert isinstance(app.screen, PodDetailScreen)

    asyncio.run(_cancel())

    cluster = FakeCluster()
    cluster.error = ApiException(status=403, reason='Forbidden')
    cluster.error.body = '{"message":"pods \\"web\\" is forbidden"}'
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _error() -> None:
        async with app.run_test() as pilot:
            await _open_pod_detail(app, pilot)
            app.screen.action_delete()
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, PodDetailScreen)

    asyncio.run(_error())


def test_pod_list_delete_removes_row() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            table = app.query_one('#pods', DataTable)
            assert table.row_count == 1
            screen.action_delete()
            await pilot.pause()
            assert isinstance(app.screen, DeleteConfirmScreen)
            await pilot.press('enter')
            await pilot.pause()
            assert cluster.deleted == [('Pod', 'web', 'default', False)]
            assert isinstance(app.screen, PodListScreen)
            assert app.query_one('#pods', DataTable).row_count == 0

    asyncio.run(_run())


def test_workload_detail_delete_has_no_evict() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

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
            detail.action_delete()
            await pilot.pause()
            confirm = app.screen
            assert isinstance(confirm, DeleteConfirmScreen)
            assert confirm.query_one('#delete-list', OptionList).option_count == 2
            await pilot.press('enter')
            await pilot.pause()
            assert cluster.deleted == [('Deployment', 'web', 'default', False)]
            assert isinstance(app.screen, WorkloadListScreen)

    asyncio.run(_run())


async def _open_pod_detail(app: RoomlampApp, pilot) -> None:
    await pilot.pause()
    screen = app.screen
    assert isinstance(screen, PodListScreen)
    await screen._open_detail('default/web')
    await pilot.pause()
    assert isinstance(app.screen, PodDetailScreen)
