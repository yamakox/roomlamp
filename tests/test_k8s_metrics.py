from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.metrics import (
    METRICS_FORBIDDEN,
    METRICS_NOT_FOUND,
    METRICS_OK,
    list_node_metrics,
    parse_cpu,
    parse_memory,
    pod_is_overview_ready,
)
from roomlamp.k8s.resources import PodSummary


class _FakeApi:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def list_cluster_custom_object(self, group: str, version: str, plural: str) -> object:
        assert (group, version, plural) == ('metrics.k8s.io', 'v1beta1', 'nodes')
        if self.error is not None:
            raise self.error
        return self.result


def test_parse_cpu_cores_and_suffixes() -> None:
    assert parse_cpu('2') == 2.0
    assert parse_cpu('500m') == 0.5
    assert parse_cpu('250000000n') == 0.25
    assert parse_cpu(None) == 0.0


def test_parse_memory_binary_and_milli() -> None:
    assert parse_memory('1Ki') == 1024
    assert parse_memory('1Mi') == 1024**2
    assert parse_memory('2Gi') == 2 * 1024**3
    assert parse_memory('1000m') == 1.0
    assert parse_memory('1G') == 1e9
    assert parse_memory(None) == 0.0


def test_pod_is_overview_ready() -> None:
    running = PodSummary('web', 'default', 'Running', '1/1', 0, 'n', True)
    succeeded = PodSummary('job', 'default', 'Succeeded', '0/1', 0, 'n', False)
    pending = PodSummary('wait', 'default', 'Pending', '0/1', 0, None, False)
    assert pod_is_overview_ready(running) is True
    assert pod_is_overview_ready(succeeded) is True
    assert pod_is_overview_ready(pending) is False


def test_list_node_metrics_ok(monkeypatch) -> None:
    fake = _FakeApi(
        {
            'items': [
                {'metadata': {'name': 'node-a'}, 'usage': {'cpu': '250m', 'memory': '1Gi'}},
            ]
        }
    )
    monkeypatch.setattr('roomlamp.k8s.metrics.CustomObjectsApi', lambda _client: fake)
    result = list_node_metrics(object())
    assert result.status == METRICS_OK
    assert result.by_node['node-a'].cpu_used == 0.25
    assert result.by_node['node-a'].memory_used == 1024**3


def test_list_node_metrics_404_and_403(monkeypatch) -> None:
    monkeypatch.setattr(
        'roomlamp.k8s.metrics.CustomObjectsApi',
        lambda _client: _FakeApi(error=ApiException(status=404, reason='Not Found')),
    )
    missing = list_node_metrics(object())
    assert missing.status == METRICS_NOT_FOUND
    assert missing.by_node == {}

    monkeypatch.setattr(
        'roomlamp.k8s.metrics.CustomObjectsApi',
        lambda _client: _FakeApi(error=ApiException(status=403, reason='Forbidden')),
    )
    forbidden = list_node_metrics(object())
    assert forbidden.status == METRICS_FORBIDDEN
