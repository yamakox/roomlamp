import asyncio

from textual.widgets import DataTable, OptionList

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.metrics import NodeMetricsResult
from roomlamp.k8s.nodes import HomeSnapshot, build_home_snapshot
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.k8s.network import SERVICE, NetworkSummary
from roomlamp.k8s.security import SERVICE_ACCOUNT, SecuritySummary
from roomlamp.k8s.storage import PVC, StorageSummary
from roomlamp.k8s.workloads import POD_KIND
from roomlamp.ui.nav import NAV_GROUPS
from roomlamp.ui.screens.home import HomeScreen
from roomlamp.ui.screens.kinds import KindPickerScreen
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.network import NetworkListScreen
from roomlamp.ui.screens.pods import PodListScreen
from roomlamp.ui.screens.security import SecurityListScreen
from roomlamp.ui.screens.storage import StorageListScreen


class FakeCluster:
    def __init__(self) -> None:
        self.pods = [PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a', True)]

    def load_home(self) -> HomeSnapshot:
        return build_home_snapshot([], self.pods, NodeMetricsResult({}, 'not_found'))

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
            labels=(),
            containers=(),
        )

    def list_storage(self, kind: str, namespace: str) -> list[StorageSummary]:
        return [
            StorageSummary(
                kind=PVC,
                name='data',
                namespace='default',
                created=None,
                cells=('default', 'data', 'Bound', 'pvc-abc', '8Gi', 'ReadWriteOnce', 'standard', '1d'),
                sort_keys=('default', 'data', 'Bound', 'pvc-abc', '8Gi', 'ReadWriteOnce', 'standard', 1.0),
            )
        ]

    def list_network(self, kind: str, namespace: str) -> list[NetworkSummary]:
        return [
            NetworkSummary(
                kind=SERVICE,
                name='web',
                namespace='default',
                created=None,
                cells=('default', 'web', 'ClusterIP', '10.96.0.10', '', '80/TCP', 'app=web', '1d'),
                sort_keys=('default', 'web', 'ClusterIP', '10.96.0.10', '', '80/TCP', 'app=web', 1.0),
            )
        ]

    def list_security(self, kind: str, namespace: str) -> list[SecuritySummary]:
        return [
            SecuritySummary(
                kind=SERVICE_ACCOUNT,
                name='builder',
                namespace='default',
                created=None,
                cells=('default', 'builder', '1', '1d'),
                sort_keys=('default', 'builder', 1, 1.0),
            )
        ]


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


def test_nav_groups_workloads_storage_network_and_security_implemented() -> None:
    labels = [group.label for group in NAV_GROUPS]
    assert labels == [
        'Cluster',
        'Workloads',
        'Storage',
        'Network',
        'Gateway',
        'Security',
        'Configuration',
    ]
    implemented = [group.id for group in NAV_GROUPS if group.implemented]
    assert implemented == ['workloads', 'storage', 'network', 'security']
    kinds = next(group.kinds for group in NAV_GROUPS if group.id == 'workloads')
    assert kinds[0].kind == POD_KIND
    storage = next(group.kinds for group in NAV_GROUPS if group.id == 'storage')
    assert [item.kind for item in storage] == ['PersistentVolumeClaim', 'PersistentVolume', 'StorageClass']
    network = next(group.kinds for group in NAV_GROUPS if group.id == 'network')
    assert [item.kind for item in network] == ['Service', 'Endpoints', 'EndpointSlice', 'Ingress']
    security = next(group.kinds for group in NAV_GROUPS if group.id == 'security')
    assert [item.kind for item in security] == ['ServiceAccount', 'Role', 'RoleBinding']


def test_menu_empty_group_stays_open() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_menu_workloads_opens_pod_list() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            options = menu.query_one('#menu-list', OptionList)
            options.highlighted = 1
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            labels = [str(kind_list.get_option_at_index(i).prompt) for i in range(kind_list.option_count)]
            assert 'Pods' in labels
            assert labels[-1] == 'Back'
            assert all('(current)' not in label for label in labels)
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, PodListScreen)
            assert 'pick_kind' not in enabled_actions(app.screen)
            assert 'show_pods' not in enabled_actions(app.screen)
            assert 'show_cluster' not in enabled_actions(app.screen)
            assert 'show_menu' in enabled_actions(app.screen)
            assert 'show_home' in enabled_actions(app.screen)
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 1
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            labels = [str(kind_list.get_option_at_index(i).prompt) for i in range(kind_list.option_count)]
            assert 'Pods (current)' in labels
            await pilot.press('escape')
            await pilot.pause()
            await pilot.press('h')
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(_run())


def test_menu_storage_opens_pvc_list() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 2
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            labels = [str(kind_list.get_option_at_index(i).prompt) for i in range(kind_list.option_count)]
            assert labels == [
                'Persistent Volume Claims',
                'Persistent Volumes',
                'Storage Classes',
                'Back',
            ]
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, StorageListScreen)
            assert screen.kind == PVC
            assert 'pick_namespace' in enabled_actions(screen)
            assert 'show_menu' in enabled_actions(screen)
            table = screen.query_one('#storage', DataTable)
            assert table.row_count == 1
            assert 'data' in table.get_row_at(0)

    asyncio.run(_run())


def test_menu_network_opens_service_list() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 3
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            labels = [str(kind_list.get_option_at_index(i).prompt) for i in range(kind_list.option_count)]
            assert labels == [
                'Services',
                'Endpoints',
                'Endpoint Slices',
                'Ingresses',
                'Back',
            ]
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, NetworkListScreen)
            assert screen.kind == SERVICE
            assert 'pick_namespace' in enabled_actions(screen)
            assert 'show_menu' in enabled_actions(screen)
            table = screen.query_one('#network', DataTable)
            assert table.row_count == 1
            assert 'web' in table.get_row_at(0)

    asyncio.run(_run())


def test_menu_security_opens_service_account_list() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 5
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            labels = [str(kind_list.get_option_at_index(i).prompt) for i in range(kind_list.option_count)]
            assert labels == [
                'Service Accounts',
                'Roles',
                'Role Bindings',
                'Back',
            ]
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            assert screen.kind == SERVICE_ACCOUNT
            assert 'pick_namespace' in enabled_actions(screen)
            assert 'show_menu' in enabled_actions(screen)
            table = screen.query_one('#security', DataTable)
            assert table.row_count == 1
            assert 'builder' in table.get_row_at(0)

    asyncio.run(_run())


def test_menu_back_from_kind_returns_to_group() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            menu.query_one('#menu-list', OptionList).highlighted = 3
            await pilot.press('enter')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, KindPickerScreen)
            kind_list = picker.query_one('#kind-list', OptionList)
            kind_list.highlighted = kind_list.option_count - 1
            await pilot.press('enter')
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, MainMenuScreen)
            labels = [
                str(menu.query_one('#menu-list', OptionList).get_option_at_index(i).prompt)
                for i in range(menu.query_one('#menu-list', OptionList).option_count)
            ]
            assert labels[-1] == 'Back'
            assert 'Network' in labels
            menu.query_one('#menu-list', OptionList).highlighted = 1
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, KindPickerScreen)
            assert app.screen.group.id == 'workloads'

    asyncio.run(_run())


def test_menu_back_from_group_closes() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)
            options = app.screen.query_one('#menu-list', OptionList)
            options.highlighted = options.option_count - 1
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(_run())


def test_menu_escape_from_kind_closes() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            app.screen.query_one('#menu-list', OptionList).highlighted = 3
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, KindPickerScreen)
            await pilot.press('escape')
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(_run())
