"""Read Kubernetes resources with the official client."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api
from kubernetes.client.models import V1Pod

from roomlamp.k8s.dump import dump_resource
from roomlamp.k8s.exec import open_pod_exec as _open_pod_exec
from roomlamp.k8s.logs import DEFAULT_TAIL_LINES
from roomlamp.k8s.logs import read_pod_logs as _read_pod_logs
from roomlamp.k8s.logs import watch_pod_logs as _watch_pod_logs

ALL_NAMESPACES = '*'
POD_API_VERSION = 'v1'


@dataclass(frozen=True)
class PodSummary:
    name: str
    namespace: str
    phase: str
    ready: str
    restarts: int
    node: str | None
    condition_ready: bool = False

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
    container_names: tuple[str, ...] = ()
    default_container: str = ''
    node_os: str | None = None


class PodReader(Protocol):
    def list_namespaces(self) -> list[str]: ...

    def list_pods(self, namespace: str) -> list[PodSummary]: ...

    def get_pod(self, namespace: str, name: str) -> PodDetail: ...

    def get_pod_yaml(self, namespace: str, name: str, hide_managed_fields: bool = True) -> str: ...

    def read_pod_logs(
        self,
        namespace: str,
        name: str,
        *,
        container: str | None = None,
        tail_lines: int = DEFAULT_TAIL_LINES,
        timestamps: bool = True,
        previous: bool = False,
    ) -> str: ...

    def open_pod_exec(self, namespace: str, name: str, *, container: str, command: str) -> object: ...


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

    def get_pod_yaml(self, namespace: str, name: str, hide_managed_fields: bool = True) -> str:
        pod = self._core.read_namespaced_pod(name, namespace)
        return dump_resource(
            pod,
            kind='Pod',
            api_version=POD_API_VERSION,
            hide_managed_fields=hide_managed_fields,
        )

    def read_pod_logs(
        self,
        namespace: str,
        name: str,
        *,
        container: str | None = None,
        tail_lines: int = DEFAULT_TAIL_LINES,
        timestamps: bool = True,
        previous: bool = False,
    ) -> str:
        return _read_pod_logs(
            self._core,
            namespace,
            name,
            container=container,
            tail_lines=tail_lines,
            timestamps=timestamps,
            previous=previous,
        )

    def watch_pod_logs(
        self,
        namespace: str,
        name: str,
        stop: threading.Event,
        on_line: Callable[[str], None],
        on_error: Callable[[str], None],
        *,
        container: str | None = None,
        tail_lines: int = DEFAULT_TAIL_LINES,
        timestamps: bool = True,
        previous: bool = False,
        on_open: Callable[[object], None] | None = None,
    ) -> None:
        _watch_pod_logs(
            self._core,
            namespace,
            name,
            stop,
            on_line,
            on_error,
            container=container,
            tail_lines=tail_lines,
            timestamps=timestamps,
            previous=previous,
            on_open=on_open,
        )

    def open_pod_exec(self, namespace: str, name: str, *, container: str, command: str) -> object:
        return _open_pod_exec(
            self._core,
            namespace,
            name,
            container=container,
            command=command,
        )


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
        condition_ready=_pod_condition_ready(pod),
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
    names = pod_container_names(pod)
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
        container_names=names,
        default_container=default_container_name(pod),
        node_os=pod_node_os(pod),
    )


def pod_node_os(pod: V1Pod) -> str | None:
    """Return kubernetes.io/os (or the beta key) from the pod node selector."""
    spec = pod.spec
    selector = spec.node_selector if spec is not None else None
    if not selector:
        return None
    value = selector.get('kubernetes.io/os') or selector.get('beta.kubernetes.io/os')
    return str(value) if value else None


def pod_container_names(pod: V1Pod) -> tuple[str, ...]:
    """Main, init, then ephemeral containers — same order as Headlamp."""
    spec = pod.spec
    if spec is None:
        return ()
    names: list[str] = []
    for group in (spec.containers, spec.init_containers, spec.ephemeral_containers):
        if not group:
            continue
        names.extend(item.name for item in group if getattr(item, 'name', None))
    return tuple(names)


def default_container_name(pod: V1Pod) -> str:
    """Prefer a running main container, then a running init, then the first spec name."""
    status = pod.status
    if status is not None:
        running = _first_running_name(status.container_statuses)
        if running:
            return running
        running = _first_running_name(status.init_container_statuses)
        if running:
            return running
    names = pod_container_names(pod)
    return names[0] if names else ''


def _first_running_name(statuses: object | None) -> str:
    if not statuses:
        return ''
    for item in statuses:
        state = getattr(item, 'state', None)
        if state is not None and getattr(state, 'running', None) is not None:
            name = getattr(item, 'name', None)
            if name:
                return str(name)
    return ''


def _pod_condition_ready(pod: V1Pod) -> bool:
    status = pod.status
    if status is None:
        return False
    for condition in status.conditions or []:
        if getattr(condition, 'type', None) == 'Ready' and getattr(condition, 'status', None) == 'True':
            return True
    return False


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
