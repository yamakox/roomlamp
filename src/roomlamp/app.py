"""Textual application entry."""

from __future__ import annotations

from typing import Any

from textual.app import App

from roomlamp.k8s.context import ClusterInfo
from roomlamp.ui.screens.home import HomeScreen


class RoomlampApp(App[None]):
    """Standalone Kubernetes TUI."""

    TITLE = 'Roomlamp'
    CSS = """
    #home, #pods-wrap, #pod-detail-wrap, #workloads-wrap, #workload-detail-wrap, #storage-wrap, #storage-detail-wrap, #network-wrap, #network-detail-wrap, #gateway-wrap, #gateway-detail-wrap, #security-wrap, #security-detail-wrap, #logs-wrap, #exec-wrap {
        padding: 1 2;
    }

    #yaml-view {
        padding: 1 2;
    }

    #home-status, #pods-status, #workloads-status, #storage-status, #network-status, #gateway-status, #security-status, #logs-status, #exec-status {
        margin-bottom: 1;
    }

    #home-identity, #home-overview {
        margin-bottom: 1;
    }

    #namespace-dialog, #kind-dialog, #menu-dialog, #container-dialog, #delete-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $accent;
        background: $surface;
    }

    #delete-prompt {
        width: 100%;
        height: auto;
        text-wrap: wrap;
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

    def get_default_screen(self) -> HomeScreen:
        return HomeScreen(self.cluster_info, self.cluster, self.enable_watch)
