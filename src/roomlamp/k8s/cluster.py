"""Live cluster access used by the TUI."""

from __future__ import annotations

from kubernetes.client import ApiClient, AuthorizationV1Api
from kubernetes.dynamic import DynamicClient

from roomlamp.k8s.apply import AppliedObject, apply_yaml as apply_documents
from roomlamp.k8s.auth import review_access
from roomlamp.k8s.client import build_api_client
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.delete import (
    DeletedObject,
    api_version_for_kind,
    delete_object as delete_resource_object,
    evict_pod as evict_pod_object,
)
from roomlamp.k8s.gateway import ApiGatewayReader
from roomlamp.k8s.network import ApiNetworkReader
from roomlamp.k8s.nodes import ApiNodeReader
from roomlamp.k8s.resources import ApiPodReader
from roomlamp.k8s.security import ApiSecurityReader
from roomlamp.k8s.storage import ApiStorageReader
from roomlamp.k8s.watch import (
    ApiGatewayWatcher,
    ApiNetworkWatcher,
    ApiPodWatcher,
    ApiSecurityWatcher,
    ApiStorageWatcher,
    ApiWorkloadWatcher,
)
from roomlamp.k8s.workloads import ApiWorkloadReader


class ClusterAccess(
    ApiPodReader,
    ApiPodWatcher,
    ApiWorkloadReader,
    ApiWorkloadWatcher,
    ApiStorageReader,
    ApiStorageWatcher,
    ApiNetworkReader,
    ApiNetworkWatcher,
    ApiGatewayReader,
    ApiGatewayWatcher,
    ApiSecurityReader,
    ApiSecurityWatcher,
    ApiNodeReader,
):
    """Read, watch, apply, exec, and delete cluster objects with one shared API client."""

    def __init__(self, api_client: ApiClient) -> None:
        ApiPodReader.__init__(self, api_client)
        ApiPodWatcher.__init__(self, api_client)
        ApiWorkloadReader.__init__(self, api_client)
        ApiWorkloadWatcher.__init__(self, api_client)
        ApiStorageReader.__init__(self, api_client)
        ApiStorageWatcher.__init__(self, api_client)
        ApiNetworkReader.__init__(self, api_client)
        ApiNetworkWatcher.__init__(self, api_client)
        ApiGatewayReader.__init__(self, api_client)
        ApiGatewayWatcher.__init__(self, api_client)
        ApiSecurityReader.__init__(self, api_client)
        ApiSecurityWatcher.__init__(self, api_client)
        ApiNodeReader.__init__(self, api_client)
        self._dynamic: DynamicClient | None = None
        self._auth_api: AuthorizationV1Api | None = None
        self._auth_cache: dict[tuple[str | None, ...], bool] = {}

    def apply_yaml(
        self,
        text: str,
        *,
        dry_run: bool = False,
        default_namespace: str = 'default',
    ) -> list[AppliedObject]:
        dynamic = self._dynamic_client()
        return apply_documents(
            text,
            lambda api_version, kind: dynamic.resources.get(api_version=api_version, kind=kind),
            dry_run=dry_run,
            default_namespace=default_namespace,
        )

    def delete_resource(
        self,
        kind: str,
        name: str,
        *,
        namespace: str | None = None,
        force: bool = False,
    ) -> DeletedObject:
        resource = self._dynamic_client().resources.get(
            api_version=api_version_for_kind(kind),
            kind=kind,
        )
        return delete_resource_object(
            resource,
            name,
            kind=kind,
            namespace=namespace,
            force=force,
        )

    def evict_pod(self, namespace: str, name: str) -> DeletedObject:
        return evict_pod_object(self._core, namespace, name)

    def check_access(
        self,
        verb: str,
        kind: str,
        *,
        namespace: str | None = None,
        name: str | None = None,
        subresource: str | None = None,
    ) -> bool:
        key = (verb, kind, namespace, name, subresource)
        cached = self._auth_cache.get(key)
        if cached is not None:
            return cached
        allowed = review_access(
            self._authorization(),
            verb,
            kind,
            namespace=namespace,
            name=name,
            subresource=subresource,
        )
        self._auth_cache[key] = allowed
        return allowed

    def _authorization(self) -> AuthorizationV1Api:
        if self._auth_api is None:
            self._auth_api = AuthorizationV1Api(self._api_client)
        return self._auth_api

    def _dynamic_client(self) -> DynamicClient:
        if self._dynamic is None:
            self._dynamic = DynamicClient(self._api_client)
        return self._dynamic


def open_cluster(info: ClusterInfo) -> ClusterAccess | None:
    if not info.ok:
        return None
    try:
        client = build_api_client(info.kubeconfig, info.context_name)
    except Exception:
        return None
    return ClusterAccess(client)
