from textual.widgets import Static

from roomlamp.ui.status import set_status, status_widget


def test_status_widget_starts_hidden() -> None:
    widget = status_widget('pods-status')
    assert widget.id == 'pods-status'
    assert widget.display is False


def test_set_status_toggles_display() -> None:
    widget = Static('', id='pods-status')
    widget.display = False
    set_status(widget, 'Reason: Unauthorized')
    assert widget.display is True
    assert 'Unauthorized' in str(widget.content)
    set_status(widget, '')
    assert widget.display is False
    assert str(widget.content) == ''
