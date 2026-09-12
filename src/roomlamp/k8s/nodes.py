"""Node list summaries for the home screen (Headlamp Nodes list, without detail)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api
from kubernetes.client.models import V1Node

from roomlamp.k8s.metrics import (
    METRICS_OK,
    NodeMetricsResult,
    NodeUsage,
    parse_cpu,
    parse_memory,
    pod_is_overview_ready,
)
from roomlamp.k8s.resources import PodSummary
from roomlamp.k8s.workloads import format_age

ROLE_PREFIX = 'node-role.kubernetes.io/'


@dataclass(frozen=True)
class NodeSummary:
    name: str
    ready: bool
    roles: str
    internal_ip: str
    version: str
    age: str
    created: datetime | None
    cpu_capacity: float
    memory_capacity: float

    @property
    def key(self) -> str:
        return self.name


@dataclass(frozen=True)
class HomeSnapshot:
    nodes: tuple[NodeSummary, ...]
    pods_ready: int
    pods_total: int
    nodes_ready: int
    nodes_total: int
    cpu_used: float | None
    cpu_capacity: float
    memory_used: float | None
    memory_capacity: float
    metrics_status: str
    metrics_message: str
    usages: dict[str, NodeUsage]


class NodeReader(Protocol):
    def list_nodes(self) -> list[NodeSummary]: ...

    def list_node_metrics(self) -> NodeMetricsResult: ...

    def load_home(self) -> HomeSnapshot: ...


class ApiNodeReader:
    """Node reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        if not hasattr(self, '_api_client'):
            self._api_client = api_client
        if not hasattr(self, '_core'):
            self._core = CoreV1Api(api_client)

    def list_nodes(self) -> list[NodeSummary]:
        items = self._core.list_node().items or []
        return [summarize_node(node) for node in items]

    def list_node_metrics(self) -> NodeMetricsResult:
        from roomlamp.k8s.metrics import list_node_metrics

        return list_node_metrics(self._api_client)

    def load_home(self) -> HomeSnapshot:
        from roomlamp.k8s.resources import ALL_NAMESPACES

        nodes = self.list_nodes()
        try:
            pods = self.list_pods(ALL_NAMESPACES)  # type: ignore[attr-defined]
        except Exception:
            pods = []
        return build_home_snapshot(nodes, pods, self.list_node_metrics())


def summarize_node(node: V1Node, now: datetime | None = None) -> NodeSummary:
    meta = node.metadata
    status = node.status
    name = meta.name if meta and meta.name else ''
    created = meta.creation_timestamp if meta else None
    labels = meta.labels if meta and meta.labels else {}
    roles = tuple(sorted(key.removeprefix(ROLE_PREFIX) for key in labels if key.startswith(ROLE_PREFIX)))
    capacity = status.capacity if status and status.capacity else {}
    return NodeSummary(
        name=name,
        ready=_node_ready(node),
        roles=', '.join(roles),
        internal_ip=_internal_ip(node),
        version=_kubelet_version(node),
        age=format_age(created, now),
        created=created,
        cpu_capacity=parse_cpu(capacity.get('cpu')),
        memory_capacity=parse_memory(capacity.get('memory')),
    )


def build_home_snapshot(
    nodes: list[NodeSummary],
    pods: list[PodSummary],
    metrics: NodeMetricsResult,
) -> HomeSnapshot:
    cpu_capacity = sum(node.cpu_capacity for node in nodes)
    memory_capacity = sum(node.memory_capacity for node in nodes)
    has_usage = metrics.status == METRICS_OK
    cpu_used = sum(item.cpu_used for item in metrics.by_node.values()) if has_usage else None
    memory_used = sum(item.memory_used for item in metrics.by_node.values()) if has_usage else None
    return HomeSnapshot(
        nodes=tuple(nodes),
        pods_ready=sum(1 for pod in pods if pod_is_overview_ready(pod)),
        pods_total=len(pods),
        nodes_ready=sum(1 for node in nodes if node.ready),
        nodes_total=len(nodes),
        cpu_used=cpu_used,
        cpu_capacity=cpu_capacity,
        memory_used=memory_used,
        memory_capacity=memory_capacity,
        metrics_status=metrics.status,
        metrics_message=metrics.message,
        usages=dict(metrics.by_node),
    )


def _node_ready(node: V1Node) -> bool:
    status = node.status
    if status is None:
        return False
    for condition in status.conditions or []:
        if getattr(condition, 'type', None) == 'Ready' and getattr(condition, 'status', None) == 'True':
            return True
    return False


def _internal_ip(node: V1Node) -> str:
    status = node.status
    if status is None:
        return ''
    for address in status.addresses or []:
        if getattr(address, 'type', None) == 'InternalIP':
            return str(getattr(address, 'address', None) or '')
    return ''


def _kubelet_version(node: V1Node) -> str:
    status = node.status
    info = status.node_info if status is not None else None
    version = getattr(info, 'kubelet_version', None) if info is not None else None
    return str(version) if version else ''
