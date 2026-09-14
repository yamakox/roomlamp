"""Pod log viewer with optional follow."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Header, Log, Static

from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.logs import DEFAULT_TAIL_LINES, close_log_stream, interrupt_log_stream
from roomlamp.ui.screens.containers import ContainerScreen
from roomlamp.ui.status import set_status, status_widget


class PodLogLine(Message):
    def __init__(self, line: str) -> None:
        super().__init__()
        self.line = line


class PodLogStatus(Message):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class PodLogsScreen(Screen[None]):
    BINDINGS = [
        ('c', 'pick_container', 'Container'),
        ('r', 'refresh', 'Refresh'),
        ('escape', 'close_logs', 'Back'),
        ('backspace', 'close_logs', 'Back'),
    ]

    def __init__(
        self,
        cluster: Any,
        namespace: str,
        name: str,
        containers: tuple[str, ...],
        container: str,
        enable_watch: bool = True,
    ) -> None:
        super().__init__()
        self.cluster = cluster
        self.namespace = namespace
        self.pod_name = name
        self.containers = containers
        self.container = container
        self.enable_watch = enable_watch
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None
        self._log_stream: object | None = None

    def on_mount(self) -> None:
        self._set_subtitle()
        self.run_worker(self._load, exclusive=True, group='pod-logs')

    def on_screen_suspend(self) -> None:
        # Stop follow before Textual waits for child message pumps to exit.
        self._stop_follow()

    def on_unmount(self) -> None:
        self._stop_follow()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            status_widget('logs-status'),
            Log(id='pod-logs', highlight=False, max_lines=10000),
            id='logs-wrap',
        )
        yield Footer()

    def action_close_logs(self) -> None:
        self._stop_follow()
        self.app.pop_screen()

    def action_pick_container(self) -> None:
        if not self.containers:
            return
        self.app.push_screen(
            ContainerScreen(self.containers, self.container),
            callback=self._on_container_chosen,
        )

    def _on_container_chosen(self, chosen: str | None) -> None:
        if chosen is None or chosen == self.container:
            return
        self.container = chosen
        self.run_worker(self._load, exclusive=True, group='pod-logs')

    async def action_refresh(self) -> None:
        await self._load()

    async def _load(self) -> None:
        self._stop_follow()
        self._set_subtitle()
        follow = self.enable_watch and hasattr(self.cluster, 'watch_pod_logs')
        if follow:
            self._set_status('')
            self._clear_log()
            self._start_follow()
            return
        try:
            text = await asyncio.to_thread(self._read)
        except Exception as exc:
            self._set_status(api_error_message(exc))
            return
        self._show_text(text)
        self._set_status('')

    def _read(self) -> str:
        return self.cluster.read_pod_logs(
            self.namespace,
            self.pod_name,
            container=self.container or None,
            tail_lines=DEFAULT_TAIL_LINES,
            timestamps=True,
        )

    def _start_follow(self) -> None:
        stop = threading.Event()
        self._watch_stop = stop

        def _emit_line(line: str) -> None:
            try:
                self.post_message(PodLogLine(line))
            except Exception:
                pass

        def _emit_status(message: str) -> None:
            try:
                self.post_message(PodLogStatus(message))
            except Exception:
                pass

        def _run() -> None:
            self.cluster.watch_pod_logs(
                self.namespace,
                self.pod_name,
                stop,
                _emit_line,
                _emit_status,
                container=self.container or None,
                tail_lines=DEFAULT_TAIL_LINES,
                timestamps=True,
                on_open=self._attach_log_stream,
            )

        thread = threading.Thread(target=_run, daemon=True)
        self._watch_thread = thread
        thread.start()

    def _attach_log_stream(self, resp: object) -> None:
        self._log_stream = resp
        if self._watch_stop is not None and self._watch_stop.is_set():
            close_log_stream(resp)

    def _stop_follow(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
        stream = self._log_stream
        self._log_stream = None
        if stream is not None:
            interrupt_log_stream(stream)
            threading.Thread(target=close_log_stream, args=(stream,), daemon=True).start()
        self._watch_stop = None
        self._watch_thread = None

    def on_pod_log_line(self, event: PodLogLine) -> None:
        if self._watch_stop is None:
            return
        self.query_one('#pod-logs', Log).write_line(event.line)

    def on_pod_log_status(self, event: PodLogStatus) -> None:
        self._set_status(event.message)

    def _show_text(self, text: str) -> None:
        log = self.query_one('#pod-logs', Log)
        log.clear()
        if text:
            log.write(text if text.endswith('\n') else text + '\n')

    def _clear_log(self) -> None:
        self.query_one('#pod-logs', Log).clear()

    def _set_status(self, message: str) -> None:
        set_status(self.query_one('#logs-status', Static), message)

    def _set_subtitle(self) -> None:
        container = self.container or '(default)'
        self.sub_title = f'{self.namespace}/{self.pod_name} / {container}'
