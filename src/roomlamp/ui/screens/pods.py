"""Pod list with namespace switching and optional Watch."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from roomlamp.k8s.auth import ResourceActions, actions_for, has_access_checker, initial_actions
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.delete import DeletedObject
from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.resources import ALL_NAMESPACES, PodSummary
from roomlamp.k8s.watch import apply_watch_event
from roomlamp.k8s.workloads import POD_KIND
from roomlamp.ui.bindings import CONTEXT_BINDING, HOME_BINDING, MENU_BINDING, NavigationMixin
from roomlamp.ui.screens.delete import request_delete, selected_row_key
from roomlamp.ui.screens.namespaces import ALL_LABEL, NamespaceScreen
from roomlamp.ui.screens.pod_detail import PodDetailScreen
from roomlamp.ui.widgets.data_table import ResourceTable

POD_COLUMNS = ('Namespace', 'Name', 'Ready', 'Status', 'Restarts', 'Node')


def _ready_sort_key(ready: str) -> tuple[int, int]:
    try:
        left, right = ready.split('/', 1)
        return int(left), int(right)
    except ValueError:
        return (0, 0)


def sort_pods(pods: list[PodSummary], column: int, ascending: bool) -> list[PodSummary]:
    """Sort Pod rows. ``column`` is an index into ``POD_COLUMNS``."""
    column = max(0, min(column, len(POD_COLUMNS) - 1))

    def key(pod: PodSummary) -> tuple[object, ...]:
        values: tuple[object, ...] = (
            pod.namespace,
            pod.name,
            _ready_sort_key(pod.ready),
            pod.phase,
            pod.restarts,
            pod.node or '',
        )
        return (values[column], pod.namespace, pod.name)

    return sorted(pods, key=key, reverse=not ascending)


class PodListScreen(NavigationMixin, Screen[None]):
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
        namespace: str,
        enable_watch: bool = True,
    ) -> None:
        super().__init__()
        self.info = info
        self.cluster = cluster
        self.kind = POD_KIND
        self.namespace = namespace
        self.enable_watch = enable_watch
        self._namespaces: list[str] = []
        self._pods: dict[str, PodSummary] = {}
        self.sort_column = 0
        self.sort_ascending = True
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None
        self._auth = initial_actions(cluster, POD_KIND)
        self._auth_key: str | None = None

    def on_mount(self) -> None:
        self._set_subtitle()
        if self.enable_watch:
            self.run_worker(self._load_initial, exclusive=True, group='pods-load')
        else:
            self._load_sync()

    def on_unmount(self) -> None:
        self._stop_watch()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static('', id='pods-status'),
            ResourceTable(id='pods', cursor_type='row'),
            id='pods-wrap',
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
            self.run_worker(self._open_detail(key), exclusive=True, group='pod-detail')

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
            self.run_worker(self._load_initial, exclusive=True, group='pods-load')
        else:
            self._load_sync()

    def _on_kind_chosen(self, chosen: str | None) -> None:
        self._on_nav_kind(chosen)

    async def action_refresh(self) -> None:
        self._stop_watch()
        if self.enable_watch:
            await self._load_initial()
        else:
            self._load_sync()

    def action_delete(self) -> None:
        key = selected_row_key(self.query_one('#pods', DataTable))
        if not key:
            return
        namespace, name = key.split('/', 1)
        request_delete(
            self,
            self.cluster,
            POD_KIND,
            name,
            namespace,
            allow_delete=self._auth.delete,
            allow_evict=self._auth.evict,
            on_success=self._on_deleted,
        )

    def _on_deleted(self, deleted: DeletedObject) -> None:
        if deleted.namespace:
            self._pods.pop(f'{deleted.namespace}/{deleted.name}', None)
            self._render_table()

    def _load_sync(self) -> None:
        try:
            namespaces, pods = self._fetch()
            self._apply_list(namespaces, pods)
            self._set_status('')
        except Exception as exc:
            self._set_status(api_error_message(exc))

    async def _load_initial(self) -> None:
        try:
            namespaces, pods = await asyncio.to_thread(self._fetch)
            self._apply_list(namespaces, pods)
            self._set_status('')
        except Exception as exc:
            self._set_status(api_error_message(exc))
        if self.enable_watch:
            self._start_watch()

    def _fetch(self) -> tuple[list[str], list[PodSummary]]:
        try:
            namespaces = self.cluster.list_namespaces()
        except Exception:
            namespaces = [self.namespace] if self.namespace != ALL_NAMESPACES else []
        pods = self.cluster.list_pods(self.namespace)
        return namespaces, pods

    def _apply_list(self, namespaces: list[str], pods: list[PodSummary]) -> None:
        self._namespaces = namespaces
        self._pods = {pod.key: pod for pod in pods}
        self._render_table()
        self._set_subtitle()
        key = selected_row_key(self.query_one('#pods', DataTable))
        self._queue_auth(key)

    def _apply_event(self, event_type: str, pod: PodSummary) -> None:
        self._pods = apply_watch_event(self._pods, event_type, pod)
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one('#pods', DataTable)
        if not table.columns:
            table.add_columns(*POD_COLUMNS)
        table.clear()
        for pod in sort_pods(list(self._pods.values()), self.sort_column, self.sort_ascending):
            table.add_row(
                pod.namespace,
                pod.name,
                pod.ready,
                pod.phase,
                str(pod.restarts),
                pod.node or '',
                key=pod.key,
            )

    async def _open_detail(self, key: str) -> None:
        namespace, name = key.split('/', 1)
        try:
            detail = await asyncio.to_thread(self.cluster.get_pod, namespace, name)
        except Exception as exc:
            self._set_status(api_error_message(exc))
            return
        await self.app.push_screen(PodDetailScreen(detail, self.cluster, self.enable_watch))

    def _start_watch(self) -> None:
        if not hasattr(self.cluster, 'watch_pods'):
            return
        self._stop_watch()
        stop = threading.Event()
        self._watch_stop = stop

        def _run() -> None:
            self.cluster.watch_pods(
                self.namespace,
                stop,
                lambda event_type, pod: self.app.call_from_thread(self._apply_event, event_type, pod),
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
            self._auth = initial_actions(self.cluster, POD_KIND)
            self.refresh_bindings()
            return
        self.run_worker(self._load_row_auth(key), exclusive=True, group='auth')

    async def _load_row_auth(self, key: str) -> None:
        namespace, name = key.split('/', 1)
        auth = await asyncio.to_thread(actions_for, self.cluster, POD_KIND, namespace, name)
        if self._auth_key != key:
            return
        self._auth = auth
        self.refresh_bindings()

    def _set_status(self, message: str) -> None:
        self.query_one('#pods-status', Static).update(message)

    def _set_subtitle(self) -> None:
        context = self.info.context_name or 'no context'
        namespace = ALL_LABEL if self.namespace == ALL_NAMESPACES else self.namespace
        self.sub_title = f'{context} / {namespace}'
