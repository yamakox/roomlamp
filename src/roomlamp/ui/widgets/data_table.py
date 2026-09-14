"""DataTable that does not crash on clicks when there are no columns."""

from __future__ import annotations

from textual import events
from textual.widgets import DataTable


class ResourceTable(DataTable[str]):
    """List table that ignores header clicks outside a real column.

    Textual treats empty-area clicks as header clicks when ``cursor_type`` is
    ``row``, then indexes ``ordered_columns`` without a bounds check. That
    raises ``IndexError`` while a list is still empty (for example after
    Unauthorized). Handlers on the MRO all run, so this uses
    ``prevent_default`` instead of ``super()``.
    """

    async def _on_click(self, event: events.Click) -> None:
        meta = event.style.meta
        if 'row' in meta and 'column' in meta and self.show_header and meta['row'] == -1:
            column_index = meta['column']
            if column_index < 0 or column_index >= len(self.ordered_columns):
                event.prevent_default()
