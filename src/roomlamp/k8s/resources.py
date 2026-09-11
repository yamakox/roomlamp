"""Read Kubernetes resources with the official client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api
from kubernetes.client.models import V1Pod

ALL_NAMESPACES = '*'


@dataclass(frozen=True)
class PodSummary:
    name: str
    namespace: str
    phase: str
    ready: str
    restarts: int
    node: str | None

    @property
    def key(self) -> str:
        return f'{self.namespace}/{self.name}'


@dataclass(frozen=True)
class PodDetail:
    name: str
    namespace: str
    uid: str | None
    created: str | None
    phase: str
    ready: str
    restarts: int
    node: str | None
    pod_ip: str | None
    labels: tuple[tuple[str, str], ...]
    containers: tuple[str, ...]


class PodReader(Protocol):
    def list_namespaces(self) -> list[str]: ...

    def list_pods(self, namespace: str) -> list[PodSummary]: ...

    def get_pod(self, namespace: str, name: str) -> PodDetail: ...


class ApiPodReader:
    """Pod reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._api_client = api_client
        self._core = CoreV1Api(api_client)

    def list_namespaces(self) -> list[str]:
        items = self._core.list_namespace().items or []
        names = [ns.metadata.name for ns in items if ns.metadata and ns.metadata.name]
        return sorted(names)

    def list_pods(self, namespace: str) -> list[PodSummary]:
        if namespace == ALL_NAMESPACES:
            items = self._core.list_pod_for_all_namespaces().items or []
        else:
            items = self._core.list_namespaced_pod(namespace).items or []
        return [summarize_pod(pod) for pod in items]

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        return detail_pod(self._core.read_namespaced_pod(name, namespace))


def summarize_pod(pod: V1Pod) -> PodSummary:
    meta = pod.metadata
    status = pod.status
    spec = pod.spec
    ready, total, restarts = _container_counts(pod)
    return PodSummary(
        name=meta.name if meta and meta.name else '',
        namespace=meta.namespace if meta and meta.namespace else '',
        phase=(status.phase if status and status.phase else 'Unknown'),
        ready=f'{ready}/{total}',
        restarts=restarts,
        node=spec.node_name if spec else None,
    )


def detail_pod(pod: V1Pod) -> PodDetail:
    summary = summarize_pod(pod)
    meta = pod.metadata
    status = pod.status
    labels = ()
    if meta and meta.labels:
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and meta.creation_timestamp:
        created = _format_time(meta.creation_timestamp)
    containers = _container_lines(pod)
    return PodDetail(
        name=summary.name,
        namespace=summary.namespace,
        uid=meta.uid if meta else None,
        created=created,
        phase=summary.phase,
        ready=summary.ready,
        restarts=summary.restarts,
        node=summary.node,
        pod_ip=status.pod_ip if status else None,
        labels=labels,
        containers=containers,
    )


def _container_counts(pod: V1Pod) -> tuple[int, int, int]:
    spec = pod.spec
    status = pod.status
    spec_count = len(spec.containers) if spec and spec.containers else 0
    statuses = status.container_statuses if status and status.container_statuses else []
    total = len(statuses) or spec_count
    ready = sum(1 for item in statuses if item.ready)
    restarts = sum(item.restart_count or 0 for item in statuses)
    return ready, total, restarts


def _container_lines(pod: V1Pod) -> tuple[str, ...]:
    status = pod.status
    statuses = status.container_statuses if status and status.container_statuses else []
    if statuses:
        lines = []
        for item in statuses:
            state = _container_state(item)
            lines.append(
                f'{item.name}: {state} ready={item.ready} restarts={item.restart_count or 0} image={item.image}'
            )
        return tuple(lines)
    spec = pod.spec
    if spec and spec.containers:
        return tuple(f'{item.name}: image={item.image}' for item in spec.containers)
    return ()


def _container_state(item: object) -> str:
    state = getattr(item, 'state', None)
    if state is None:
        return 'unknown'
    if getattr(state, 'running', None) is not None:
        return 'running'
    if getattr(state, 'waiting', None) is not None:
        reason = getattr(state.waiting, 'reason', None) or 'waiting'
        return str(reason)
    if getattr(state, 'terminated', None) is not None:
        reason = getattr(state.terminated, 'reason', None) or 'terminated'
        return str(reason)
    return 'unknown'


def _format_time(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
