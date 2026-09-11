"""Interactive Pod exec via the official client's websocket stream (kubectl exec)."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kubernetes.client import CoreV1Api
from kubernetes.stream import stream
from kubernetes.stream.ws_client import ERROR_CHANNEL, RESIZE_CHANNEL

from roomlamp.k8s.errors import api_error_message

LINUX_SHELLS = ('bash', '/bin/bash', 'sh', '/bin/sh')
WINDOWS_SHELLS = ('powershell.exe', 'cmd.exe')
FALLBACK_SHELLS = LINUX_SHELLS + WINDOWS_SHELLS

DETACH_KEY = 'ctrl+right_square_bracket'
CONTAINER_KEY = 'f2'

_SGR_OSC_RE = re.compile(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-9;:]*m|\x1b[@-Z\\-_]')
_CTRL_KEYS = {f'ctrl+{chr(ord("a") + index)}': chr(index + 1) for index in range(26)}
_SPECIAL_KEYS = {
    'enter': '\r',
    'return': '\r',
    'backspace': '\x08',
    'tab': '\t',
    'escape': '\x1b',
    'up': '\x1b[A',
    'down': '\x1b[B',
    'right': '\x1b[C',
    'left': '\x1b[D',
    'home': '\x1b[H',
    'end': '\x1b[F',
    'insert': '\x1b[2~',
    'delete': '\x1b[3~',
    'pageup': '\x1b[5~',
    'pagedown': '\x1b[6~',
    'shift+tab': '\x1b[Z',
}


@dataclass(frozen=True)
class ExecPoll:
    stdout: str
    stderr: str
    error: str
    is_open: bool


def shells_for_node_os(node_os: str | None) -> tuple[str, ...]:
    """Return Headlamp's shell fallback list for a pod's node OS selector."""
    if node_os == 'linux':
        return LINUX_SHELLS
    if node_os == 'windows':
        return WINDOWS_SHELLS
    return FALLBACK_SHELLS


def display_text(text: str) -> str:
    """Strip colors and OSC. Keep CR, backspace, and CSI cursor/erase sequences."""
    cleaned = _SGR_OSC_RE.sub('', text)
    return cleaned.replace('\r\n', '\n')


def encode_exec_key(key: str, character: str | None) -> str:
    """Map a Textual key event to bytes for a remote TTY.

    ``f2`` and ``ctrl+]`` stay in the TUI (container picker / detach).
    """
    if key in {CONTAINER_KEY, DETACH_KEY}:
        return ''
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    if key in _CTRL_KEYS:
        return _CTRL_KEYS[key]
    if character:
        return character
    return ''


def is_successful_exit_error(text: str) -> bool:
    """True when the exec error channel reports a clean process exit (Headlamp)."""
    error = _parse_status(text)
    if error is None:
        return False
    metadata = error.get('metadata')
    return (not metadata) and error.get('status') == 'Success'


def is_shell_not_found_error(text: str) -> bool:
    """True when kubelet failed to start the command (Headlamp InternalError heuristic)."""
    error = _parse_status(text)
    if error is None:
        return False
    return error.get('code') == 500 and error.get('status') == 'Failure' and error.get('reason') == 'InternalError'


def is_windows_shell_not_found(text: str) -> bool:
    return 'The system cannot find the file specified' in text


def open_pod_exec(
    core: CoreV1Api,
    namespace: str,
    name: str,
    *,
    container: str,
    command: str,
    stream_fn: Callable[..., Any] = stream,
) -> ExecConnection:
    """Open an interactive TTY exec (stdin/stdout/stderr), matching Headlamp Terminal.tsx."""
    client = stream_fn(
        core.connect_get_namespaced_pod_exec,
        name,
        namespace,
        command=[command],
        container=container or None,
        stderr=True,
        stdin=True,
        stdout=True,
        tty=True,
        _preload_content=False,
    )
    return ExecConnection(client)


def follow_pod_exec(
    session: ExecSession,
    stop: threading.Event,
    on_output: Callable[[str], None],
    on_error: Callable[[str], None],
) -> str:
    """Read the exec stream until it ends. Returns ``success``, ``not_found``, or ``closed``."""
    try:
        while not stop.is_set():
            poll = session.poll(timeout=0)
            if poll.stdout:
                on_output(display_text(poll.stdout))
            if poll.stderr:
                if is_windows_shell_not_found(poll.stderr):
                    return 'not_found'
                on_output(display_text(poll.stderr))
            if poll.error:
                if is_successful_exit_error(poll.error):
                    return 'success'
                if is_shell_not_found_error(poll.error):
                    return 'not_found'
                on_error(poll.error)
                return 'closed'
            if not poll.is_open:
                return 'closed'
            if not poll.stdout and not poll.stderr and not poll.error:
                if stop.wait(0.05):
                    return 'closed'
        return 'closed'
    except Exception as exc:
        if not stop.is_set():
            on_error(api_error_message(exc))
        return 'closed'
    finally:
        session.close()


def _parse_status(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class ExecSession:
    """Duck-typed exec websocket used by the TUI and tests."""

    def poll(self, timeout: float = 0) -> ExecPoll:
        raise NotImplementedError

    def write_stdin(self, data: str) -> None:
        raise NotImplementedError

    def write_resize(self, cols: int, rows: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class ExecConnection(ExecSession):
    """Thread-safe wrapper around ``kubernetes.stream``'s ``WSClient``."""

    def __init__(self, client: object) -> None:
        self._client = client
        self._lock = threading.Lock()

    def poll(self, timeout: float = 0) -> ExecPoll:
        with self._lock:
            updater = getattr(self._client, 'update', None)
            if updater is not None:
                updater(timeout=timeout)
            stdout = self._take('peek_stdout', 'read_stdout')
            stderr = self._take('peek_stderr', 'read_stderr')
            error = self._take_channel(ERROR_CHANNEL)
            return ExecPoll(stdout, stderr, error, self._is_open_unlocked())

    def write_stdin(self, data: str) -> None:
        if not data:
            return
        with self._lock:
            if not self._is_open_unlocked():
                return
            writer = getattr(self._client, 'write_stdin', None)
            if writer is not None:
                writer(data)

    def write_resize(self, cols: int, rows: int) -> None:
        payload = json.dumps({'Width': int(cols), 'Height': int(rows)})
        with self._lock:
            if not self._is_open_unlocked():
                return
            writer = getattr(self._client, 'write_channel', None)
            if writer is not None:
                writer(RESIZE_CHANNEL, payload)

    def close(self) -> None:
        with self._lock:
            closer = getattr(self._client, 'close', None)
            if closer is None:
                return
            try:
                closer()
            except Exception:
                pass

    def _take(self, peek_name: str, read_name: str) -> str:
        peek = getattr(self._client, peek_name, None)
        reader = getattr(self._client, read_name, None)
        if peek is None or reader is None:
            return ''
        data = peek()
        if not data:
            return ''
        return reader() or ''

    def _take_channel(self, channel: int) -> str:
        peek = getattr(self._client, 'peek_channel', None)
        reader = getattr(self._client, 'read_channel', None)
        if peek is None or reader is None:
            return ''
        data = peek(channel)
        if not data:
            return ''
        return reader(channel) or ''

    def _is_open_unlocked(self) -> bool:
        checker = getattr(self._client, 'is_open', None)
        if checker is None:
            return False
        return bool(checker())
