"""Container picker shared by Pod logs and exec."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class ContainerScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, containers: tuple[str, ...], current: str) -> None:
        super().__init__()
        self.containers = containers
        self.current = current

    def compose(self) -> ComposeResult:
        options = []
        for name in self.containers:
            mark = ' (current)' if name == self.current else ''
            options.append(Option(f'{name}{mark}', id=name))
        yield Vertical(
            Label('Select container'),
            OptionList(*options, id='container-list'),
            id='container-dialog',
        )

    def on_mount(self) -> None:
        highlighted = 0
        if self.current in self.containers:
            highlighted = self.containers.index(self.current)
        self.query_one('#container-list', OptionList).highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            self.dismiss(None)
            return
        self.dismiss(str(option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
