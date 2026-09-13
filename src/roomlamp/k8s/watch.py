"""Watch Pod, workload, storage, network, and gateway events with the official client."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol, TypeVar

from kubernetes.client import ApiClient, CoreV1Api
from kubernetes.watch import Watch

from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.gateway import ApiGatewayReader, GatewaySummary, summarize_gateway
from roomlamp.k8s.network import ApiNetworkReader, NetworkSummary, summarize_network
from roomlamp.k8s.resources import ALL_NAMESPACES, PodSummary, summarize_pod
from roomlamp.k8s.storage import ApiStorageReader, StorageSummary, summarize_storage
from roomlamp.k8s.workloads import ApiWorkloadReader, WorkloadSummary, summarize_workload

TKeyed = TypeVar('TKeyed', bound='HasKey')
WatchCallback = Callable[[str, PodSummary], None]
WorkloadWatchCallback = Callable[[str, WorkloadSummary], None]
StorageWatchCallback = Callable[[str, StorageSummary], None]
NetworkWatchCallback = Callable[[str, NetworkSummary], None]
GatewayWatchCallback = Callable[[str, GatewaySummary], None]
ErrorCallback = Callable[[str], None]
Summarize = Callable[[object], TKeyed]


class HasKey(Protocol):
    @property
    def key(self) -> str: ...


class PodWatcher(Protocol):
    def watch_pods(
        self,
        namespace: str,
        stop: threading.Event,
        on_event: WatchCallback,
        on_error: ErrorCallback,
    ) -> None: ...


class WorkloadWatcher(Protocol):
    def watch_workloads(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: WorkloadWatchCallback,
        on_error: ErrorCallback,
    ) -> None: ...


class StorageWatcher(Protocol):
    def watch_storage(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: StorageWatchCallback,
        on_error: ErrorCallback,
    ) -> None: ...


class NetworkWatcher(Protocol):
    def watch_network(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: NetworkWatchCallback,
        on_error: ErrorCallback,
    ) -> None: ...


class GatewayWatcher(Protocol):
    def watch_gateway(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: GatewayWatchCallback,
        on_error: ErrorCallback,
    ) -> None: ...


class ApiPodWatcher:
    def __init__(self, api_client: ApiClient) -> None:
        self._core = CoreV1Api(api_client)

    def watch_pods(
        self,
        namespace: str,
        stop: threading.Event,
        on_event: WatchCallback,
        on_error: ErrorCallback,
    ) -> None:
        if namespace == ALL_NAMESPACES:
            list_fn = self._core.list_pod_for_all_namespaces
            args: tuple[object, ...] = ()
        else:
            list_fn = self._core.list_namespaced_pod
            args = (namespace,)
        watch_stream(list_fn, args, stop, summarize_pod, on_event, on_error)


class ApiWorkloadWatcher:
    def __init__(self, api_client: ApiClient) -> None:
        self._workload_reader = ApiWorkloadReader(api_client)

    def watch_workloads(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: WorkloadWatchCallback,
        on_error: ErrorCallback,
    ) -> None:
        list_fn, args = self._workload_reader.list_call(kind, namespace)
        watch_stream(
            list_fn,
            args,
            stop,
            lambda raw: summarize_workload(kind, raw),
            on_event,
            on_error,
        )


class ApiStorageWatcher:
    def __init__(self, api_client: ApiClient) -> None:
        self._storage_reader = ApiStorageReader(api_client)

    def watch_storage(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: StorageWatchCallback,
        on_error: ErrorCallback,
    ) -> None:
        list_fn, args = self._storage_reader.storage_list_call(kind, namespace)
        watch_stream(
            list_fn,
            args,
            stop,
            lambda raw: summarize_storage(kind, raw),
            on_event,
            on_error,
        )


class ApiNetworkWatcher:
    def __init__(self, api_client: ApiClient) -> None:
        self._network_reader = ApiNetworkReader(api_client)

    def watch_network(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: NetworkWatchCallback,
        on_error: ErrorCallback,
    ) -> None:
        list_fn, args = self._network_reader.network_list_call(kind, namespace)
        watch_stream(
            list_fn,
            args,
            stop,
            lambda raw: summarize_network(kind, raw),
            on_event,
            on_error,
        )


class ApiGatewayWatcher:
    def __init__(self, api_client: ApiClient) -> None:
        self._gateway_reader = ApiGatewayReader(api_client)

    def watch_gateway(
        self,
        kind: str,
        namespace: str,
        stop: threading.Event,
        on_event: GatewayWatchCallback,
        on_error: ErrorCallback,
    ) -> None:
        list_fn, args = self._gateway_reader.gateway_list_call(kind, namespace)
        watch_stream(
            list_fn,
            args,
            stop,
            lambda raw: summarize_gateway(kind, raw),
            on_event,
            on_error,
        )


def watch_stream(
    list_fn: object,
    args: tuple[object, ...],
    stop: threading.Event,
    summarize: Summarize[TKeyed],
    on_event: Callable[[str, TKeyed], None],
    on_error: ErrorCallback,
) -> None:
    watcher = Watch()
    while not stop.is_set():
        try:
            for event in watcher.stream(list_fn, *args, timeout_seconds=30):
                if stop.is_set():
                    watcher.stop()
                    return
                event_type = str(event.get('type') or '')
                raw = event.get('object')
                if raw is None:
                    continue
                on_event(event_type, summarize(raw))
        except Exception as exc:
            if stop.is_set():
                return
            on_error(api_error_message(exc))
            return


def apply_watch_event(
    items: dict[str, TKeyed],
    event_type: str,
    item: TKeyed,
) -> dict[str, TKeyed]:
    """Return a new map after ADDED / MODIFIED / DELETED."""
    updated = dict(items)
    if event_type == 'DELETED':
        updated.pop(item.key, None)
    elif event_type != 'BOOKMARK':
        updated[item.key] = item
    return updated
