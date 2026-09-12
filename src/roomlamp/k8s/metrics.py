"""Node metrics from metrics.k8s.io (Headlamp cluster overview / node list)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from kubernetes.client import ApiClient, CustomObjectsApi
from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.errors import api_error_message
from roomlamp.k8s.resources import PodSummary

METRICS_OK = 'ok'
METRICS_NOT_FOUND = 'not_found'
METRICS_FORBIDDEN = 'forbidden'
METRICS_ERROR = 'error'

_BINARY = {
    'Ki': 1024,
    'Mi': 1024**2,
    'Gi': 1024**3,
    'Ti': 1024**4,
    'Pi': 1024**5,
    'Ei': 1024**6,
}
_DECIMAL = {
    'k': 1e3,
    'K': 1e3,
    'M': 1e6,
    'G': 1e9,
    'T': 1e12,
    'P': 1e15,
    'E': 1e18,
}
_MILLI_BYTES = re.compile(r'^\d+(?:\.\d+)?m$')


@dataclass(frozen=True)
class NodeUsage:
    cpu_used: float
    memory_used: float


@dataclass(frozen=True)
class NodeMetricsResult:
    by_node: dict[str, NodeUsage]
    status: str
    message: str = ''


def parse_cpu(value: str | None) -> float:
    """Parse a Kubernetes CPU quantity into cores."""
    if not value:
        return 0.0
    text = str(value).strip()
    if text.endswith('n'):
        return float(text[:-1]) / 1_000_000_000
    if text.endswith('u'):
        return float(text[:-1]) / 1_000_000
    if text.endswith('m'):
        return float(text[:-1]) / 1_000
    return float(text)


def parse_memory(value: str | None) -> float:
    """Parse a Kubernetes memory quantity into bytes (Headlamp parseRam)."""
    if not value:
        return 0.0
    text = str(value).strip()
    if _MILLI_BYTES.fullmatch(text):
        return float(text[:-1]) / 1000.0
    for suffix, multiplier in _BINARY.items():
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * multiplier
    for suffix, multiplier in _DECIMAL.items():
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * multiplier
    return float(text)


def list_node_metrics(api_client: ApiClient) -> NodeMetricsResult:
    """GET /apis/metrics.k8s.io/v1beta1/nodes. Never raises for 403/404."""
    api = CustomObjectsApi(api_client)
    try:
        raw = api.list_cluster_custom_object('metrics.k8s.io', 'v1beta1', 'nodes')
    except ApiException as exc:
        if exc.status == 404:
            return NodeMetricsResult({}, METRICS_NOT_FOUND)
        if exc.status == 403:
            return NodeMetricsResult({}, METRICS_FORBIDDEN)
        return NodeMetricsResult({}, METRICS_ERROR, api_error_message(exc))
    except Exception as exc:
        return NodeMetricsResult({}, METRICS_ERROR, api_error_message(exc))
    by_node: dict[str, NodeUsage] = {}
    items = raw.get('items') if isinstance(raw, dict) else None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        meta = item.get('metadata') or {}
        name = str(meta.get('name') or '')
        usage = item.get('usage') or {}
        by_node[name] = NodeUsage(
            cpu_used=parse_cpu(usage.get('cpu') if isinstance(usage, dict) else None),
            memory_used=parse_memory(usage.get('memory') if isinstance(usage, dict) else None),
        )
    return NodeMetricsResult(by_node, METRICS_OK)


def pod_is_overview_ready(pod: PodSummary) -> bool:
    """Headlamp PodsStatusCircleChart: Succeeded, or Ready=True."""
    return pod.phase == 'Succeeded' or pod.condition_ready
