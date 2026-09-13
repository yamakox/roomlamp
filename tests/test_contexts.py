import asyncio
from datetime import datetime, timezone
from pathlib import Path

from helpers import open_kind
from textual.widgets import DataTable, OptionList, Static, TextArea

from roomlamp.app import RoomlampApp
from roomlamp.k8s.client import build_api_client
from roomlamp.k8s.cluster import close_cluster
from roomlamp.k8s.context import ClusterInfo, load_cluster_info
from roomlamp.k8s.metrics import NodeMetricsResult, NodeUsage
from roomlamp.k8s.nodes import HomeSnapshot, NodeSummary, build_home_snapshot
from roomlamp.k8s.resources import PodDetail, PodSummary
from roomlamp.ui.screens.containers import ContainerScreen
from roomlamp.ui.screens.contexts import ContextScreen
from roomlamp.ui.screens.exec import PodExecScreen
from roomlamp.ui.screens.home import HomeScreen
from roomlamp.ui.screens.logs import PodLogsScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.screens.pods import PodListScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
GI = 1024**3


class TrackingCluster:
    def __init__(self, node_name: str) -> None:
        self.node_name = node_name
        self.closed = False
        self.pods = [PodSummary('web', 'default', 'Running', '1/1', 0, node_name)]

    def close(self) -> None:
        self.closed = True

    def list_namespaces(self) -> list[str]:
        return ['default']

    def list_pods(self, namespace: str) -> list[PodSummary]:
        return list(self.pods)

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        return PodDetail(
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            phase='Running',
            ready='1/1',
            restarts=0,
            node=self.node_name,
            pod_ip='10.1.0.5',
            labels=(('app', name),),
            containers=(f'{name}: running',),
            container_names=('app',),
            default_container='app',
        )

    def get_pod_yaml(self, namespace: str, name: str, hide_managed_fields: bool = True) -> str:
        return f'apiVersion: v1\nkind: Pod\nmetadata:\n  name: {name}\n  namespace: {namespace}\n'

    def read_pod_logs(
        self,
        namespace: str,
        name: str,
        *,
        container: str | None = None,
        tail_lines: int = 100,
        timestamps: bool = True,
        previous: bool = False,
    ) -> str:
        return f'{name}: hello from {container or "app"}\n'

    def load_home(self) -> HomeSnapshot:
        nodes = [
            NodeSummary(self.node_name, True, 'worker', '10.0.0.1', 'v1.34.0', '1d', CREATED, 4.0, 16 * GI),
        ]
        metrics = NodeMetricsResult({self.node_name: NodeUsage(1.0, 4 * GI)}, 'ok')
        return build_home_snapshot(nodes, self.pods, metrics)


def enabled_actions(screen) -> set[str]:
    return {info.binding.action for info in screen.active_bindings.values() if info.enabled}


def capture_notify(app: RoomlampApp) -> list[str]:
    notes: list[str] = []
    original = app.notify

    def _notify(message: str, **kwargs: object) -> None:
        notes.append(str(message))
        original(message, **kwargs)

    app.notify = _notify  # type: ignore[method-assign]
    return notes


def _option_labels(screen: ContextScreen) -> list[str]:
    options = screen.query_one('#context-list', OptionList)
    return [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]


def test_home_context_key_opens_picker_with_one_context(kubeconfig_path: Path) -> None:
    one = ClusterInfo(
        kubeconfig=str(kubeconfig_path),
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )
    app = RoomlampApp(one, cluster=TrackingCluster('node-a'), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert 'pick_context' in enabled_actions(app.screen)
            await pilot.press('c')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, ContextScreen)
            assert _option_labels(picker) == ['test-context (current)']

    asyncio.run(_run())


def test_context_key_available_when_cluster_missing() -> None:
    info = ClusterInfo(
        kubeconfig='/tmp/missing',
        context_name=None,
        cluster_name=None,
        user_name=None,
        namespace=None,
        context_names=(),
        error='No such file',
    )
    app = RoomlampApp(info, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert 'pick_context' in enabled_actions(app.screen)
            assert 'show_menu' not in enabled_actions(app.screen)
            await pilot.press('c')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, ContextScreen)
            assert _option_labels(picker) == []

    asyncio.run(_run())


