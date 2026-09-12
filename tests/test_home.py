import asyncio
from datetime import datetime, timezone

from textual.widgets import DataTable, Static

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.metrics import METRICS_FORBIDDEN, METRICS_NOT_FOUND, NodeMetricsResult, NodeUsage
from roomlamp.k8s.nodes import HomeSnapshot, NodeSummary, build_home_snapshot
from roomlamp.k8s.resources import PodSummary
from roomlamp.ui.screens.home import HomeScreen
from roomlamp.ui.usage import format_bar, format_cpu, format_memory

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
GI = 1024**3


class FakeCluster:
    def __init__(self, *, metrics_status: str = 'ok', message: str = '') -> None:
        self.nodes = [
            NodeSummary('node-a', True, 'control-plane', '10.0.0.1', 'v1.34.0', '1d', CREATED, 4.0, 16 * GI),
        ]
        self.pods = [
            PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a', True),
            PodSummary('job', 'default', 'Succeeded', '0/1', 0, 'node-a', False),
        ]
        self.metrics = NodeMetricsResult(
            {'node-a': NodeUsage(2.0, 8 * GI)},
            metrics_status,
            message,
        )

    def load_home(self) -> HomeSnapshot:
        return build_home_snapshot(self.nodes, self.pods, self.metrics)


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


def test_home_shows_identity_overview_and_nodes() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            identity = str(app.query_one('#home-identity', Static).content)
            assert 'test-context' in identity
            assert 'test-cluster' in identity
            assert 'test-user' in identity
            assert '/tmp/kubeconfig' in identity
            assert 'dummy-token' not in identity
            overview = str(app.query_one('#home-overview', Static).content)
            assert 'CPU' in overview
            assert 'Memory' in overview
            assert 'Pods' in overview
            assert 'Nodes' in overview
            assert format_cpu(2.0) in overview
            table = app.query_one('#nodes', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'node-a' in row
            assert 'Yes' in row
            assert 'control-plane' in row
            assert '10.0.0.1' in row
            assert 'show_home' not in enabled_actions(app.screen)
            assert 'show_menu' in enabled_actions(app.screen)

    asyncio.run(_run())


def test_home_metrics_not_found_keeps_counts() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(metrics_status=METRICS_NOT_FOUND), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            overview = str(app.query_one('#home-overview', Static).content)
            assert 'unavailable' in overview
            assert 'Pods' in overview
            assert 'Nodes' in overview
            table = app.query_one('#nodes', DataTable)
            assert 'unavailable' in str(table.get_row_at(0)[1])

    asyncio.run(_run())


def test_home_metrics_forbidden_hides_bars() -> None:
    app = RoomlampApp(
        _info(),
        cluster=FakeCluster(metrics_status=METRICS_FORBIDDEN, message='Metrics forbidden'),
        enable_watch=False,
    )

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.query_one('#home-status', Static).content)
            assert 'forbidden' in status.lower()
            overview = str(app.query_one('#home-overview', Static).content)
            assert 'CPU' not in overview
            assert 'Pods' in overview
            row = app.query_one('#nodes', DataTable).get_row_at(0)
            assert row[1] == '—'

    asyncio.run(_run())


def test_format_bar_and_units() -> None:
    text = format_bar(1.0, 4.0, used_label=format_cpu(1.0), capacity_label=format_cpu(4.0), width=4)
    assert text.startswith('[')
    assert '1.00 / 4.00 (25%)' in text
    assert format_memory(8 * GI) == '8.00 Gi'
    unavailable = format_bar(None, 4.0, unavailable=True, width=4)
    assert 'unavailable' in unavailable
