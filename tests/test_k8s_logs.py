import socket
import threading
import time

from roomlamp.k8s.logs import (
    DEFAULT_TAIL_LINES,
    interrupt_log_stream,
    iter_log_lines,
    read_pod_logs,
    watch_pod_logs,
)


class _Core:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.kwargs: dict[str, object] = {}

    def read_namespaced_pod_log(self, name: str, namespace: str, **kwargs: object) -> object:
        assert name == 'web'
        assert namespace == 'default'
        self.kwargs = kwargs
        return self.payload


def test_read_pod_logs_uses_headlamp_defaults() -> None:
    core = _Core('hello\nworld\n')
    text = read_pod_logs(core, 'default', 'web', container='app')
    assert text == 'hello\nworld\n'
    assert core.kwargs['follow'] is False
    assert core.kwargs['tail_lines'] == DEFAULT_TAIL_LINES
    assert core.kwargs['timestamps'] is True
    assert core.kwargs['container'] == 'app'


def test_iter_log_lines_splits_chunks() -> None:
    assert list(iter_log_lines('a\nb\n')) == ['a', 'b']
    assert list(iter_log_lines([b'hel', b'lo\nwor', b'ld\n'])) == ['hello', 'world']


def test_watch_pod_logs_emits_lines() -> None:
    core = _Core(['one\n', 'two\n'])
    stop = threading.Event()
    lines: list[str] = []
    errors: list[str] = []
    watch_pod_logs(core, 'default', 'web', stop, lines.append, errors.append, container='app')
    assert lines == ['one', 'two']
    assert errors == []
    assert core.kwargs['follow'] is True
    assert core.kwargs['_preload_content'] is False


def test_interrupt_log_stream_shuts_down_socket_without_close() -> None:
    closed = threading.Event()

    class Sock:
        def shutdown(self, how: int) -> None:
            assert how == socket.SHUT_RDWR
            closed.set()

    class Conn:
        sock = Sock()

    class Resp:
        def __init__(self) -> None:
            self._connection = Conn()
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            time.sleep(2)

    resp = Resp()
    started = time.monotonic()
    interrupt_log_stream(resp)
    assert closed.is_set()
    assert resp.close_calls == 0
    assert time.monotonic() - started < 0.5