def test_home_context_picker_lists_contexts(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    app = RoomlampApp(info, cluster=TrackingCluster('node-a'), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('c')
            await pilot.pause()
            picker = app.screen
            assert isinstance(picker, ContextScreen)
            assert _option_labels(picker) == ['test-context (current)', 'other-context']

    asyncio.run(_run())


def test_same_context_notifies_and_stays(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    cluster = TrackingCluster('node-a')
    app = RoomlampApp(info, cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            notes = capture_notify(app)
            await pilot.press('c')
            await pilot.pause()
            assert isinstance(app.screen, ContextScreen)
            await pilot.press('enter')
            await pilot.pause()
            assert notes == ['No changes to apply']
            assert isinstance(app.screen, PodListScreen)
            assert app.cluster_info.context_name == 'test-context'
            assert app.cluster is cluster
            assert cluster.closed is False

    asyncio.run(_run())


def test_switch_context_returns_home_and_does_not_rewrite_kubeconfig(
    kubeconfig_path: Path,
    monkeypatch,
) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    old = TrackingCluster('node-a')
    new = TrackingCluster('node-b')
    monkeypatch.setattr('roomlamp.app.build_cluster', lambda switched: new)
    app = RoomlampApp(info, cluster=old, enable_watch=False)
    before = kubeconfig_path.read_text(encoding='utf-8')

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            await screen_open_detail(app, pilot)
            app.switch_context('other-context')
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            identity = str(app.query_one('#home-identity', Static).content)
            assert 'other-context' in identity
            assert 'other-cluster' in identity
            assert 'other-user' in identity
            assert 'dummy-token' not in identity
            table = app.query_one('#nodes', DataTable)
            assert table.row_count == 1
            assert 'node-b' in table.get_row_at(0)
            assert app.cluster_info.context_name == 'other-context'
            assert app.cluster is new
            assert old.closed is True
            assert new.closed is False
            assert kubeconfig_path.read_text(encoding='utf-8') == before
            assert 'current-context: test-context' in before

    asyncio.run(_run())


async def screen_open_detail(app: RoomlampApp, pilot) -> None:
    screen = app.screen
    assert isinstance(screen, PodListScreen)
    await screen._open_detail('default/web')
    await pilot.pause()
    assert isinstance(app.screen, PodDetailScreen)


def test_failed_switch_keeps_current_screen(kubeconfig_path: Path, monkeypatch) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    cluster = TrackingCluster('node-a')

    def fail(_info: object) -> None:
        raise RuntimeError('authentication failed')

    monkeypatch.setattr('roomlamp.app.build_cluster', fail)
    app = RoomlampApp(info, cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            notes = capture_notify(app)
            app.switch_context('other-context')
            await pilot.pause()
            assert isinstance(app.screen, PodListScreen)
            assert app.cluster_info.context_name == 'test-context'
            assert app.cluster is cluster
            assert cluster.closed is False
            assert notes == ['authentication failed']

    asyncio.run(_run())


def test_detail_has_context_key(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    app = RoomlampApp(info, cluster=TrackingCluster('node-a'), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            await screen_open_detail(app, pilot)
            assert 'pick_context' in enabled_actions(app.screen)

    asyncio.run(_run())


def test_logs_yaml_and_exec_omit_context_key() -> None:
    log_actions = {item[1] if isinstance(item, tuple) else item.action for item in PodLogsScreen.BINDINGS}
    yaml_actions = {item[1] if isinstance(item, tuple) else item.action for item in YamlViewScreen.BINDINGS}
    exec_actions = {item[1] if isinstance(item, tuple) else item.action for item in PodExecScreen.BINDINGS}
    assert 'pick_context' not in log_actions
    assert 'pick_container' in log_actions
    assert 'pick_context' not in yaml_actions
    assert 'pick_context' not in exec_actions


def test_logs_c_still_picks_container(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    app = RoomlampApp(info, cluster=TrackingCluster('node-a'), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            await screen_open_detail(app, pilot)
            detail = app.screen
            assert isinstance(detail, PodDetailScreen)
            await detail.action_show_logs()
            await pilot.pause()
            assert isinstance(app.screen, PodLogsScreen)
            await pilot.press('c')
            await pilot.pause()
            assert isinstance(app.screen, ContainerScreen)

    asyncio.run(_run())


def test_yaml_c_does_not_open_context_picker(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    app = RoomlampApp(info, cluster=TrackingCluster('node-a'), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            await screen_open_detail(app, pilot)
            detail = app.screen
            assert isinstance(detail, PodDetailScreen)
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            await pilot.press('c')
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            assert 'kind: Pod' in app.screen.query_one('#yaml-view', TextArea).text

    asyncio.run(_run())


def test_build_api_client_does_not_rewrite_kubeconfig(kubeconfig_path: Path) -> None:
    before = kubeconfig_path.read_text(encoding='utf-8')
    client = build_api_client(str(kubeconfig_path), 'other-context')
    try:
        assert kubeconfig_path.read_text(encoding='utf-8') == before
        assert 'current-context: test-context' in before
    finally:
        client.close()


def test_close_cluster_ignores_missing_close() -> None:
    close_cluster(None)
    close_cluster(object())
