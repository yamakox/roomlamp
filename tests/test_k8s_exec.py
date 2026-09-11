import json
import threading

from kubernetes.stream.ws_client import ERROR_CHANNEL, RESIZE_CHANNEL

from roomlamp.k8s.exec import (
    FALLBACK_SHELLS,
    LINUX_SHELLS,
    WINDOWS_SHELLS,
    ExecConnection,
    ExecPoll,
    display_text,
    encode_exec_key,
    follow_pod_exec,
    is_shell_not_found_error,
    is_successful_exit_error,
    is_windows_shell_not_found,
    open_pod_exec,
    shells_for_node_os,
)


class _Core:
    def connect_get_namespaced_pod_exec(self, name: str, namespace: str, **kwargs: object) -> None:
        raise AssertionError('stream_fn should intercept the API call')


class _Client:
    def __init__(self) -> None:
        self.closed = False
        self.stdin: list[str] = []
        self.channels: list[tuple[int, str]] = []
        self.stdout = 'hi\n'
        self.stderr = ''
        self.error = ''
        self.open = True
        self.update_calls = 0

    def is_open(self) -> bool:
        return self.open and not self.closed

    def update(self, timeout: float = 0) -> None:
        self.update_calls += 1

    def peek_stdout(self) -> str:
        return self.stdout

    def read_stdout(self, timeout: float | None = None) -> str:
        text = self.stdout
        self.stdout = ''
        return text

    def peek_stderr(self) -> str:
        return self.stderr

    def read_stderr(self, timeout: float | None = None) -> str:
        text = self.stderr
        self.stderr = ''
        return text

    def peek_channel(self, channel: int) -> str:
        return self.error if channel == ERROR_CHANNEL else ''

    def read_channel(self, channel: int, timeout: float = 0) -> str:
        if channel != ERROR_CHANNEL:
            return ''
        text = self.error
        self.error = ''
        return text

    def write_stdin(self, data: str) -> None:
        self.stdin.append(data)

    def write_channel(self, channel: int, data: str) -> None:
        self.channels.append((channel, data))

    def close(self) -> None:
        self.closed = True
        self.open = False


class _Session:
    def __init__(self, polls: list[ExecPoll]) -> None:
        self.polls = list(polls)
        self.closed = False
        self.stdin: list[str] = []

    def poll(self, timeout: float = 0) -> ExecPoll:
        if self.polls:
            return self.polls.pop(0)
        return ExecPoll('', '', '', False)

    def write_stdin(self, data: str) -> None:
        self.stdin.append(data)

    def write_resize(self, cols: int, rows: int) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_shells_for_node_os_match_headlamp() -> None:
    assert shells_for_node_os('linux') == LINUX_SHELLS
    assert shells_for_node_os('windows') == WINDOWS_SHELLS
    assert shells_for_node_os(None) == FALLBACK_SHELLS
    assert shells_for_node_os('darwin') == FALLBACK_SHELLS


def test_encode_exec_key_maps_tty_keys_and_keeps_chrome_keys() -> None:
    assert encode_exec_key('enter', None) == '\r'
    assert encode_exec_key('backspace', None) == '\x08'
    assert encode_exec_key('ctrl+h', None) == '\x08'
    assert encode_exec_key('up', None) == '\x1b[A'
    assert encode_exec_key('ctrl+c', None) == '\x03'
    assert encode_exec_key('a', 'a') == 'a'
    assert encode_exec_key('f2', None) == ''
    assert encode_exec_key('ctrl+right_square_bracket', None) == ''


def test_display_text_strips_colors_and_keeps_cursor_csi() -> None:
    assert display_text('\x1b[32mhi\x1b[0m\r\nthere\r') == 'hi\nthere\r'
    assert display_text('ab\x08') == 'ab\x08'
    assert display_text('ab\x1b[2D') == 'ab\x1b[2D'
    assert display_text('a\x1b[2@b') == 'a\x1b[2@b'
    assert display_text('\x1b[4hX\x1b[4l') == '\x1b[4hX\x1b[4l'


def test_error_channel_status_helpers() -> None:
    success = '{"metadata":{},"status":"Success"}'
    missing = '{"code":500,"status":"Failure","reason":"InternalError","message":"no bash"}'
    other = '{"code":403,"status":"Failure","reason":"Forbidden"}'
    assert is_successful_exit_error(success)
    assert is_shell_not_found_error(missing)
    assert not is_shell_not_found_error(other)
    assert not is_successful_exit_error(missing)
    assert is_windows_shell_not_found('The system cannot find the file specified')


def test_open_pod_exec_uses_tty_stream_kwargs() -> None:
    seen: dict[str, object] = {}
    client = _Client()

    def _stream(method: object, name: str, namespace: str, **kwargs: object) -> _Client:
        seen['method'] = method
        seen['name'] = name
        seen['namespace'] = namespace
        seen.update(kwargs)
        return client

    core = _Core()
    conn = open_pod_exec(
        core,
        'default',
        'web',
        container='app',
        command='bash',
        stream_fn=_stream,
    )
    assert isinstance(conn, ExecConnection)
    assert seen['name'] == 'web'
    assert seen['namespace'] == 'default'
    assert seen['command'] == ['bash']
    assert seen['container'] == 'app'
    assert seen['stdin'] is True
    assert seen['stdout'] is True
    assert seen['stderr'] is True
    assert seen['tty'] is True
    assert seen['_preload_content'] is False
    conn.write_stdin('ls\r')
    conn.write_resize(80, 24)
    assert client.stdin == ['ls\r']
    assert client.channels == [(RESIZE_CHANNEL, json.dumps({'Width': 80, 'Height': 24}))]
    conn.close()
    assert client.closed is True


def test_follow_pod_exec_emits_output_then_success() -> None:
    session = _Session(
        [
            ExecPoll('prompt$ ', '', '', True),
            ExecPoll('', '', '{"metadata":{},"status":"Success"}', False),
        ]
    )
    stop = threading.Event()
    lines: list[str] = []
    errors: list[str] = []
    result = follow_pod_exec(session, stop, lines.append, errors.append)
    assert result == 'success'
    assert lines == ['prompt$ ']
    assert errors == []
    assert session.closed is True


def test_follow_pod_exec_detects_missing_shell() -> None:
    session = _Session([ExecPoll('', '', '{"code":500,"status":"Failure","reason":"InternalError"}', False)])
    stop = threading.Event()
    result = follow_pod_exec(session, stop, lambda _text: None, lambda _text: None)
    assert result == 'not_found'
    assert session.closed is True
