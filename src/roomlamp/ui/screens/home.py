"""Startup screen: kubeconfig path and the current context."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.workloads import POD_KIND


class HomeScreen(Screen[None]):
    """Show which kubeconfig context Roomlamp will use."""

    BINDINGS = [
        ('p', 'show_pods', 'Pods'),
        ('w', 'pick_kind', 'Workloads'),
        ('escape', 'back', 'Back'),
    ]

    def __init__(self, info: ClusterInfo) -> None:
        super().__init__()
        self.info = info

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_show_pods(self) -> None:
        self._open_kind(POD_KIND)

    def action_pick_kind(self) -> None:
        if getattr(self.app, 'cluster', None) is None or not self.info.ok:
            return
        from roomlamp.ui.screens.kinds import WorkloadKindScreen

        self.app.push_screen(WorkloadKindScreen(POD_KIND), callback=self._on_kind_chosen)

    def _on_kind_chosen(self, chosen: str | None) -> None:
        if chosen is None:
            return
        self._open_kind(chosen)

    def _open_kind(self, kind: str) -> None:
        app = self.app
        cluster = getattr(app, 'cluster', None)
        if cluster is None or not self.info.ok:
            return
        from roomlamp.ui.screens.workloads import show_kind_list

        show_kind_list(
            app,
            self.info,
            cluster,
            kind,
            self.info.namespace or 'default',
            getattr(app, 'enable_watch', True),
            replace=False,
        )

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
