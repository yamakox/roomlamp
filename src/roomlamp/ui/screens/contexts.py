"""Modal list for switching the active kubeconfig context."""

from __future__ import annotations

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class ContextScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, contexts: Sequence[str], current: str | None) -> None:
        super().__init__()
        self.contexts = tuple(contexts)
        self.current = current

    def compose(self) -> ComposeResult:
        options = []
        for name in self.contexts:
            mark = ' (current)' if name == self.current else ''
            options.append(Option(f'{name}{mark}', id=name))
        yield Vertical(
            Label('Select context'),
            OptionList(*options, id='context-list'),
            id='context-dialog',
        )

    def on_mount(self) -> None:
        highlighted = 0
        if self.current in self.contexts:
            highlighted = self.contexts.index(self.current)
        self.query_one('#context-list', OptionList).highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            self.dismiss(None)
            return
        self.dismiss(str(option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
