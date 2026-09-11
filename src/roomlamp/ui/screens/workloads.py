"""Workload list and read-only detail views."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.k8s.watch import apply_watch_event
from roomlamp.k8s.workloads import KIND_LABELS, KIND_SPECS, POD_KIND, WorkloadDetail, WorkloadSummary
from roomlamp.ui.screens.kinds import WorkloadKindScreen
from roomlamp.ui.screens.namespaces import ALL_LABEL, NamespaceScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen


def sort_workloads(items: list[WorkloadSummary], column: int, ascending: bool) -> list[WorkloadSummary]:
    """Sort workload rows. ``column`` is an index into the kind's columns."""

    def key(item: WorkloadSummary) -> tuple[object, ...]:
        keys = item.sort_keys
        if not keys:
            return (item.namespace, item.name)
        column_index = max(0, min(column, len(keys) - 1))
        return (keys[column_index], item.namespace, item.name)

    return sorted(items, key=key, reverse=not ascending)


def show_kind_list(
    app: Any,
    info: ClusterInfo,
    cluster: Any,
    kind: str,
    namespace: str,
    enable_watch: bool,
    *,
    replace: bool,
) -> None:
    """Open Pods or another workload list, replacing the current screen when asked."""
    if kind == POD_KIND:
        from roomlamp.ui.screens.pods import PodListScreen

        screen: Screen[None] = PodListScreen(info, cluster, namespace, enable_watch)
    else:
        screen = WorkloadListScreen(info, cluster, kind, namespace, enable_watch)
    if replace:
        app.switch_screen(screen)
    else:
        app.push_screen(screen)


