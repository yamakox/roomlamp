"""YAML editor with apply. Headlamp EditorDialog equivalent for the TUI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, TextArea

from roomlamp.k8s.apply import AppliedObject
from roomlamp.k8s.errors import api_error_message

ApplyFn = Callable[..., Sequence[AppliedObject]]


class YamlViewScreen(Screen[None]):
    BINDINGS = [
        Binding('ctrl+s', 'apply', 'Apply', priority=True),
        Binding('f8', 'dry_run', 'Dry Run', priority=True),
        Binding('ctrl+r', 'refresh', 'Refresh', priority=True),
        Binding('escape', 'app.pop_screen', 'Back', priority=True),
    ]

    def __init__(
        self,
        title: str,
        text: str,
        reload: Callable[[], str] | None = None,
        apply: ApplyFn | None = None,
        *,
        can_apply: bool = True,
        on_applied: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._original = text
        self._reload = reload
        self._apply = apply
        self._can_apply = can_apply and apply is not None
        self._on_applied = on_applied

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {'apply', 'dry_run'} and not self._can_apply:
            return False
        return True

    def on_mount(self) -> None:
        self.sub_title = self._title

    def compose(self) -> ComposeResult:
        yield Header()
        yield TextArea.code_editor(
            self._original,
            language='yaml',
            read_only=not self._can_apply,
            id='yaml-view',
        )
        yield Footer()

    async def action_apply(self) -> None:
        await self._run_apply(dry_run=False)

    async def action_dry_run(self) -> None:
        await self._run_apply(dry_run=True)

    async def action_refresh(self) -> None:
        if self._reload is None:
            return
        try:
            text = await asyncio.to_thread(self._reload)
        except Exception as exc:
            self.notify(api_error_message(exc), severity='error')
            return
        self._original = text
        self.query_one('#yaml-view', TextArea).load_text(text)

    async def _run_apply(self, *, dry_run: bool) -> None:
        if not self._can_apply or self._apply is None:
            return
        text = self.query_one('#yaml-view', TextArea).text
        if text == self._original:
            self.notify('No changes to apply')
            return
        try:
            applied = await asyncio.to_thread(self._apply, text, dry_run)
        except Exception as exc:
            self.notify(api_error_message(exc), severity='error')
            return
        names = ', '.join(item.label for item in applied) or 'resource'
        if dry_run:
            self.notify(f'Dry run passed for {names}')
            return
        self._original = text
        self.notify(f'Applied {names}')
        if self._on_applied is not None:
            self._on_applied()
        self.app.pop_screen()
