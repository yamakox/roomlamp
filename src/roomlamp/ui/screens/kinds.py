"""Modal list for switching the active workload kind."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from roomlamp.k8s.workloads import KIND_LABELS, PICKER_KINDS


class WorkloadKindScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, current: str) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        options = []
        for kind in PICKER_KINDS:
            mark = ' (current)' if kind == self.current else ''
            options.append(Option(f'{KIND_LABELS[kind]}{mark}', id=kind))
        yield Vertical(
            Label('Select workload'),
            OptionList(*options, id='kind-list'),
            id='kind-dialog',
        )

    def on_mount(self) -> None:
        highlighted = 0
        if self.current in PICKER_KINDS:
            highlighted = PICKER_KINDS.index(self.current)
        self.query_one('#kind-list', OptionList).highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            self.dismiss(None)
            return
        self.dismiss(str(option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
