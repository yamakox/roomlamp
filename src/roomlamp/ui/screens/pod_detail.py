"""Read-only Pod detail view."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from roomlamp.k8s.resources import PodDetail
from roomlamp.ui.screens.exec import PodExecScreen
from roomlamp.ui.screens.logs import PodLogsScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen


class PodDetailScreen(Screen[None]):
    BINDINGS = [
        ('y', 'show_yaml', 'YAML'),
        ('l', 'show_logs', 'Logs'),
        ('e', 'show_exec', 'Exec'),
        ('escape', 'app.pop_screen', 'Back'),
        ('backspace', 'app.pop_screen', 'Back'),
    ]

    def __init__(self, detail: PodDetail, cluster: Any, enable_watch: bool = True) -> None:
        super().__init__()
        self.detail = detail
        self.cluster = cluster
        self.enable_watch = enable_watch

    def on_mount(self) -> None:
        self.sub_title = f'{self.detail.namespace}/{self.detail.name}'

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static(_detail_text(self.detail), id='pod-detail'), id='pod-detail-wrap')
        yield Footer()

    async def action_show_yaml(self) -> None:
        try:
            text = await asyncio.to_thread(
                self.cluster.get_pod_yaml,
                self.detail.namespace,
                self.detail.name,
            )
        except Exception as exc:
            self.notify(str(exc), severity='error')
            return
        title = f'Pod {self.detail.namespace}/{self.detail.name}'
        namespace = self.detail.namespace
        name = self.detail.name
        await self.app.push_screen(
            YamlViewScreen(
                title,
                text,
                reload=lambda: self.cluster.get_pod_yaml(namespace, name),
                apply=lambda body, dry_run=False: self.cluster.apply_yaml(
                    body, dry_run=dry_run, default_namespace=namespace
                ),
            )
        )

    async def action_show_logs(self) -> None:
        container = self.detail.default_container
        if not container and self.detail.container_names:
            container = self.detail.container_names[0]
        await self.app.push_screen(
            PodLogsScreen(
                self.cluster,
                self.detail.namespace,
                self.detail.name,
                self.detail.container_names,
                container,
                self.enable_watch,
            )
        )

    async def action_show_exec(self) -> None:
        container = self.detail.default_container
        if not container and self.detail.container_names:
            container = self.detail.container_names[0]
        await self.app.push_screen(
            PodExecScreen(
                self.cluster,
                self.detail.namespace,
                self.detail.name,
                self.detail.container_names,
                container,
                self.detail.node_os,
            )
        )


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
