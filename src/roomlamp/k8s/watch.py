"""Watch Pod events with the official client."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from kubernetes.client import ApiClient, CoreV1Api
from kubernetes.watch import Watch

from roomlamp.k8s.resources import ALL_NAMESPACES, PodSummary, summarize_pod

WatchCallback = Callable[[str, PodSummary], None]
ErrorCallback = Callable[[str], None]


class PodWatcher(Protocol):
    def watch_pods(
        self,
        namespace: str,
        stop: threading.Event,
        on_event: WatchCallback,
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
        watcher = Watch()
        if namespace == ALL_NAMESPACES:
            list_fn = self._core.list_pod_for_all_namespaces
            args: tuple[object, ...] = ()
        else:
            list_fn = self._core.list_namespaced_pod
            args = (namespace,)

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
                    on_event(event_type, summarize_pod(raw))
            except Exception as exc:
                if stop.is_set():
                    return
                on_error(str(exc))
                return


def apply_watch_event(
    pods: dict[str, PodSummary],
    event_type: str,
    pod: PodSummary,
) -> dict[str, PodSummary]:
    """Return a new map after ADDED / MODIFIED / DELETED."""
    updated = dict(pods)
    if event_type == 'DELETED':
        updated.pop(pod.key, None)
    elif event_type != 'BOOKMARK':
        updated[pod.key] = pod
    return updated
