import asyncio

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from roomlamp.ui.widgets.data_table import ResourceTable


class EmptyTableApp(App[None]):
    CSS = """
    #workloads {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield ResourceTable(id='workloads', cursor_type='row')


class HeaderTableApp(App[None]):
    selected_column: int | None = None

    def compose(self) -> ComposeResult:
        table = ResourceTable(id='workloads', cursor_type='row')
        table.add_columns('Name', 'Ready')
        table.add_row('web', '1/1', key='default/web')
        yield table

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        self.selected_column = event.column_index


def test_empty_resource_table_click_does_not_crash() -> None:
    app = EmptyTableApp()

    async def _run() -> None:
        async with app.run_test() as pilot:
            table = app.query_one('#workloads', ResourceTable)
            assert not table.columns
            await pilot.click('#workloads')
            assert table.row_count == 0

    asyncio.run(_run())


def test_resource_table_header_click_selects_column() -> None:
    app = HeaderTableApp()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.click('#workloads')
            assert app.selected_column == 0

    asyncio.run(_run())
