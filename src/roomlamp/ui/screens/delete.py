"""Confirm dialog for delete and Pod evict. Headlamp DeleteButton equivalent for the TUI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Input, Label, OptionList
from textual.widgets.option_list import Option

from roomlamp.k8s.apply import apply_error_message
from roomlamp.k8s.delete import ACTION_DELETE, ACTION_EVICT, DeletedObject

OPTION_DELETE = ACTION_DELETE
OPTION_FORCE = 'force'
OPTION_EVICT = ACTION_EVICT


@dataclass(frozen=True)
class DeleteChoice:
    action: str
    force: bool


class DeleteConfirmScreen(ModalScreen[DeleteChoice | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(
        self,
        kind: str,
        name: str,
        namespace: str | None,
        *,
        allow_delete: bool = True,
        allow_evict: bool = False,
        require_typed_name: str | None = None,
    ) -> None:
        super().__init__()
        self.item_kind = kind
        self.item_name = name
        self.item_namespace = namespace
        self.allow_delete = allow_delete
        self.allow_evict = allow_evict
        self.require_typed_name = require_typed_name

    def compose(self) -> ComposeResult:
        options: list[Option] = []
        if self.allow_delete:
            options.extend(
                [
                    Option('Delete', id=OPTION_DELETE),
                    Option('Force delete', id=OPTION_FORCE),
                ]
            )
        if self.allow_evict:
            options.append(Option('Evict', id=OPTION_EVICT))
        with Vertical(id='delete-dialog'):
            yield Label(
                confirm_message(self.item_kind, self.item_name, self.item_namespace),
                id='delete-prompt',
            )
            if self.require_typed_name:
                yield Label(
                    'This is a system namespace. Deleting it may break your cluster.',
                    id='delete-warning',
                )
                yield Label(
                    f'To confirm, type {self.require_typed_name} in the field below.',
                    id='delete-confirm-hint',
                )
                yield Input(
                    placeholder=self.require_typed_name,
                    id='delete-confirm-input',
                )
            yield OptionList(*options, id='delete-list')

    def on_mount(self) -> None:
        if self.require_typed_name:
            self.query_one('#delete-confirm-input', Input).focus()
            return
        option_list = self.query_one('#delete-list', OptionList)
        option_list.highlighted = 0
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id == OPTION_EVICT:
            self.dismiss(DeleteChoice(ACTION_EVICT, False))
            return
        if option_id in {OPTION_FORCE, OPTION_DELETE} and not self._typed_ok():
            self.notify('Type the namespace name to confirm.', severity='warning')
            return
        if option_id == OPTION_FORCE:
            self.dismiss(DeleteChoice(ACTION_DELETE, True))
            return
        if option_id == OPTION_DELETE:
            self.dismiss(DeleteChoice(ACTION_DELETE, False))
            return
        self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        if not self.allow_delete:
            return
        if not self._typed_ok():
            self.notify('Type the namespace name to confirm.', severity='warning')
            return
        self.dismiss(DeleteChoice(ACTION_DELETE, False))

    def _typed_ok(self) -> bool:
        if not self.require_typed_name:
            return True
        typed = self.query_one('#delete-confirm-input', Input).value.strip()
        return typed == self.require_typed_name

    def action_cancel(self) -> None:
        self.dismiss(None)


def confirm_message(kind: str, name: str, namespace: str | None) -> str:
    target = f'{namespace}/{name}' if namespace else name
    return f'Are you sure you want to delete {kind} {target}?'


def selected_row_key(table: DataTable) -> str | None:
    if table.row_count == 0:
        return None
    cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
    value = cell_key.row_key.value
    return str(value) if value is not None else None


def request_delete(
    screen: Screen[Any],
    cluster: Any,
    kind: str,
    name: str,
    namespace: str | None,
    *,
    allow_delete: bool = True,
    allow_evict: bool = False,
    require_typed_name: str | None = None,
    on_success: Callable[[DeletedObject], None] | None = None,
) -> None:
    """Open the confirm modal, then DELETE or evict off the Textual event loop."""
    if not allow_delete and not allow_evict:
        return

    def _chosen(choice: DeleteChoice | None) -> None:
        if choice is None:
            return
        screen.run_worker(
            _execute_delete(screen, cluster, kind, name, namespace, choice, on_success),
            exclusive=True,
            group='delete',
        )

    screen.app.push_screen(
        DeleteConfirmScreen(
            kind,
            name,
            namespace,
            allow_delete=allow_delete,
            allow_evict=allow_evict,
            require_typed_name=require_typed_name,
        ),
        callback=_chosen,
    )


async def _execute_delete(
    screen: Screen[Any],
    cluster: Any,
    kind: str,
    name: str,
    namespace: str | None,
    choice: DeleteChoice,
    on_success: Callable[[DeletedObject], None] | None,
) -> None:
    try:
        deleted = await asyncio.to_thread(_call_cluster, cluster, kind, name, namespace, choice)
    except Exception as exc:
        screen.notify(apply_error_message(exc), severity='error')
        return
    if deleted.action == ACTION_EVICT:
        screen.notify(f'Evicted pod {deleted.name}.')
    else:
        screen.notify(f'Deleted item {deleted.name}.')
    if on_success is not None:
        on_success(deleted)


def _call_cluster(
    cluster: Any,
    kind: str,
    name: str,
    namespace: str | None,
    choice: DeleteChoice,
) -> DeletedObject:
    if choice.action == ACTION_EVICT:
        return cluster.evict_pod(namespace, name)
    return cluster.delete_resource(kind, name, namespace=namespace or None, force=choice.force)