class WorkloadListScreen(Screen[None]):
    BINDINGS = [
        ('n', 'pick_namespace', 'Namespace'),
        ('w', 'pick_kind', 'Workloads'),
        ('p', 'show_pods', 'Pods'),
        ('c', 'show_cluster', 'Cluster'),
        ('r', 'refresh', 'Refresh'),
    ]

    def __init__(
        self,
        info: ClusterInfo,
        cluster: Any,
        kind: str,
        namespace: str,
        enable_watch: bool = True,
    ) -> None:
        super().__init__()
        self.info = info
        self.cluster = cluster
        self.kind = kind
        self.namespace = namespace
        self.enable_watch = enable_watch
        self._namespaces: list[str] = []
        self._items: dict[str, WorkloadSummary] = {}
        self.sort_column = 0
        self.sort_ascending = True
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None

    def on_mount(self) -> None:
        self._set_subtitle()
        if self.enable_watch:
            self.run_worker(self._load_initial, exclusive=True, group='workloads-load')
        else:
            self._load_sync()

    def on_unmount(self) -> None:
        self._stop_watch()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static('', id='workloads-status'),
            DataTable(id='workloads', cursor_type='row'),
            id='workloads-wrap',
        )
        yield Footer()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column = event.column_index
        if column == self.sort_column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = True
        self._render_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value) if event.row_key is not None else ''
        if key:
            self.run_worker(self._open_detail(key), exclusive=True, group='workload-detail')

    def action_pick_namespace(self) -> None:
        self.app.push_screen(
            NamespaceScreen(self._namespaces, self.namespace),
            callback=self._on_namespace_chosen,
        )

    def _on_namespace_chosen(self, chosen: str | None) -> None:
        if chosen is None or chosen == self.namespace:
            return
        self.namespace = chosen
        self._stop_watch()
        if self.enable_watch:
            self.run_worker(self._load_initial, exclusive=True, group='workloads-load')
        else:
            self._load_sync()

    def action_pick_kind(self) -> None:
        self.app.push_screen(WorkloadKindScreen(self.kind), callback=self._on_kind_chosen)

    def _on_kind_chosen(self, chosen: str | None) -> None:
        if chosen is None or chosen == self.kind:
            return
        show_kind_list(
            self.app,
            self.info,
            self.cluster,
            chosen,
            self.namespace,
            self.enable_watch,
            replace=chosen != POD_KIND,
        )

    def action_show_pods(self) -> None:
        show_kind_list(
            self.app,
            self.info,
            self.cluster,
            POD_KIND,
            self.namespace,
            self.enable_watch,
            replace=False,
        )

    def action_show_cluster(self) -> None:
        from roomlamp.ui.screens.home import HomeScreen

        self.app.push_screen(HomeScreen(self.info))

    async def action_refresh(self) -> None:
        self._stop_watch()
        if self.enable_watch:
            await self._load_initial()
        else:
            self._load_sync()

    def _load_sync(self) -> None:
        try:
            namespaces, items = self._fetch()
            self._apply_list(namespaces, items)
            self._set_status('')
        except Exception as exc:
            self._set_status(str(exc))

    async def _load_initial(self) -> None:
        try:
            namespaces, items = await asyncio.to_thread(self._fetch)
            self._apply_list(namespaces, items)
            self._set_status('')
        except Exception as exc:
            self._set_status(str(exc))
        if self.enable_watch:
            self._start_watch()

    def _fetch(self) -> tuple[list[str], list[WorkloadSummary]]:
        try:
            namespaces = self.cluster.list_namespaces()
        except Exception:
            namespaces = [self.namespace] if self.namespace != ALL_NAMESPACES else []
        items = self.cluster.list_workloads(self.kind, self.namespace)
        return namespaces, items

    def _apply_list(self, namespaces: list[str], items: list[WorkloadSummary]) -> None:
        self._namespaces = namespaces
        self._items = {item.key: item for item in items}
        self._render_table()
        self._set_subtitle()

    def _apply_event(self, event_type: str, item: WorkloadSummary) -> None:
        self._items = apply_watch_event(self._items, event_type, item)
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one('#workloads', DataTable)
        columns = KIND_SPECS[self.kind].columns
        if not table.columns:
            table.add_columns(*columns)
        table.clear()
        for item in sort_workloads(list(self._items.values()), self.sort_column, self.sort_ascending):
            table.add_row(*item.cells, key=item.key)

    async def _open_detail(self, key: str) -> None:
        namespace, name = key.split('/', 1)
        try:
            detail = await asyncio.to_thread(self.cluster.get_workload, self.kind, namespace, name)
        except Exception as exc:
            self._set_status(str(exc))
            return
        await self.app.push_screen(WorkloadDetailScreen(detail, self.cluster))

    def _start_watch(self) -> None:
        if not hasattr(self.cluster, 'watch_workloads'):
            return
        self._stop_watch()
        stop = threading.Event()
        self._watch_stop = stop

        def _run() -> None:
            self.cluster.watch_workloads(
                self.kind,
                self.namespace,
                stop,
                lambda event_type, item: self.app.call_from_thread(self._apply_event, event_type, item),
                lambda message: self.app.call_from_thread(self._set_status, message),
            )

        thread = threading.Thread(target=_run, daemon=True)
        self._watch_thread = thread
        thread.start()

    def _stop_watch(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
        self._watch_stop = None
        self._watch_thread = None

    def _set_status(self, message: str) -> None:
        self.query_one('#workloads-status', Static).update(message)

    def _set_subtitle(self) -> None:
        context = self.info.context_name or 'no context'
        namespace = ALL_LABEL if self.namespace == ALL_NAMESPACES else self.namespace
        self.sub_title = f'{context} / {namespace} / {KIND_LABELS[self.kind]}'


class WorkloadDetailScreen(Screen[None]):
    BINDINGS = [
        ('y', 'show_yaml', 'YAML'),
        ('escape', 'app.pop_screen', 'Back'),
        ('backspace', 'app.pop_screen', 'Back'),
    ]

    def __init__(self, detail: WorkloadDetail, cluster: Any) -> None:
        super().__init__()
        self.detail = detail
        self.cluster = cluster

    def on_mount(self) -> None:
        self.sub_title = f'{self.detail.kind} {self.detail.namespace}/{self.detail.name}'

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(_detail_text(self.detail), id='workload-detail'),
            id='workload-detail-wrap',
        )
        yield Footer()

    async def action_show_yaml(self) -> None:
        try:
            text = await asyncio.to_thread(
                self.cluster.get_workload_yaml,
                self.detail.kind,
                self.detail.namespace,
                self.detail.name,
            )
        except Exception as exc:
            self.notify(str(exc), severity='error')
            return
        title = f'{self.detail.kind} {self.detail.namespace}/{self.detail.name}'
        kind = self.detail.kind
        namespace = self.detail.namespace
        name = self.detail.name
        await self.app.push_screen(
            YamlViewScreen(
                title,
                text,
                reload=lambda: self.cluster.get_workload_yaml(kind, namespace, name),
                apply=lambda body, dry_run=False: self.cluster.apply_yaml(
                    body, dry_run=dry_run, default_namespace=namespace
                ),
            )
        )


def _detail_text(detail: WorkloadDetail) -> str:
    labels = ', '.join(f'{key}={value}' for key, value in detail.labels) or '(none)'
    containers = '\n'.join(f'  - {line}' for line in detail.containers) or '  (none)'
    rows = [
        ('Kind', detail.kind),
        ('Name', detail.name),
        ('Namespace', detail.namespace),
        ('UID', detail.uid or '(none)'),
        ('Created', detail.created or '(none)'),
        *detail.fields,
        ('Labels', labels),
    ]
    width = max(len(name) for name, _ in rows)
    body = '\n'.join(f'{name + ":":<{width + 1}} {value}' for name, value in rows)
    return f'{body}\n\nContainers:\n{containers}'
