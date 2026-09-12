"""Headlamp in-cluster sidebar groups for the main menu.

Later phases add kinds to a group; empty groups stay visible but are not selectable.
"""

from __future__ import annotations

from dataclasses import dataclass

from roomlamp.k8s.storage import STORAGE_KINDS, STORAGE_LABELS
from roomlamp.k8s.workloads import KIND_LABELS, PICKER_KINDS


@dataclass(frozen=True)
class NavKind:
    kind: str
    label: str


@dataclass(frozen=True)
class NavGroup:
    id: str
    label: str
    kinds: tuple[NavKind, ...]

    @property
    def implemented(self) -> bool:
        return bool(self.kinds)


NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup('cluster', 'Cluster', ()),
    NavGroup(
        'workloads',
        'Workloads',
        tuple(NavKind(kind, KIND_LABELS[kind]) for kind in PICKER_KINDS),
    ),
    NavGroup(
        'storage',
        'Storage',
        tuple(NavKind(kind, STORAGE_LABELS[kind]) for kind in STORAGE_KINDS),
    ),
    NavGroup('network', 'Network', ()),
    NavGroup('gateway', 'Gateway', ()),
    NavGroup('security', 'Security', ()),
    NavGroup('configuration', 'Configuration', ()),
)


def group_by_id(group_id: str) -> NavGroup | None:
    for group in NAV_GROUPS:
        if group.id == group_id:
            return group
    return None
