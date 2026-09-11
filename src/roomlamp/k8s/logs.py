"""Read and follow Pod container logs with the official client."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator

from kubernetes.client import CoreV1Api

DEFAULT_TAIL_LINES = 100
LogLineCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


def read_pod_logs(
    core: CoreV1Api,
    namespace: str,
    name: str,
    *,
    container: str | None = None,
    tail_lines: int = DEFAULT_TAIL_LINES,
    timestamps: bool = True,
    previous: bool = False,
) -> str:
    """Return a snapshot of the last log lines (Headlamp default tail is 100)."""
    kwargs: dict[str, object] = {
        'follow': False,
        'previous': previous,
        'tail_lines': tail_lines,
        'timestamps': timestamps,
    }
    if container:
        kwargs['container'] = container
    text = core.read_namespaced_pod_log(name, namespace, **kwargs)
    return text or ''


def watch_pod_logs(
    core: CoreV1Api,
    namespace: str,
    name: str,
    stop: threading.Event,
    on_line: LogLineCallback,
    on_error: ErrorCallback,
    *,
    container: str | None = None,
    tail_lines: int = DEFAULT_TAIL_LINES,
    timestamps: bool = True,
    previous: bool = False,
    on_open: Callable[[object], None] | None = None,
) -> None:
    """Follow logs in the calling thread until ``stop`` is set or the stream ends."""
    kwargs: dict[str, object] = {
        'follow': True,
        'previous': previous,
        'tail_lines': tail_lines,
        'timestamps': timestamps,
        '_preload_content': False,
    }
    if container:
        kwargs['container'] = container
    try:
        resp = core.read_namespaced_pod_log(name, namespace, **kwargs)
    except Exception as exc:
        if not stop.is_set():
            on_error(str(exc))
        return
    if on_open is not None:
        on_open(resp)
    if stop.is_set():
        close_log_stream(resp)
        return
    try:
        for line in iter_log_lines(resp):
            if stop.is_set():
                break
            on_line(line)
    except Exception as exc:
        if not stop.is_set():
            on_error(str(exc))
    finally:
        close_log_stream(resp)


def iter_log_lines(resp: object) -> Iterator[str]:
    """Yield decoded log lines from a string snapshot or a streaming HTTP body."""
    if isinstance(resp, str):
        yield from resp.splitlines()
        return
    buffer = ''
    for chunk in resp:
        if isinstance(chunk, bytes):
            text = chunk.decode('utf-8', errors='replace')
        else:
            text = str(chunk)
        buffer += text
        while '\n' in buffer:
            line, buffer = buffer.split('\n', 1)
            yield line.rstrip('\r')
        if stop_if_closed(resp):
            break
    if buffer:
        yield buffer.rstrip('\r')


def stop_if_closed(resp: object) -> bool:
    closed = getattr(resp, 'closed', None)
    return bool(closed) if closed is not None else False


def interrupt_log_stream(resp: object) -> None:
    """Unblock a follow reader without draining the HTTP body on this thread.

    ``HTTPResponse.close()`` waits for the socket read in the follow thread, which
    freezes the TUI. Shutdown wakes that read; ``close_log_stream`` can run later.
    """
    sock = _log_stream_socket(resp)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        return
    closer = getattr(resp, 'close', None)
    if closer is not None:
        try:
            closer()
        except Exception:
            pass


def close_log_stream(resp: object) -> None:
    interrupt_log_stream(resp)
    for method in ('close', 'release_conn'):
        closer = getattr(resp, method, None)
        if closer is None:
            continue
        try:
            closer()
        except Exception:
            pass


def _log_stream_socket(resp: object) -> object | None:
    conn = getattr(resp, '_connection', None) or getattr(resp, 'connection', None)
    sock = getattr(conn, 'sock', None)
    if sock is not None:
        return sock
    fp = getattr(resp, '_fp', None) or getattr(resp, 'fp', None)
    raw = getattr(fp, 'raw', None)
    sock = getattr(raw, '_sock', None)
    if sock is not None:
        return sock
    return None
