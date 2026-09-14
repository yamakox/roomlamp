"""Interactive Pod exec (Headlamp Terminal / Exec)."""

from __future__ import annotations

import re
import threading
from typing import Any, ClassVar

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.geometry import Size
from textual.message import Message
from textual.screen import Screen
from textual.strip import Strip
from textual.widgets import Footer, Header, Log, Static

from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.exec import (
    CONTAINER_KEY,
    DETACH_KEY,
    encode_exec_key,
    follow_pod_exec,
    shells_for_node_os,
)
from roomlamp.ui.screens.containers import ContainerScreen
from roomlamp.ui.status import set_status, status_widget

_CSI_RE = re.compile(r'\x1b\[([0-9;?]*)([A-Za-z@-~])')


class PodExecOutput(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class PodExecStatus(Message):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class PodExecFinished(Message):
    def __init__(self, result: str) -> None:
        super().__init__()
        self.result = result


class ExecView(Log, inherit_bindings=False):
    """Log that keeps PTY keys and draws a blinking block cursor at the end."""

    ALLOW_SELECT = False
    BINDINGS: list[Binding] = []
    COMPONENT_CLASSES: ClassVar[set[str]] = {'exec-view--cursor'}
    DEFAULT_CSS = """
    ExecView {
        &>.exec-view--cursor {
            background: $input-cursor-background;
            color: $input-cursor-foreground;
            text-style: $input-cursor-text-style;
        }
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cursor_visible = True
        self._cursor_x = 0
        self._insert_mode = False
        self._overwrite_after_cr = False

    def on_mount(self) -> None:
        super().on_mount()
        self._ensure_cursor_row()
        self.set_interval(0.5, self._blink_cursor)

    def clear(self) -> ExecView:
        super().clear()
        self._cursor_x = 0
        self._insert_mode = False
        self._overwrite_after_cr = False
        return self

    @property
    def line_count(self) -> int:
        """Include the trailing empty line so the cursor cell is actually painted."""
        if not self._lines:
            return 1
        return len(self._lines)

    def _blink_cursor(self) -> None:
        self.cursor_visible = not self.cursor_visible
        self._refresh_cursor_line()

    def _cursor_y(self) -> int:
        if not self._lines:
            return 0
        return len(self._lines) - 1

    def _ensure_line(self) -> None:
        if not self._lines:
            self._lines.append('')

    def _ensure_cursor_row(self) -> None:
        height = self.line_count
        width = max(self._width, 1)
        if self.virtual_size.height < height or self.virtual_size.width < width:
            self.virtual_size = Size(width, height)

    def _refresh_cursor_line(self) -> None:
        self._ensure_cursor_row()
        y = self._cursor_y()
        self._render_line_cache.discard(y)
        self.refresh()

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        rich_style = self.rich_style
        if not self._lines:
            line = self._line_strip('', rich_style, cursor=self.cursor_visible and y == 0)
            return line.crop_extend(scroll_x, scroll_x + width, rich_style)
        if y >= len(self._lines):
            return Strip.blank(width, rich_style)
        line = self._render_line_strip(y, rich_style)
        return line.crop_extend(scroll_x, scroll_x + width, rich_style).apply_offsets(scroll_x, y)

    def _render_line_strip(self, y: int, rich_style: Style) -> Strip:
        text = self._process_line(self._lines[y]) if y < len(self._lines) else ''
        return self._line_strip(text, rich_style, cursor=self.cursor_visible and y == self._cursor_y())

    def _line_strip(self, text: str, rich_style: Style, *, cursor: bool) -> Strip:
        cursor_style = self.get_component_rich_style('exec-view--cursor')
        line_text = Text(end='')
        if cursor:
            x = min(max(self._cursor_x, 0), len(text))
            if x < len(text):
                if x:
                    line_text.append(text[:x], rich_style)
                line_text.append(text[x], cursor_style)
                if x + 1 < len(text):
                    line_text.append(text[x + 1 :], rich_style)
            else:
                if text:
                    line_text.append(text, rich_style)
                line_text.append(' ', cursor_style)
        elif text:
            line_text.append(text, rich_style)
        else:
            return Strip([], 0)
        segments = [segment for segment in line_text.render(self.app.console) if segment.text]
        return Strip(segments, cell_len(line_text.plain))

    def write(self, data: str, scroll_end: bool | None = None) -> ExecView:
        """Write PTY output with a column cursor, CSI erase/insert, and insert mode."""
        if not data:
            return self
        index = 0
        length = len(data)
        while index < length:
            char = data[index]
            if char == '\x1b':
                match = _CSI_RE.match(data, index)
                if match is not None:
                    self._apply_csi(match.group(1), match.group(2))
                    index = match.end()
                    continue
                index += 1
                continue
            if char == '\r' and index + 1 < length and data[index + 1] == '\n':
                self._newline()
                index += 2
                continue
            if char == '\n':
                self._newline()
                index += 1
                continue
            if char == '\r':
                self._cursor_x = 0
                self._overwrite_after_cr = True
                index += 1
                continue
            if char in {'\x08', '\x7f'}:
                self._cursor_x = max(0, self._cursor_x - 1)
                index += 1
                continue
            if char in {'\x07', '\x0f', '\x0e'}:
                index += 1
                continue
            if char == '\t':
                next_tab = (self._cursor_x // 8 + 1) * 8
                while self._cursor_x < next_tab:
                    self._put_char(' ')
                index += 1
                continue
            if char >= ' ':
                self._put_char(char)
                index += 1
                continue
            index += 1
        self._sync_layout(scroll_end)
        return self

    def _put_char(self, char: str) -> None:
        self._ensure_line()
        line = self._lines[-1]
        x = self._cursor_x
        replace = (not self._insert_mode) or self._overwrite_after_cr
        if x < len(line) and not replace:
            self._lines[-1] = line[:x] + char + line[x:]
        elif x < len(line):
            self._lines[-1] = line[:x] + char + line[x + 1 :]
        elif x == len(line):
            self._lines[-1] = line + char
        else:
            self._lines[-1] = line + ' ' * (x - len(line)) + char
        self._cursor_x = x + 1

    def _newline(self) -> None:
        self._ensure_line()
        self._width = max(self._width, cell_len(self._lines[-1]))
        self._lines.append('')
        self._cursor_x = 0
        self._overwrite_after_cr = False

    def _apply_csi(self, params: str, final: str) -> None:
        self._ensure_line()
        line = self._lines[-1]
        private = params.startswith('?')
        nums = [int(part) if part else 0 for part in params.replace('?', '').split(';')] if params else []
        count = nums[0] if nums else 0
        if final in {'h', 'l'} and not private:
            enable = final == 'h'
            for mode in nums or [0]:
                if mode == 4:
                    self._insert_mode = enable
            return
        if final == 'D':
            self._overwrite_after_cr = False
            self._cursor_x = max(0, self._cursor_x - (count or 1))
            return
        if final == 'C':
            self._overwrite_after_cr = False
            self._cursor_x = min(len(line), self._cursor_x + (count or 1))
            return
        if final == 'G':
            self._overwrite_after_cr = False
            self._cursor_x = max(0, min(len(line), (count or 1) - 1))
            return
        if final == 'K':
            self._overwrite_after_cr = False
            mode = count
            if mode == 0:
                self._lines[-1] = line[: self._cursor_x]
            elif mode == 1:
                self._lines[-1] = ' ' * self._cursor_x + line[self._cursor_x :]
            else:
                self._lines[-1] = ''
                self._cursor_x = 0
            return
        if final == 'P':
            self._overwrite_after_cr = False
            delete = count or 1
            x = self._cursor_x
            self._lines[-1] = line[:x] + line[x + delete :]
            return
        if final == '@':
            self._overwrite_after_cr = False
            if self._insert_mode:
                return
            insert = count or 1
            x = self._cursor_x
            self._lines[-1] = line[:x] + (' ' * insert) + line[x:]

    def _sync_layout(self, scroll_end: bool | None) -> None:
        self._ensure_line()
        self._width = max(self._width, max((cell_len(line) for line in self._lines), default=0), 1)
        self.virtual_size = Size(self._width, self.line_count)
        self._render_line_cache.clear()
        auto_scroll = self.auto_scroll if scroll_end is None else scroll_end
        if auto_scroll:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        else:
            self.refresh()


class PodExecScreen(Screen[None]):
    BINDINGS = [
        Binding(DETACH_KEY, 'close_exec', 'Detach', priority=True),
        Binding(CONTAINER_KEY, 'pick_container', 'Container', priority=True),
    ]

    def __init__(
        self,
        cluster: Any,
        namespace: str,
        name: str,
        containers: tuple[str, ...],
        container: str,
        node_os: str | None = None,
    ) -> None:
        super().__init__()
        self.cluster = cluster
        self.namespace = namespace
        self.pod_name = name
        self.containers = containers
        self.container = container
        self.shells = shells_for_node_os(node_os)
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None
        self._session: Any = None
        self._reconnect_on_enter = False

    def on_mount(self) -> None:
        self._set_subtitle()
        self._focus_exec()
        self._start_session()

    def on_screen_resume(self) -> None:
        self._focus_exec()

    def on_unmount(self) -> None:
        self._stop_session()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            status_widget('exec-status'),
            ExecView(id='pod-exec', highlight=False, max_lines=10000),
            id='exec-wrap',
        )
        yield Footer()

    def action_close_exec(self) -> None:
        self._stop_session()
        self.app.pop_screen()

    def action_pick_container(self) -> None:
        if not self.containers:
            return
        self.app.push_screen(
            ContainerScreen(self.containers, self.container),
            callback=self._on_container_chosen,
        )

    def _on_container_chosen(self, chosen: str | None) -> None:
        if chosen is not None and chosen != self.container:
            self.container = chosen
            self._set_subtitle()
            self._start_session()
        self._focus_exec()

    def on_key(self, event: events.Key) -> None:
        if event.key in {DETACH_KEY, CONTAINER_KEY}:
            return
        event.stop()
        event.prevent_default()
        if self._reconnect_on_enter:
            if event.key in {'enter', 'return'}:
                self._reconnect_on_enter = False
                self._start_session()
            return
        text = encode_exec_key(event.key, event.character)
        if text:
            self._write_stdin(text)

    def on_resize(self) -> None:
        self._send_resize()

    def on_pod_exec_output(self, event: PodExecOutput) -> None:
        if event.text:
            self.query_one('#pod-exec', ExecView).write(event.text)

    def on_pod_exec_status(self, event: PodExecStatus) -> None:
        self._set_status(event.message)

    def on_pod_exec_finished(self, event: PodExecFinished) -> None:
        if event.result == 'success':
            self._stop_session()
            self.app.pop_screen()
            return
        if event.result == 'reconnect':
            self._reconnect_on_enter = True

    def _start_session(self) -> None:
        self._stop_session()
        self._reconnect_on_enter = False
        self._clear_output()
        self._set_status('')
        stop = threading.Event()
        self._watch_stop = stop
        thread = threading.Thread(target=self._run_shells, args=(stop,), daemon=True)
        self._watch_thread = thread
        thread.start()

    def _run_shells(self, stop: threading.Event) -> None:
        last = len(self.shells) - 1
        for index, command in enumerate(self.shells):
            if stop.is_set():
                return
            self._emit_output(f'Trying to run "{command}"…\n')
            try:
                session = self.cluster.open_pod_exec(
                    self.namespace,
                    self.pod_name,
                    container=self.container,
                    command=command,
                )
            except Exception as exc:
                self._emit_status(api_error_message(exc))
                if index >= last:
                    self._emit_connect_failed()
                    return
                continue
            if stop.is_set():
                _close_session(session)
                return
            self._session = session
            self._send_resize()
            result = follow_pod_exec(
                session,
                stop,
                self._emit_output,
                self._emit_status,
            )
            self._session = None
            if result == 'success':
                self._emit_finished('success')
                return
            if result == 'not_found' and index < last:
                self._emit_output(f'Failed to run "{command}"\n')
                continue
            if result == 'not_found':
                self._emit_connect_failed()
                return
            return

    def _emit_connect_failed(self) -> None:
        self._emit_output('Failed to connect…\n\nPress the enter key to reconnect.\n')
        self._emit_finished('reconnect')

    def _emit_output(self, text: str) -> None:
        try:
            self.post_message(PodExecOutput(text))
        except Exception:
            pass

    def _emit_status(self, message: str) -> None:
        try:
            self.post_message(PodExecStatus(message))
        except Exception:
            pass

    def _emit_finished(self, result: str) -> None:
        try:
            self.post_message(PodExecFinished(result))
        except Exception:
            pass

    def _write_stdin(self, data: str) -> None:
        session = self._session
        if session is None:
            return
        writer = getattr(session, 'write_stdin', None)
        if writer is None:
            return
        try:
            writer(data)
        except Exception:
            pass

    def _send_resize(self) -> None:
        session = self._session
        if session is None:
            return
        writer = getattr(session, 'write_resize', None)
        if writer is None:
            return
        try:
            log = self.query_one('#pod-exec', ExecView)
        except Exception:
            return
        cols = max(20, log.size.width)
        rows = max(5, log.size.height)
        try:
            writer(cols, rows)
        except Exception:
            pass

    def _stop_session(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
        session = self._session
        self._session = None
        if session is not None:
            threading.Thread(target=_close_session, args=(session,), daemon=True).start()
        self._watch_stop = None
        self._watch_thread = None

    def _clear_output(self) -> None:
        self.query_one('#pod-exec', ExecView).clear()

    def _set_status(self, message: str) -> None:
        set_status(self.query_one('#exec-status', Static), message)

    def _set_subtitle(self) -> None:
        container = self.container or '(default)'
        self.sub_title = f'{self.namespace}/{self.pod_name} / {container}'

    def _focus_exec(self) -> None:
        try:
            self.query_one('#pod-exec', ExecView).focus()
        except Exception:
            pass


def _close_session(session: object) -> None:
    closer = getattr(session, 'close', None)
    if closer is None:
        return
    try:
        closer()
    except Exception:
        pass
