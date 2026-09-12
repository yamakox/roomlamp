"""Two-level main menu: Headlamp sidebar groups, then implemented kinds."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from roomlamp.ui.nav import NAV_GROUPS, NavGroup, group_by_id


class MainMenuScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def compose(self) -> ComposeResult:
        options = [Option(group.label, id=group.id) for group in NAV_GROUPS]
        yield Vertical(
            Label('Select group'),
            OptionList(*options, id='menu-list'),
            id='menu-dialog',
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            self.dismiss(None)
            return
        group = group_by_id(str(option_id))
        if group is None or not group.implemented:
            self.notify('No screens in this group yet')
            return
        self.dismiss(group.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


def current_kind_index(group: NavGroup, current: str | None) -> int:
    if current is None:
        return 0
    for index, item in enumerate(group.kinds):
        if item.kind == current:
            return index
    return 0
