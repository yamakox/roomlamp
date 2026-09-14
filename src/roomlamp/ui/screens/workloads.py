"""Workload list and read-only detail views."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from roomlamp.k8s.auth import ResourceActions, actions_for, has_access_checker, initial_actions
from roomlamp.k8s.catalog import is_catalog_kind
from roomlamp.k8s.configuration import is_configuration_kind
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.delete import DeletedObject
from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.gateway import is_gateway_kind
from roomlamp.k8s.network import is_network_kind
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.k8s.security import is_security_kind
from roomlamp.k8s.storage import is_storage_kind
from roomlamp.k8s.watch import apply_watch_event
from roomlamp.k8s.workloads import KIND_LABELS, KIND_SPECS, POD_KIND, WorkloadDetail, WorkloadSummary
from roomlamp.ui.bindings import CONTEXT_BINDING, HOME_BINDING, MENU_BINDING, NavigationMixin
from roomlamp.ui.screens.delete import request_delete, selected_row_key
from roomlamp.ui.screens.namespaces import ALL_LABEL, NamespaceScreen
from roomlamp.ui.screens.yaml_view import YamlViewScreen
from roomlamp.ui.status import set_status, status_widget
from roomlamp.ui.widgets.data_table import ResourceTable


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
    """Open Pods, a workload, Storage, Network, Gateway, Security, Configuration, or Cluster catalog kind list, replacing the current screen when asked."""
    if kind == POD_KIND:
        from roomlamp.ui.screens.pods import PodListScreen

        screen: Screen[None] = PodListScreen(info, cluster, namespace, enable_watch)
    elif is_catalog_kind(kind):
        from roomlamp.ui.screens.catalog import CatalogListScreen

        screen = CatalogListScreen(info, cluster, kind, namespace, enable_watch)
    elif is_storage_kind(kind):
        from roomlamp.ui.screens.storage import StorageListScreen

        screen = StorageListScreen(info, cluster, kind, namespace, enable_watch)
    elif is_network_kind(kind):
        from roomlamp.ui.screens.network import NetworkListScreen

        screen = NetworkListScreen(info, cluster, kind, namespace, enable_watch)
    elif is_gateway_kind(kind):
        from roomlamp.ui.screens.gateway import GatewayListScreen

        screen = GatewayListScreen(info, cluster, kind, namespace, enable_watch)
    elif is_security_kind(kind):
        from roomlamp.ui.screens.security import SecurityListScreen

        screen = SecurityListScreen(info, cluster, kind, namespace, enable_watch)
    elif is_configuration_kind(kind):
        from roomlamp.ui.screens.configuration import ConfigurationListScreen

        screen = ConfigurationListScreen(info, cluster, kind, namespace, enable_watch)
    else:
        screen = WorkloadListScreen(info, cluster, kind, namespace, enable_watch)
    if replace:
        app.switch_screen(screen)
    else:
        app.push_screen(screen)


class WorkloadListScreen(NavigationMixin, Screen[None]):
    BINDINGS = [
        MENU_BINDING,
        CONTEXT_BINDING,
        HOME_BINDING,
        ('n', 'pick_namespace', 'Namespace'),
        ('d', 'delete', 'Delete'),
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
        self._auth = initial_actions(cluster, kind)
        self._auth_key: str | None = None

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
            status_widget('workloads-status'),
            ResourceTable(id='workloads', cursor_type='row'),
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

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = str(event.row_key.value) if event.row_key is not None else None
        self._queue_auth(key)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'delete' and not self._auth.can_remove:
            return False
        return True

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

    def _on_kind_chosen(self, chosen: str | None) -> None:
        if chosen is None or chosen == self.kind:
            return
        self._on_nav_kind(chosen)

    async def action_refresh(self) -> None:
        self._stop_watch()
        if self.enable_watch:
            await self._load_initial()
        else:
            self._load_sync()

    def action_delete(self) -> None:
        key = selected_row_key(self.query_one('#workloads', DataTable))
        if not key:
            return
        namespace, name = key.split('/', 1)
        request_delete(
            self,
            self.cluster,
            self.kind,
            name,
            namespace,
            allow_delete=self._auth.delete,
            on_success=self._on_deleted,
        )

    def _on_deleted(self, deleted: DeletedObject) -> None:
        if deleted.namespace:
            self._items.pop(f'{deleted.namespace}/{deleted.name}', None)
            self._render_table()

    def _load_sync(self) -> None:
        try:
            namespaces, items = self._fetch()
            self._apply_list(namespaces, items)
            self._set_status('')
        except Exception as exc:
            self._set_status(api_error_message(exc))

    async def _load_initial(self) -> None:
        try:
            namespaces, items = await asyncio.to_thread(self._fetch)
            self._apply_list(namespaces, items)
            self._set_status('')
        except Exception as exc:
            self._set_status(api_error_message(exc))
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
        key = selected_row_key(self.query_one('#workloads', DataTable))
        self._queue_auth(key)

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
            self._set_status(api_error_message(exc))
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

    def _queue_auth(self, key: str | None) -> None:
        if key == self._auth_key:
            return
        self._auth_key = key
        if not key:
            self._auth = ResourceActions.none()
            self.refresh_bindings()
            return
        if not has_access_checker(self.cluster):
            self._auth = initial_actions(self.cluster, self.kind)
            self.refresh_bindings()
            return
        self.run_worker(self._load_row_auth(key), exclusive=True, group='auth')

    async def _load_row_auth(self, key: str) -> None:
        namespace, name = key.split('/', 1)
        auth = await asyncio.to_thread(actions_for, self.cluster, self.kind, namespace, name)
        if self._auth_key != key:
            return
        self._auth = auth
        self.refresh_bindings()

    def _set_status(self, message: str) -> None:
        set_status(self.query_one('#workloads-status', Static), message)

    def _set_subtitle(self) -> None:
        context = self.info.context_name or 'no context'
        namespace = ALL_LABEL if self.namespace == ALL_NAMESPACES else self.namespace
        self.sub_title = f'{context} / {namespace} / {KIND_LABELS[self.kind]}'


class WorkloadDetailScreen(NavigationMixin, Screen[None]):
    BINDINGS = [
        MENU_BINDING,
        CONTEXT_BINDING,
        HOME_BINDING,
        ('y', 'show_yaml', 'YAML'),
        ('d', 'delete', 'Delete'),
        ('r', 'refresh', 'Refresh'),
        ('escape', 'app.pop_screen', 'Back'),
        ('backspace', 'app.pop_screen', 'Back'),
    ]

    def __init__(self, detail: WorkloadDetail, cluster: Any) -> None:
        super().__init__()
        self.detail = detail
        self.cluster = cluster
        self.kind = detail.kind
        self._auth = initial_actions(cluster, detail.kind)

    def on_mount(self) -> None:
        self._set_subtitle()
        if has_access_checker(self.cluster):
            self.run_worker(self._load_auth, exclusive=True, group='auth')

    def _set_subtitle(self) -> None:
        self.sub_title = f'{self.detail.kind} {self.detail.namespace}/{self.detail.name}'

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'delete' and not self._auth.can_remove:
            return False
        return True

    async def _load_auth(self) -> None:
        self._auth = await asyncio.to_thread(
            actions_for,
            self.cluster,
            self.detail.kind,
            self.detail.namespace,
            self.detail.name,
        )
        self.refresh_bindings()

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(_detail_text(self.detail), id='workload-detail'),
            id='workload-detail-wrap',
        )
        yield Footer()

    async def action_refresh(self) -> None:
        await self._reload_detail()

    async def _reload_detail(self) -> None:
        try:
            self.detail = await asyncio.to_thread(
                self.cluster.get_workload,
                self.detail.kind,
                self.detail.namespace,
                self.detail.name,
            )
        except Exception as exc:
            self.notify(api_error_message(exc), severity='error')
            return
        self.kind = self.detail.kind
        self._set_subtitle()
        self.query_one('#workload-detail', Static).update(_detail_text(self.detail))

    async def action_show_yaml(self) -> None:
        try:
            text = await asyncio.to_thread(
                self.cluster.get_workload_yaml,
                self.detail.kind,
                self.detail.namespace,
                self.detail.name,
            )
        except Exception as exc:
            self.notify(api_error_message(exc), severity='error')
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
                can_apply=self._auth.update,
                on_applied=lambda: self.run_worker(self._reload_detail, exclusive=True, group='detail-load'),
            )
        )

    def action_delete(self) -> None:
        request_delete(
            self,
            self.cluster,
            self.detail.kind,
            self.detail.name,
            self.detail.namespace,
            allow_delete=self._auth.delete,
            on_success=lambda _deleted: self.app.pop_screen(),
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
