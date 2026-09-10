"""Textual application entry."""

from __future__ import annotations

from textual.app import App

from roomlamp.k8s.context import ClusterInfo
from roomlamp.ui.screens.home import HomeScreen


class RoomlampApp(App[None]):
    """Standalone Kubernetes TUI."""

    TITLE = 'Roomlamp'
    CSS = """
    #home {
        padding: 1 2;
    }
    """
    BINDINGS = [('q', 'quit', 'Quit')]

    def __init__(self, cluster_info: ClusterInfo) -> None:
        super().__init__()
        self.cluster_info = cluster_info

    def get_default_screen(self) -> HomeScreen:
        return HomeScreen(self.cluster_info)
