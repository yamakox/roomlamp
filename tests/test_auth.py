import asyncio

from textual.widgets import DataTable, OptionList, TextArea

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.delete import ACTION_DELETE, DeletedObject
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.k8s.workloads import DEPLOYMENT, WorkloadDetail, WorkloadSummary
from roomlamp.ui.screens.delete import DeleteConfirmScreen
from roomlamp.ui.screens.logs import PodLogsScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.screens.pods import PodListScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen


class FakeCluster:
    def __init__(
        self,
        *,
        default: bool = True,
        grants: dict[tuple[str, str | None], bool] | None = None,
    ) -> None:
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
        self.default = default
        self.grants = grants or {}
        self.checks: list[tuple[str, str, str | None, str | None, str | None]] = []
        self.deleted: list[tuple[str, str, str | None, bool]] = []

    def check_access(
        self,
        verb: str,
        kind: str,
        *,
        namespace: str | None = None,
        name: str | None = None,
        subresource: str | None = None,
    ) -> bool:
        self.checks.append((verb, kind, namespace, name, subresource))
        key = (verb, subresource)
        if key in self.grants:
            return self.grants[key]
        return self.default

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

    def get_pod_yaml(self, namespace: str, name: str, hide_managed_fields: bool = True) -> str:
        return f'apiVersion: v1\nkind: Pod\nmetadata:\n  name: {name}\n  namespace: {namespace}\n'

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
        self.deleted.append((kind, name, namespace, force))
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


async def _open_pod_detail(app: RoomlampApp, pilot) -> PodDetailScreen:
    await pilot.pause()
    screen = app.screen
    assert isinstance(screen, PodListScreen)
    await screen._open_detail('default/web')
    await pilot.pause()
    detail = app.screen
    assert isinstance(detail, PodDetailScreen)
    await detail._load_auth()
    await pilot.pause()
    return detail


def test_pod_detail_hides_unauthorized_actions() -> None:
    cluster = FakeCluster(default=False)
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            detail = await _open_pod_detail(app, pilot)
            actions = enabled_actions(detail)
            assert 'show_logs' not in actions
            assert 'show_exec' not in actions
            assert 'delete' not in actions
            assert 'show_yaml' in actions
            await detail.action_show_logs()
            await pilot.pause()
            assert isinstance(app.screen, PodDetailScreen)
            await pilot.press('d')
            await pilot.pause()
            assert isinstance(app.screen, PodDetailScreen)
            assert cluster.deleted == []

    asyncio.run(_run())


def test_pod_detail_delete_without_evict_omits_evict_option() -> None:
    cluster = FakeCluster(grants={('create', 'eviction'): False})
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            detail = await _open_pod_detail(app, pilot)
            detail.action_delete()
            await pilot.pause()
            confirm = app.screen
            assert isinstance(confirm, DeleteConfirmScreen)
            options = confirm.query_one('#delete-list', OptionList)
            assert options.option_count == 2
            ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
            assert 'evict' not in ids

    asyncio.run(_run())


def test_pod_detail_evict_only_hides_delete_options() -> None:
    cluster = FakeCluster(default=False, grants={('create', 'eviction'): True})
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            detail = await _open_pod_detail(app, pilot)
            assert 'delete' in enabled_actions(detail)
            detail.action_delete()
            await pilot.pause()
            confirm = app.screen
            assert isinstance(confirm, DeleteConfirmScreen)
            options = confirm.query_one('#delete-list', OptionList)
            assert options.option_count == 1
            assert options.get_option_at_index(0).id == 'evict'

    asyncio.run(_run())


def test_pod_detail_yaml_without_update_is_read_only() -> None:
    cluster = FakeCluster(grants={('update', None): False})
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            detail = await _open_pod_detail(app, pilot)
            await detail.action_show_yaml()
            await pilot.pause()
            yaml_screen = app.screen
            assert isinstance(yaml_screen, YamlViewScreen)
            assert yaml_screen.query_one('#yaml-view', TextArea).read_only is True
            actions = enabled_actions(yaml_screen)
            assert 'apply' not in actions
            assert 'dry_run' not in actions

    asyncio.run(_run())


def test_pod_detail_logs_allowed_still_opens() -> None:
    cluster = FakeCluster(
        grants={
            ('create', 'exec'): False,
            ('delete', None): False,
            ('create', 'eviction'): False,
        }
    )
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            detail = await _open_pod_detail(app, pilot)
            actions = enabled_actions(detail)
            assert 'show_logs' in actions
            assert 'show_exec' not in actions
            await detail.action_show_logs()
            await pilot.pause()
            assert isinstance(app.screen, PodLogsScreen)

    asyncio.run(_run())


def test_pod_list_hides_delete_when_unauthorized() -> None:
    cluster = FakeCluster(default=False)
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            await screen._load_row_auth('default/web')
            await pilot.pause()
            assert 'delete' not in enabled_actions(screen)
            assert app.query_one('#pods', DataTable).row_count == 1
            await pilot.press('d')
            await pilot.pause()
            assert isinstance(app.screen, PodListScreen)
            assert cluster.deleted == []

    asyncio.run(_run())
