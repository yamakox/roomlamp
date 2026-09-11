"""Read-only YAML view for a Kubernetes object."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class YamlViewScreen(Screen[None]):
    BINDINGS = [
        ('r', 'refresh', 'Refresh'),
        ('escape', 'app.pop_screen', 'Back'),
        ('backspace', 'app.pop_screen', 'Back'),
    ]

    def __init__(self, title: str, text: str, reload: Callable[[], str] | None = None) -> None:
        super().__init__()
        self._title = title
        self._text = text
        self._reload = reload

    def on_mount(self) -> None:
        self.sub_title = self._title

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(self._text, id='yaml-view'), id='yaml-wrap')
        yield Footer()

    async def action_refresh(self) -> None:
        if self._reload is None:
            return
        try:
            self._text = await asyncio.to_thread(self._reload)
        except Exception as exc:
            self.notify(str(exc), severity='error')
            return
        self.query_one('#yaml-view', Static).update(self._text)
