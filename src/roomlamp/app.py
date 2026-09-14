"""Textual application entry."""

from __future__ import annotations

from typing import Any

from textual.app import App

from roomlamp.k8s.cluster import build_cluster, close_cluster
from roomlamp.k8s.context import ClusterInfo, load_cluster_info
from roomlamp.k8s.errors import api_error_message
from roomlamp.ui.bindings import pop_to_home
from roomlamp.ui.screens.home import HomeScreen


class RoomlampApp(App[None]):
    """Standalone Kubernetes TUI."""

    TITLE = 'Roomlamp'
    CSS = """
    #home, #pods-wrap, #pod-detail-wrap, #workloads-wrap, #workload-detail-wrap, #storage-wrap, #storage-detail-wrap, #network-wrap, #network-detail-wrap, #gateway-wrap, #gateway-detail-wrap, #security-wrap, #security-detail-wrap, #configuration-wrap, #configuration-detail-wrap, #catalog-wrap, #catalog-detail-wrap, #logs-wrap, #exec-wrap {
        padding: 1 2;
    }

    #yaml-view {
        padding: 1 2;
    }

    #home {
        height: 1fr;
    }

    #pods-wrap, #workloads-wrap, #storage-wrap, #network-wrap, #gateway-wrap, #security-wrap, #configuration-wrap, #catalog-wrap {
        height: 1fr;
    }

    #pods, #workloads, #storage, #network, #gateway, #security, #configuration, #catalog {
        height: 1fr;
    }

    #nodes {
        height: auto;
        overflow-y: hidden;
    }

    #pod-detail-wrap, #workload-detail-wrap, #storage-detail-wrap, #network-detail-wrap, #gateway-detail-wrap, #security-detail-wrap, #configuration-detail-wrap, #catalog-detail-wrap {
        height: 1fr;
    }

    #home-status, #pods-status, #workloads-status, #storage-status, #network-status, #gateway-status, #security-status, #configuration-status, #catalog-status, #logs-status, #exec-status {
        margin-bottom: 1;
    }

    #home-identity, #home-overview {
        margin-bottom: 1;
    }

        #namespace-dialog, #kind-dialog, #menu-dialog, #container-dialog, #delete-dialog, #context-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $accent;
        background: $surface;
    }

    #delete-prompt, #delete-warning, #delete-confirm-hint {
        width: 100%;
        height: auto;
        text-wrap: wrap;
    }

    #delete-warning {
        color: $warning;
        margin-top: 1;
    }

    #delete-confirm-hint {
        margin-top: 1;
    }

    #delete-confirm-input {
        width: 100%;
        margin: 1 0;
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

    def switch_context(self, name: str) -> None:
        """Switch kubeconfig context in this process. Does not rewrite the file."""
        current = self.cluster_info
        if name == current.context_name:
            self.notify('No changes to apply')
            return
        info = load_cluster_info(config_file=current.kubeconfig, context=name)
        try:
            cluster = build_cluster(info)
        except Exception as exc:
            self.notify(api_error_message(exc), severity='error')
            return
        pop_to_home(self)
        old = self.cluster
        self.cluster_info = info
        self.cluster = cluster
        if isinstance(self.screen, HomeScreen):
            self.screen.apply_cluster(info, cluster)
        close_cluster(old)
