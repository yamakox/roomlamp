"""Cluster home: identity, metrics overview, and a Node list (no detail)."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.metrics import METRICS_FORBIDDEN, METRICS_NOT_FOUND, METRICS_OK
from roomlamp.k8s.nodes import HomeSnapshot, NodeSummary
from roomlamp.ui.bindings import MENU_BINDING, NavigationMixin
from roomlamp.ui.usage import format_bar, format_cpu, format_memory

OVERVIEW_INTERVAL_SECONDS = 60.0
NODE_COLUMNS = ('Name', 'CPU', 'Memory', 'Ready', 'Roles', 'Internal IP', 'Version', 'Age')


def sort_nodes(nodes: list[NodeSummary], snapshot: HomeSnapshot, column: int, ascending: bool) -> list[NodeSummary]:
    column = max(0, min(column, len(NODE_COLUMNS) - 1))

    def key(node: NodeSummary) -> tuple[object, ...]:
        usage = snapshot.usages.get(node.name)
        cpu_used = usage.cpu_used if usage is not None else 0.0
        memory_used = usage.memory_used if usage is not None else 0.0
        age_key = node.created.timestamp() if node.created is not None else 0.0
        values: tuple[object, ...] = (
            node.name,
            cpu_used,
            memory_used,
            node.ready,
            node.roles,
            node.internal_ip,
            node.version,
            age_key,
        )
        return (values[column], node.name)

    return sorted(nodes, key=key, reverse=not ascending)


class HomeScreen(NavigationMixin, Screen[None]):
    """Headlamp Clusters / main: identity, overview bars, Node table."""

    BINDINGS = [
        MENU_BINDING,
        ('r', 'refresh', 'Refresh'),
    ]

    def __init__(
        self,
        info: ClusterInfo,
        cluster: Any = None,
        enable_watch: bool = True,
    ) -> None:
        super().__init__()
        self.info = info
        self.cluster = cluster
        self.enable_watch = enable_watch
        self._snapshot: HomeSnapshot | None = None
        self.sort_column = 0
        self.sort_ascending = True

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {'show_menu', 'refresh'} and (self.cluster is None or not self.info.ok):
            return False
        return True

    def on_mount(self) -> None:
        self.sub_title = self.info.context_name or 'no context'
        if self.cluster is not None and self.info.ok:
            self.action_refresh()
            if self.enable_watch:
                self.set_interval(OVERVIEW_INTERVAL_SECONDS, self.action_refresh)

    def compose(self) -> ComposeResult:
        table = DataTable(id='nodes', cursor_type='none', show_cursor=False)
        table.can_focus = False
        yield Header()
        yield VerticalScroll(
            Static(_identity(self.info), id='home-identity'),
            Static('', id='home-status'),
            Static('', id='home-overview'),
            table,
            id='home',
        )
        yield Footer()

    def action_refresh(self) -> None:
        if self.cluster is None or not self.info.ok:
            return
        self.run_worker(self._load, exclusive=True, group='home-load')

    async def _load(self) -> None:
        try:
            loader = getattr(self.cluster, 'load_home', None)
            if loader is not None:
                snapshot = await asyncio.to_thread(loader)
            else:
                snapshot = await asyncio.to_thread(self._load_from_parts)
        except Exception as exc:
            self.query_one('#home-status', Static).update(api_error_message(exc))
            return
        self._snapshot = snapshot
        self._apply_snapshot()

    def _load_from_parts(self) -> HomeSnapshot:
        from roomlamp.k8s.metrics import NodeMetricsResult
        from roomlamp.k8s.nodes import build_home_snapshot
        from roomlamp.k8s.resources import ALL_NAMESPACES

        nodes = self.cluster.list_nodes()
        try:
            pods = self.cluster.list_pods(ALL_NAMESPACES)
        except Exception:
            pods = []
        try:
            metrics = self.cluster.list_node_metrics()
        except Exception:
            metrics = NodeMetricsResult({}, METRICS_NOT_FOUND)
        return build_home_snapshot(nodes, pods, metrics)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column = event.column_index
        if column == self.sort_column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = True
        self._apply_table()

    def _apply_snapshot(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        status = ''
        if snapshot.metrics_status == METRICS_FORBIDDEN:
            status = snapshot.metrics_message or 'Metrics forbidden'
        elif snapshot.metrics_status not in {METRICS_OK, METRICS_NOT_FOUND} and snapshot.metrics_message:
            status = snapshot.metrics_message
        self.query_one('#home-status', Static).update(status)
        self.query_one('#home-overview', Static).update(_overview_text(snapshot))
        self._apply_table()

    def _apply_table(self) -> None:
        snapshot = self._snapshot
        table = self.query_one('#nodes', DataTable)
        if not table.columns:
            table.add_columns(*NODE_COLUMNS)
        table.clear()
        if snapshot is None:
            return
        hide_metrics = snapshot.metrics_status == METRICS_FORBIDDEN
        unavailable = snapshot.metrics_status == METRICS_NOT_FOUND
        for node in sort_nodes(list(snapshot.nodes), snapshot, self.sort_column, self.sort_ascending):
            usage = snapshot.usages.get(node.name)
            cpu_used = usage.cpu_used if usage is not None else None
            memory_used = usage.memory_used if usage is not None else None
            cpu_cell = (
                '—'
                if hide_metrics
                else format_bar(
                    cpu_used,
                    node.cpu_capacity,
                    used_label=format_cpu(cpu_used or 0.0),
                    capacity_label=format_cpu(node.cpu_capacity),
                    unavailable=unavailable,
                )
            )
            memory_cell = (
                '—'
                if hide_metrics
                else format_bar(
                    memory_used,
                    node.memory_capacity,
                    used_label=format_memory(memory_used or 0.0),
                    capacity_label=format_memory(node.memory_capacity),
                    unavailable=unavailable,
                )
            )
            table.add_row(
                node.name,
                cpu_cell,
                memory_cell,
                'Yes' if node.ready else 'No',
                node.roles,
                node.internal_ip,
                node.version,
                node.age,
                key=node.key,
            )

    # Home is already current; keep the mixin method from popping.
    def action_show_home(self) -> None:
        return


def _identity(info: ClusterInfo) -> str:
    if info.error:
        return f'Could not load kubeconfig.\n\nKubeconfig: {info.kubeconfig}\nError: {info.error}'
    return '\n'.join(
        [
            f'Context:    {info.context_name or "(none)"}',
            f'Cluster:    {info.cluster_name or "(none)"}',
            f'User:       {info.user_name or "(none)"}',
            f'Kubeconfig: {info.kubeconfig}',
        ]
    )


def _overview_text(snapshot: HomeSnapshot) -> str:
    hide_metrics = snapshot.metrics_status == METRICS_FORBIDDEN
    unavailable = snapshot.metrics_status == METRICS_NOT_FOUND
    lines = ['Overview']
    if not hide_metrics:
        lines.append(
            'CPU     '
            + format_bar(
                snapshot.cpu_used,
                snapshot.cpu_capacity,
                used_label=format_cpu(snapshot.cpu_used or 0.0),
                capacity_label=f'{format_cpu(snapshot.cpu_capacity)} cores',
                unavailable=unavailable,
            )
        )
        lines.append(
            'Memory  '
            + format_bar(
                snapshot.memory_used,
                snapshot.memory_capacity,
                used_label=format_memory(snapshot.memory_used or 0.0),
                capacity_label=format_memory(snapshot.memory_capacity),
                unavailable=unavailable,
            )
        )
    lines.append(
        'Pods    '
        + format_bar(
            float(snapshot.pods_ready),
            float(snapshot.pods_total) if snapshot.pods_total else 0.0,
            used_label=str(snapshot.pods_ready),
            capacity_label=str(snapshot.pods_total),
        )
    )
    lines.append(
        'Nodes   '
        + format_bar(
            float(snapshot.nodes_ready),
            float(snapshot.nodes_total) if snapshot.nodes_total else 0.0,
            used_label=str(snapshot.nodes_ready),
            capacity_label=str(snapshot.nodes_total),
        )
    )
    return '\n'.join(lines)


__all__ = ['HomeScreen', 'NODE_COLUMNS', 'OVERVIEW_INTERVAL_SECONDS', 'sort_nodes']
