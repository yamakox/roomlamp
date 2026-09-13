"""Two-level main menu: Headlamp sidebar groups, then implemented kinds."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from roomlamp.ui.nav import NAV_GROUPS, NavGroup, group_by_id

MENU_BACK = 'back'
MENU_BACK_LABEL = 'Back'


def with_back_option(options: list[Option]) -> list[Option]:
    return [*options, Option(MENU_BACK_LABEL, id=MENU_BACK)]


class MainMenuScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def compose(self) -> ComposeResult:
        options = with_back_option([Option(group.label, id=group.id) for group in NAV_GROUPS])
        yield Vertical(
            Label('Select group'),
            OptionList(*options, id='menu-list'),
            id='menu-dialog',
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None or option_id == MENU_BACK:
            self.dismiss(None)
            return
        group = group_by_id(str(option_id), getattr(self.app, 'cluster', None))
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
