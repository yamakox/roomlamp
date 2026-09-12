import asyncio

from textual.widgets import OptionList

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.metrics import NodeMetricsResult
from roomlamp.k8s.nodes import HomeSnapshot, build_home_snapshot
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.k8s.workloads import POD_KIND
from roomlamp.ui.nav import NAV_GROUPS
from roomlamp.ui.screens.home import HomeScreen
from roomlamp.ui.screens.kinds import KindPickerScreen
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.pods import PodListScreen


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


def test_nav_groups_only_workloads_implemented() -> None:
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
    assert implemented == ['workloads']
    kinds = next(group.kinds for group in NAV_GROUPS if group.id == 'workloads')
    assert kinds[0].kind == POD_KIND


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
