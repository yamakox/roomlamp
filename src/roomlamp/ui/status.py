"""Status line that occupies no space when there is no message."""

from __future__ import annotations

from textual.widgets import Static


def status_widget(widget_id: str) -> Static:
    """Create a hidden status line; ``set_status`` shows it when there is text."""
    widget = Static('', id=widget_id)
    widget.display = False
    return widget


def set_status(widget: Static, message: str) -> None:
    """Update a status line and hide it when ``message`` is empty."""
    widget.update(message)
    widget.display = bool(message)
