"""Live cluster access used by the TUI."""

from __future__ import annotations

from kubernetes.client import ApiClient

from roomlamp.k8s.client import build_api_client
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ApiPodReader
from roomlamp.k8s.watch import ApiPodWatcher


class ClusterAccess(ApiPodReader, ApiPodWatcher):
    """Read and watch Pods with one shared API client."""

    def __init__(self, api_client: ApiClient) -> None:
        ApiPodReader.__init__(self, api_client)
        ApiPodWatcher.__init__(self, api_client)


def open_cluster(info: ClusterInfo) -> ClusterAccess | None:
    if not info.ok:
        return None
    try:
        client = build_api_client(info.kubeconfig, info.context_name)
    except Exception:
        return None
    return ClusterAccess(client)
