"""htop-style usage bars for the home overview and Node table."""

from __future__ import annotations

BAR_WIDTH = 10


def format_cpu(cores: float) -> str:
    return f'{cores:.2f}'


def format_memory(nbytes: float) -> str:
    gi = 1024**3
    mi = 1024**2
    if nbytes >= gi:
        return f'{nbytes / gi:.2f} Gi'
    if nbytes >= mi:
        return f'{nbytes / mi:.0f} Mi'
    if nbytes >= 1024:
        return f'{nbytes / 1024:.0f} Ki'
    return f'{nbytes:.0f} B'


def format_bar(
    used: float | None,
    capacity: float,
    *,
    used_label: str | None = None,
    capacity_label: str | None = None,
    width: int = BAR_WIDTH,
    unavailable: bool = False,
) -> str:
    empty = '░' * width
    if unavailable:
        extra = f' {capacity_label}' if capacity_label else ''
        return f'[{empty}] unavailable{extra}'
    if used is None or capacity <= 0:
        return f'[{empty}] —'
    ratio = min(1.0, max(0.0, used / capacity))
    filled = round(ratio * width)
    bar = '█' * filled + '░' * (width - filled)
    used_text = used_label if used_label is not None else f'{used:.0f}'
    cap_text = capacity_label if capacity_label is not None else f'{capacity:.0f}'
    return f'[{bar}] {used_text} / {cap_text} ({ratio * 100:.0f}%)'
