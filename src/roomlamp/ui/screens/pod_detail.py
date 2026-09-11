"""Read-only Pod detail view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from roomlamp.k8s.resources import PodDetail


class PodDetailScreen(Screen[None]):
    BINDINGS = [('escape', 'app.pop_screen', 'Back'), ('backspace', 'app.pop_screen', 'Back')]

    def __init__(self, detail: PodDetail) -> None:
        super().__init__()
        self.detail = detail

    def on_mount(self) -> None:
        self.sub_title = f'{self.detail.namespace}/{self.detail.name}'

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static(_detail_text(self.detail), id='pod-detail'), id='pod-detail-wrap')
        yield Footer()


def _detail_text(detail: PodDetail) -> str:
    labels = ', '.join(f'{key}={value}' for key, value in detail.labels) or '(none)'
    containers = '\n'.join(f'  - {line}' for line in detail.containers) or '  (none)'
    return (
        f'Name:      {detail.name}\n'
        f'Namespace: {detail.namespace}\n'
        f'UID:       {detail.uid or "(none)"}\n'
        f'Created:   {detail.created or "(none)"}\n'
        f'Status:    {detail.phase}\n'
        f'Ready:     {detail.ready}\n'
        f'Restarts:  {detail.restarts}\n'
        f'Node:      {detail.node or "(none)"}\n'
        f'Pod IP:    {detail.pod_ip or "(none)"}\n'
        f'Labels:    {labels}\n'
        f'\nContainers:\n{containers}'
    )
