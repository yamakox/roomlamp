"""Shared navigation keys and screen-stack helpers."""

from __future__ import annotations

from typing import Any

from textual.binding import Binding

MENU_BINDING = Binding('m', 'show_menu', 'Menu')
HOME_BINDING = Binding('h', 'show_home', 'Home')


def pop_to_home(app: Any) -> None:
    """Pop screens until Home is current. Does not push another Home."""
    from roomlamp.ui.screens.home import HomeScreen

    while len(app.screen_stack) > 1 and not isinstance(app.screen, HomeScreen):
        app.pop_screen()


def open_kind(app: Any, kind: str, namespace: str) -> None:
    """Leave Home underneath and show the list for ``kind``."""
    from roomlamp.ui.screens.workloads import show_kind_list

    pop_to_home(app)
    info = app.cluster_info
    cluster = app.cluster
    if cluster is None or not info.ok:
        return
    show_kind_list(
        app,
        info,
        cluster,
        kind,
        namespace,
        getattr(app, 'enable_watch', True),
        replace=False,
    )


class NavigationMixin:
    """``m`` Menu and ``h`` Home for screens that sit above Home."""

    def action_show_menu(self) -> None:
        app = self.app  # type: ignore[attr-defined]
        if getattr(app, 'cluster', None) is None:
            return
        from roomlamp.ui.screens.menu import MainMenuScreen

        app.push_screen(MainMenuScreen(), callback=self._on_nav_group)

    def action_show_home(self) -> None:
        pop_to_home(self.app)  # type: ignore[attr-defined]

    def _on_nav_group(self, group_id: str | None) -> None:
        if group_id is None:
            return
        from roomlamp.ui.nav import group_by_id
        from roomlamp.ui.screens.kinds import KindPickerScreen

        group = group_by_id(group_id)
        if group is None or not group.implemented:
            return
        current = getattr(self, 'kind', None)
        self.app.push_screen(  # type: ignore[attr-defined]
            KindPickerScreen(group, current),
            callback=self._on_nav_kind,
        )

    def _on_nav_kind(self, kind: str | None) -> None:
        if kind is None:
            return
        from roomlamp.ui.screens.menu import MENU_BACK

        if kind == MENU_BACK:
            self.action_show_menu()
            return
        info = getattr(self, 'info', None) or getattr(self.app, 'cluster_info', None)  # type: ignore[attr-defined]
        namespace = getattr(self, 'namespace', None) or (info.namespace if info else None) or 'default'
        open_kind(self.app, kind, namespace)  # type: ignore[attr-defined]
