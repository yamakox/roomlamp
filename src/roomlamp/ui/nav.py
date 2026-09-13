"""Headlamp in-cluster sidebar groups for the main menu.

Later phases add kinds to a group; empty groups stay visible but are not selectable.
"""

from __future__ import annotations

from dataclasses import dataclass

from roomlamp.k8s.gateway import GATEWAY_LABELS
from roomlamp.k8s.network import NETWORK_KINDS, NETWORK_LABELS
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
    NavGroup(
        'network',
        'Network',
        tuple(NavKind(kind, NETWORK_LABELS[kind]) for kind in NETWORK_KINDS),
    ),
    NavGroup('gateway', 'Gateway', ()),
    NavGroup('security', 'Security', ()),
    NavGroup('configuration', 'Configuration', ()),
)


def groups_for(cluster: object | None = None) -> tuple[NavGroup, ...]:
    """Sidebar groups, with Gateway kinds filled in when the API serves them."""
    gateway = _gateway_nav_kinds(cluster)
    return tuple(
        NavGroup(group.id, group.label, gateway if group.id == 'gateway' else group.kinds) for group in NAV_GROUPS
    )


def group_by_id(group_id: str, cluster: object | None = None) -> NavGroup | None:
    for group in groups_for(cluster):
        if group.id == group_id:
            return group
    return None


def _gateway_nav_kinds(cluster: object | None) -> tuple[NavKind, ...]:
    lister = getattr(cluster, 'available_gateway_kinds', None)
    if not callable(lister):
        return ()
    try:
        kinds = lister()
    except Exception:
        return ()
    return tuple(NavKind(kind, GATEWAY_LABELS[kind]) for kind in kinds if kind in GATEWAY_LABELS)
