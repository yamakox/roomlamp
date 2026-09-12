import asyncio
import threading
import time

from textual.widgets import Log

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.exec import ExecPoll
from roomlamp.k8s.resources import ALL_NAMESPACES, PodDetail, PodSummary
from roomlamp.ui.screens.containers import ContainerScreen
from roomlamp.ui.screens.exec import ExecView, PodExecScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.screens.pods import PodListScreen


class FakeExecSession:
    def __init__(self, command: str, *, fail: bool = False, output: str = 'ready\n') -> None:
        self.command = command
        self.fail = fail
        self._pending = '' if fail else output
        self.stdin: list[str] = []
        self.resize: list[tuple[int, int]] = []
        self._open = not fail
        self._closed = threading.Event()
        self._lock = threading.Lock()

    def poll(self, timeout: float = 0) -> ExecPoll:
        with self._lock:
            if self.fail:
                self._open = False
                return ExecPoll(
                    '',
                    '',
                    '{"code":500,"status":"Failure","reason":"InternalError"}',
                    False,
                )
            out = self._pending
            self._pending = ''
            is_open = self._open
        if not out and is_open:
            self._closed.wait(timeout if timeout else 0.05)
            with self._lock:
                out = self._pending
                self._pending = ''
                is_open = self._open
        return ExecPoll(out, '', '', is_open)

    def write_stdin(self, data: str) -> None:
        with self._lock:
            self.stdin.append(data)
            self._pending += data.replace('\r', '\n')

    def write_resize(self, cols: int, rows: int) -> None:
        self.resize.append((cols, rows))

    def close(self) -> None:
        with self._lock:
            self._open = False
        self._closed.set()


class FakeCluster:
    def __init__(self) -> None:
        self.pods = [PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a')]
        self.exec_calls: list[tuple[str, str, str, str]] = []
        self.sessions: list[FakeExecSession] = []

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
            container_names=('app', 'sidecar'),
            default_container='app',
            node_os='linux',
        )

    def open_pod_exec(self, namespace: str, name: str, *, container: str, command: str) -> FakeExecSession:
        self.exec_calls.append((namespace, name, container, command))
        fail = command == 'bash'
        session = FakeExecSession(command, fail=fail, output=f'{command}-ready\n')
        self.sessions.append(session)
        return session


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


async def _open_exec(app: RoomlampApp, pilot: object) -> PodExecScreen:
    await open_kind(app, pilot)
    screen = app.screen
    assert isinstance(screen, PodListScreen)
    await screen._open_detail('default/web')
    await pilot.pause()
    detail = app.screen
    assert isinstance(detail, PodDetailScreen)
    await detail.action_show_exec()
    await pilot.pause()
    exec_screen = app.screen
    assert isinstance(exec_screen, PodExecScreen)
    return exec_screen


async def _wait_for_log(pilot: object, screen: PodExecScreen, needle: str) -> str:
    for _ in range(40):
        text = ''.join(screen.query_one('#pod-exec', Log).lines)
        if needle in text:
            return text
        await pilot.pause()
    raise AssertionError(f'log did not contain {needle!r}')


def test_pod_exec_opens_from_detail_and_falls_back_shell() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            screen = await _open_exec(app, pilot)
            text = await _wait_for_log(pilot, screen, '/bin/bash-ready')
            assert 'Trying to run "bash"' in text
            assert 'Failed to run "bash"' in text
            assert 'Trying to run "/bin/bash"' in text
            assert cluster.exec_calls[0] == ('default', 'web', 'app', 'bash')
            assert cluster.exec_calls[1] == ('default', 'web', 'app', '/bin/bash')
            live = cluster.sessions[-1]
            await pilot.press('l')
            await pilot.pause()
            assert 'l' in live.stdin
            await _wait_for_log(pilot, screen, 'l')

    asyncio.run(_run())


def test_pod_exec_q_goes_to_session_and_detach_returns() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            screen = await _open_exec(app, pilot)
            await _wait_for_log(pilot, screen, '/bin/bash-ready')
            live = cluster.sessions[-1]
            started = time.monotonic()
            await pilot.press('q')
            await pilot.pause()
            assert isinstance(app.screen, PodExecScreen)
            assert 'q' in live.stdin
            await pilot.press('ctrl+right_square_bracket')
            await pilot.pause()
            assert isinstance(app.screen, PodDetailScreen)
            assert time.monotonic() - started < 1

    asyncio.run(asyncio.wait_for(_run(), timeout=8))


