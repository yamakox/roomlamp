"""Startup screen: kubeconfig path and the current context."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from roomlamp.k8s.context import ClusterInfo


class HomeScreen(Screen[None]):
    """Show which kubeconfig context Roomlamp will use."""

    def __init__(self, info: ClusterInfo) -> None:
        super().__init__()
        self.info = info

    def on_mount(self) -> None:
        self.sub_title = self.info.context_name or 'no context'

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(_summary(self.info), id='cluster-summary'),
            id='home',
        )
        yield Footer()


def _summary(info: ClusterInfo) -> str:
    if info.error:
        return f'Could not load kubeconfig.\n\nKubeconfig: {info.kubeconfig}\nError: {info.error}'

    lines = [
        f'Kubeconfig: {info.kubeconfig}',
        f'Context:    {info.context_name or "(none)"}',
        f'Cluster:    {info.cluster_name or "(none)"}',
        f'User:       {info.user_name or "(none)"}',
        f'Namespace:  {info.namespace or "default"}',
        '',
        'Contexts:',
    ]
    for name in info.context_names:
        mark = ' (current)' if name == info.context_name else ''
        lines.append(f'  - {name}{mark}')
    if not info.context_names:
        lines.append('  (none)')
    return '\n'.join(lines)
