"""Modal list for picking a kind inside a sidebar group."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from roomlamp.k8s.workloads import KIND_LABELS, PICKER_KINDS, POD_KIND
from roomlamp.ui.nav import NavGroup, NavKind
from roomlamp.ui.screens.menu import current_kind_index


class KindPickerScreen(ModalScreen[str | None]):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, group: NavGroup, current: str | None = None) -> None:
        super().__init__()
        self.group = group
        self.current = current

    def compose(self) -> ComposeResult:
        options = []
        for item in self.group.kinds:
            mark = ' (current)' if item.kind == self.current else ''
            options.append(Option(f'{item.label}{mark}', id=item.kind))
        yield Vertical(
            Label(f'Select {self.group.label}'),
            OptionList(*options, id='kind-list'),
            id='kind-dialog',
        )

    def on_mount(self) -> None:
        self.query_one('#kind-list', OptionList).highlighted = current_kind_index(self.group, self.current)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            self.dismiss(None)
            return
        self.dismiss(str(option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)


class WorkloadKindScreen(KindPickerScreen):
    """Workloads-only picker kept for tests that construct it directly."""

    def __init__(self, current: str = POD_KIND) -> None:
        super().__init__(
            NavGroup(
                'workloads',
                'Workloads',
                tuple(NavKind(kind, KIND_LABELS[kind]) for kind in PICKER_KINDS),
            ),
            current,
        )