def test_pod_exec_keeps_session_after_picking_current_container() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            screen = await _open_exec(app, pilot)
            await _wait_for_log(pilot, screen, '/bin/bash-ready')
            live = cluster.sessions[-1]
            calls = len(cluster.exec_calls)
            await pilot.press('f2')
            await pilot.pause()
            assert isinstance(app.screen, ContainerScreen)
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, PodExecScreen)
            assert len(cluster.exec_calls) == calls
            view = app.screen.query_one('#pod-exec', ExecView)
            assert view.has_focus
            await pilot.press('z')
            await pilot.pause()
            assert 'z' in live.stdin
            await _wait_for_log(pilot, screen, 'z')

    asyncio.run(_run())


def test_pod_exec_switch_container_starts_new_session() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            screen = await _open_exec(app, pilot)
            await _wait_for_log(pilot, screen, '/bin/bash-ready')
            await pilot.press('f2')
            await pilot.pause()
            await pilot.press('down')
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, PodExecScreen)
            await _wait_for_log(pilot, app.screen, '/bin/bash-ready')
            assert cluster.exec_calls[-1] == ('default', 'web', 'sidecar', '/bin/bash')

    asyncio.run(_run())


def test_pod_exec_shows_cursor_and_sends_arrows() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            screen = await _open_exec(app, pilot)
            await _wait_for_log(pilot, screen, '/bin/bash-ready')
            view = screen.query_one('#pod-exec', ExecView)
            assert view.has_focus
            view.clear()
            prompt = 'root@host:/# echo "abc"'
            view.write(prompt)
            await pilot.pause()
            view.cursor_visible = True
            y = view._cursor_y()
            assert y < view.line_count
            lit = view._render_line_strip(y, view.rich_style)
            assert prompt in lit.text
            assert lit.cell_length == len(prompt) + 1
            painted = view._render_line(y, 0, 80)
            assert prompt in painted.text
            view.cursor_visible = False
            dim = view._render_line_strip(y, view.rich_style)
            assert dim.cell_length == len(prompt)
            view.write('\n')
            await pilot.pause()
            view.cursor_visible = True
            assert view._lines[-1] == ''
            assert view.line_count == len(view._lines)
            after_enter = view._render_line_strip(view._cursor_y(), view.rich_style)
            assert after_enter.cell_length == 1
            live = cluster.sessions[-1]
            await pilot.press('up')
            await pilot.pause()
            assert '\x1b[A' in live.stdin
            view.write('abcde')
            view.write('\x08\x08')
            assert view._lines[-1].endswith('abcde')
            assert view._cursor_x == 3
            view.write('\x1b[C')
            assert view._cursor_x == 4
            view.write('\x1b[K')
            assert view._lines[-1].endswith('abcd')
            view.write('\r')
            assert view._cursor_x == 0
            assert 'abcd' in view._lines[-1]
            view.clear()
            view.write('abcde')
            view.write('\x08\x1b[K')
            assert view._lines[-1] == 'abcd'
            await pilot.press('backspace')
            await pilot.pause()
            assert '\x08' in live.stdin

    asyncio.run(_run())


def test_exec_view_inserts_in_the_middle_of_a_line() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            screen = await _open_exec(app, pilot)
            await _wait_for_log(pilot, screen, '/bin/bash-ready')
            view = screen.query_one('#pod-exec', ExecView)
            view.clear()
            view.write('echo "abcde"')
            view.write('\x1b[6D')
            view.write(''.join(f'\x1b[@{char}' for char in 'ABCDE'))
            assert view._lines[-1] == 'echo "ABCDEabcde"'
            view.clear()
            view.write('echo "abcde"')
            view.write('\x1b[6D')
            view.write('\x1b[4hABCDE\x1b[4l')
            assert view._lines[-1] == 'echo "ABCDEabcde"'
            view.clear()
            view.write('ace')
            view.write('\x1b[2D')
            view.write('\x1b[2@XY')
            assert view._lines[-1] == 'aXYce'
            view.clear()
            view.write('ace')
            view.write('\x1b[4l')
            view.write('\x1b[2D')
            view.write('\x1b[@b')
            assert view._lines[-1] == 'abce'
            view.clear()
            view.write('old line')
            view.write('\rnew')
            assert view._lines[-1] == 'new line'
            view.clear()
            view.write('abcde')
            view.write('\x1b[4l')
            view.write('\x1b[5D')
            view.write('XY')
            assert view._lines[-1] == 'XYcde'
            view.write('\x1b[4h')
            view.write('\x1b[2D')
            view.write('Z')
            assert view._lines[-1] == 'ZXYcde'
            view.clear()
            view.write('abcd')
            view.write('\x08 \x08')
            assert view._lines[-1] == 'abc '
            assert view._cursor_x == 3

    asyncio.run(_run())
