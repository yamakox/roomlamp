"""Modal list for switching the active namespace."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from roomlamp.k8s.resources import ALL_NAMESPACES

ALL_LABEL = 'All namespaces'


class NamespaceScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, namespaces: list[str], current: str) -> None:
        super().__init__()
        self.namespaces = namespaces
        self.current = current

    def compose(self) -> ComposeResult:
        options = [Option(ALL_LABEL, id=ALL_NAMESPACES)]
        for name in self.namespaces:
            mark = ' (current)' if name == self.current else ''
            options.append(Option(f'{name}{mark}', id=name))
        yield Vertical(
            Label('Select namespace'),
            OptionList(*options, id='namespace-list'),
            id='namespace-dialog',
        )

    def on_mount(self) -> None:
        highlighted = 0
        if self.current != ALL_NAMESPACES and self.current in self.namespaces:
            highlighted = self.namespaces.index(self.current) + 1
        self.query_one('#namespace-list', OptionList).highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            self.dismiss(None)
            return
        self.dismiss(str(option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
