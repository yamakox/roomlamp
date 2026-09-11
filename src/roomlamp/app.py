"""Textual application entry."""

from __future__ import annotations

from typing import Any

from textual.app import App

from roomlamp.k8s.context import ClusterInfo
from roomlamp.ui.screens.home import HomeScreen
from roomlamp.ui.screens.pods import PodListScreen


class RoomlampApp(App[None]):
    """Standalone Kubernetes TUI."""

    TITLE = 'Roomlamp'
    CSS = """
    #home, #pods-wrap, #pod-detail-wrap, #workloads-wrap, #workload-detail-wrap, #logs-wrap, #exec-wrap {
        padding: 1 2;
    }

    #yaml-view {
        padding: 1 2;
    }

    #pods-status, #workloads-status, #logs-status, #exec-status {
        margin-bottom: 1;
    }

    #namespace-dialog, #kind-dialog, #container-dialog, #delete-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $accent;
        background: $surface;
    }
    """
    BINDINGS = [('q', 'quit', 'Quit')]

    def __init__(
        self,
        cluster_info: ClusterInfo,
        cluster: Any = None,
        enable_watch: bool = True,
    ) -> None:
        super().__init__()
        self.cluster_info = cluster_info
        self.cluster = cluster
        self.enable_watch = enable_watch

    def get_default_screen(self) -> HomeScreen | PodListScreen:
        if self.cluster_info.ok and self.cluster is not None:
            return PodListScreen(
                self.cluster_info,
                self.cluster,
                namespace=self.cluster_info.namespace or 'default',
                enable_watch=self.enable_watch,
            )
        return HomeScreen(self.cluster_info)
