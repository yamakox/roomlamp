from datetime import datetime, timezone

from kubernetes.client.models import (
    V1Node,
    V1NodeAddress,
    V1NodeCondition,
    V1NodeStatus,
    V1NodeSystemInfo,
    V1ObjectMeta,
)

from roomlamp.k8s.metrics import METRICS_NOT_FOUND, NodeMetricsResult, NodeUsage
from roomlamp.k8s.nodes import build_home_snapshot, summarize_node
from roomlamp.k8s.resources import PodSummary

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _node(
    *,
    name: str = 'node-a',
    ready: str = 'True',
    roles: dict[str, str] | None = None,
    cpu: str = '4',
    memory: str = '16Gi',
    ip: str = '10.0.0.1',
    version: str = 'v1.34.0',
) -> V1Node:
    labels = roles if roles is not None else {'node-role.kubernetes.io/control-plane': ''}
    return V1Node(
        metadata=V1ObjectMeta(name=name, creation_timestamp=CREATED, labels=labels),
        status=V1NodeStatus(
            conditions=[V1NodeCondition(type='Ready', status=ready)],
            addresses=[V1NodeAddress(type='InternalIP', address=ip)],
            capacity={'cpu': cpu, 'memory': memory},
            node_info=V1NodeSystemInfo(
                architecture='amd64',
                boot_id='boot',
                container_runtime_version='containerd://1',
                kernel_version='6.8',
                kube_proxy_version=version,
                kubelet_version=version,
                machine_id='machine',
                operating_system='linux',
                os_image='Ubuntu',
                system_uuid='uuid',
            ),
        ),
    )


def test_summarize_node_ready_roles_and_ip() -> None:
    summary = summarize_node(_node(), now=datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert summary.name == 'node-a'
    assert summary.ready is True
    assert summary.roles == 'control-plane'
    assert summary.internal_ip == '10.0.0.1'
    assert summary.version == 'v1.34.0'
    assert summary.age == '1d'
    assert summary.cpu_capacity == 4.0
    assert summary.memory_capacity == 16 * 1024**3
    assert summary.key == 'node-a'


def test_summarize_node_not_ready_without_role() -> None:
    summary = summarize_node(_node(ready='False', roles={'kubernetes.io/hostname': 'node-a'}))
    assert summary.ready is False
    assert summary.roles == ''


def test_build_home_snapshot_counts_and_metrics() -> None:
    nodes = [summarize_node(_node()), summarize_node(_node(name='node-b', ready='False', cpu='2'))]
    pods = [
        PodSummary('web', 'default', 'Running', '1/1', 0, 'node-a', True),
        PodSummary('job', 'default', 'Succeeded', '0/1', 0, 'node-a', False),
        PodSummary('bad', 'default', 'Pending', '0/1', 0, None, False),
    ]
    metrics = NodeMetricsResult(
        {
            'node-a': NodeUsage(1.0, 8 * 1024**3),
            'node-b': NodeUsage(0.5, 1 * 1024**3),
        },
        'ok',
    )
    snapshot = build_home_snapshot(nodes, pods, metrics)
    assert snapshot.nodes_ready == 1
    assert snapshot.nodes_total == 2
    assert snapshot.pods_ready == 2
    assert snapshot.pods_total == 3
    assert snapshot.cpu_used == 1.5
    assert snapshot.cpu_capacity == 6.0
    assert snapshot.memory_used == 9 * 1024**3


def test_build_home_snapshot_without_metrics() -> None:
    nodes = [summarize_node(_node())]
    snapshot = build_home_snapshot(nodes, [], NodeMetricsResult({}, METRICS_NOT_FOUND))
    assert snapshot.cpu_used is None
    assert snapshot.cpu_capacity == 4.0
    assert snapshot.metrics_status == METRICS_NOT_FOUND
