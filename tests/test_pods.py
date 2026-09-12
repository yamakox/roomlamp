import asyncio
import threading
import time

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.ui.screens.logs import PodLogsScreen
from roomlamp.ui.screens.namespaces import NamespaceScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.screens.pods import PodListScreen, sort_pods
from roomlamp.ui.screens.yaml_view import YamlViewScreen
from textual.widgets import DataTable, Log, Static, TextArea


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
            await open_kind(app, pilot)
            assert isinstance(app.screen, PodListScreen)
            table = app.screen.query_one('#pods', DataTable)
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
            await open_kind(app, pilot)
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
            await open_kind(app, pilot)
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
            await open_kind(app, pilot)
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            table = app.screen.query_one('#pods', DataTable)
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


def test_pod_yaml_and_logs_open_from_detail() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            await screen._open_detail('default/web')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, PodDetailScreen)
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_view = app.screen.query_one('#yaml-view', TextArea)
            assert 'kind: Pod' in yaml_view.text
            assert 'name: web' in yaml_view.text
            await pilot.press('escape')
            await pilot.pause()
            await detail.action_show_logs()
            await pilot.pause()
            assert isinstance(app.screen, PodLogsScreen)
            log = app.screen.query_one('#pod-logs', Log)
            assert any('hello from' in line for line in log.lines)

    asyncio.run(_run())


class _FakeSock:
    def __init__(self, closed: threading.Event) -> None:
        self._closed = closed

    def shutdown(self, _how: int) -> None:
        self._closed.set()


class _BlockingLogStream:
    """Stays open until the socket is shut down — models a follow=True HTTP body."""

    def __init__(self) -> None:
        self._chunks = [b'hello from stream\n']
        self._index = 0
        self._closed = threading.Event()
        self.closed = False
        self.close_calls = 0
        self._connection = type('Conn', (), {})()
        self._connection.sock = _FakeSock(self._closed)

    def __iter__(self) -> '_BlockingLogStream':
        return self

    def __next__(self) -> bytes:
        if self._index < len(self._chunks):
            chunk = self._chunks[self._index]
            self._index += 1
            return chunk
        self._closed.wait()
        raise StopIteration

    def close(self) -> None:
        self.close_calls += 1
        time.sleep(2)
        self.closed = True
        self._closed.set()

    def release_conn(self) -> None:
        self.close()


class FollowCluster(FakeCluster):
    def watch_pod_logs(
        self,
        namespace: str,
        name: str,
        stop: threading.Event,
        on_line: object,
        on_error: object,
        *,
        container: str | None = None,
        tail_lines: int = 100,
        timestamps: bool = True,
        previous: bool = False,
        on_open: object | None = None,
    ) -> None:
        from roomlamp.k8s.logs import close_log_stream, iter_log_lines

        stream = _BlockingLogStream()
        if callable(on_open):
            on_open(stream)
        if stop.is_set():
            close_log_stream(stream)
            return
        try:
            for line in iter_log_lines(stream):
                if stop.is_set():
                    break
                if callable(on_line):
                    on_line(line)
        finally:
            close_log_stream(stream)


def test_leaving_followed_logs_returns_to_pod_list_quickly() -> None:
    app = RoomlampApp(_info(), cluster=FollowCluster(), enable_watch=True)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot)
            screen = app.screen
            assert isinstance(screen, PodListScreen)
            await screen._open_detail('default/web')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, PodDetailScreen)
            await detail.action_show_logs()
            await pilot.pause()
            assert isinstance(app.screen, PodLogsScreen)
            started = time.monotonic()
            await pilot.press('escape')
            await pilot.pause()
            assert isinstance(app.screen, PodDetailScreen)
            assert time.monotonic() - started < 1

    asyncio.run(asyncio.wait_for(_run(), timeout=8))
