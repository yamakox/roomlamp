"""Read kubeconfig contexts without talking to the cluster."""

from __future__ import annotations

from dataclasses import dataclass

from kubernetes.config.config_exception import ConfigException
from kubernetes.config.kube_config import list_kube_config_contexts

from roomlamp.k8s.client import resolve_kubeconfig


@dataclass(frozen=True)
class ClusterInfo:
    """Display-safe snapshot of the selected kubeconfig context.

    Credentials (tokens, client keys, certificate data) are never stored
    here.
    """

    kubeconfig: str
    context_name: str | None
    cluster_name: str | None
    user_name: str | None
    namespace: str | None
    context_names: tuple[str, ...]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.context_name is not None


def load_cluster_info(
    config_file: str | None = None,
    context: str | None = None,
) -> ClusterInfo:
    """Load context metadata from kubeconfig.

    Does not call ``load_kube_config``, so the file is not rewritten
    (the official client may persist token refreshes when that API is
    used).
    """
    kubeconfig = resolve_kubeconfig(config_file)
    empty = ClusterInfo(
        kubeconfig=kubeconfig,
        context_name=None,
        cluster_name=None,
        user_name=None,
        namespace=None,
        context_names=(),
    )
    try:
        contexts, current = list_kube_config_contexts(config_file=kubeconfig)
    except (ConfigException, OSError) as exc:
        return with_error(empty, str(exc))

    entries = tuple(contexts or ())
    names = tuple(name for entry in entries if (name := _entry_name(entry)))

    selected = current
    if context:
        selected = next((entry for entry in entries if _entry_name(entry) == context), None)
        if selected is None:
            return with_error(
                empty,
                f'context {context!r} not found in kubeconfig',
                context_names=names,
            )

    body = _context_body(selected)
    namespace = body.get('namespace') or 'default'
    return ClusterInfo(
        kubeconfig=kubeconfig,
        context_name=_entry_name(selected),
        cluster_name=_as_str(body.get('cluster')),
        user_name=_as_str(body.get('user')),
        namespace=namespace,
        context_names=names,
    )


def with_error(
    info: ClusterInfo,
    error: str,
    context_names: tuple[str, ...] | None = None,
) -> ClusterInfo:
    return ClusterInfo(
        kubeconfig=info.kubeconfig,
        context_name=None,
        cluster_name=None,
        user_name=None,
        namespace=None,
        context_names=info.context_names if context_names is None else context_names,
        error=error,
    )


def _entry_name(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    return _as_str(entry.get('name'))


def _context_body(entry: object) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {}
    body = entry.get('context') or {}
    return body if isinstance(body, dict) else {}


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
