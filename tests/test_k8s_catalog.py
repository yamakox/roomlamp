from datetime import datetime, timezone

import pytest
from kubernetes.client.models import (
    V1Namespace,
    V1NamespaceCondition,
    V1NamespaceStatus,
    V1Node,
    V1NodeAddress,
    V1NodeCondition,
    V1NodeSpec,
    V1NodeStatus,
    V1NodeSystemInfo,
    V1ObjectMeta,
    V1Taint,
)

from roomlamp.k8s.catalog import (
    CLUSTER_SPECS,
    NAMESPACE,
    NODE,
    detail_catalog,
    is_namespaced,
    is_protected_namespace,
    protected_confirm_name,
    split_catalog_key,
    summarize_catalog,
)
from roomlamp.k8s.watch import apply_watch_event

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _ns_meta(name: str, labels: dict[str, str] | None = None) -> V1ObjectMeta:
    return V1ObjectMeta(
        name=name,
        uid='uid-1',
        creation_timestamp=CREATED,
        labels=labels if labels is not None else {'kubernetes.io/metadata.name': name},
    )


def _namespace(
    name: str = 'apps',
    phase: str = 'Active',
    *,
    labels: dict[str, str] | None = None,
    conditions: list[V1NamespaceCondition] | None = None,
) -> V1Namespace:
    return V1Namespace(
        metadata=_ns_meta(name, labels),
        status=V1NamespaceStatus(phase=phase, conditions=conditions),
    )


def _node(
    *,
    name: str = 'node-a',
    ready: str = 'True',
    unschedulable: bool | None = None,
    roles: dict[str, str] | None = None,
    taints: list[V1Taint] | None = None,
    external_ip: str | None = '203.0.113.10',
) -> V1Node:
    labels = roles if roles is not None else {'node-role.kubernetes.io/control-plane': ''}
    addresses = [V1NodeAddress(type='InternalIP', address='10.0.0.1')]
    if external_ip:
        addresses.append(V1NodeAddress(type='ExternalIP', address=external_ip))
    addresses.append(V1NodeAddress(type='Hostname', address=name))
    return V1Node(
        metadata=V1ObjectMeta(name=name, uid='uid-node', creation_timestamp=CREATED, labels=labels),
        spec=V1NodeSpec(
            unschedulable=unschedulable,
            pod_cidr='10.244.0.0/24',
            taints=taints,
        ),
        status=V1NodeStatus(
            conditions=[V1NodeCondition(type='Ready', status=ready)],
            addresses=addresses,
            capacity={'cpu': '4', 'memory': '16Gi', 'pods': '110', 'ephemeral-storage': '100Gi'},
            allocatable={'cpu': '3800m', 'memory': '15Gi', 'pods': '110'},
            node_info=V1NodeSystemInfo(
                architecture='amd64',
                boot_id='boot',
                container_runtime_version='containerd://2.0',
                kernel_version='6.8',
                kube_proxy_version='v1.34.0',
                kubelet_version='v1.34.0',
                machine_id='machine',
                operating_system='linux',
                os_image='Ubuntu 24.04',
                system_uuid='uuid',
            ),
        ),
    )


def test_summarize_namespace_matches_headlamp_and_kubectl() -> None:
    summary = summarize_catalog(NAMESPACE, _namespace(), now=NOW)
    assert summary.key == 'apps'
    assert summary.cells == ('apps', 'Active', '1d')
    assert summary.confirm_name is None
    fields = dict(detail_catalog(NAMESPACE, _namespace(), now=NOW).fields)
    assert fields['Status'] == 'Active'


def test_namespace_conditions_on_detail() -> None:
    obj = _namespace(
        conditions=[
            V1NamespaceCondition(
                type='NamespaceDeletionDiscoveryFailure',
                status='True',
                reason='DiscoveryFailed',
                message='timed out',
            )
        ]
    )
    fields = dict(detail_catalog(NAMESPACE, obj, now=NOW).fields)
    assert fields['Condition NamespaceDeletionDiscoveryFailure'] == 'True (DiscoveryFailed, timed out)'


def test_protected_namespaces_match_headlamp() -> None:
    for name in ('kube-system', 'kube-node-lease', 'kube-public', 'default'):
        obj = _namespace(name)
        summary = summarize_catalog(NAMESPACE, obj, now=NOW)
        assert summary.confirm_name == name
        assert is_protected_namespace(name)
        assert protected_confirm_name(NAMESPACE, name) == name
    custom = summarize_catalog(NAMESPACE, _namespace('apps'), now=NOW)
    assert custom.confirm_name is None
    assert is_protected_namespace('apps') is False
    labeled = _namespace('apps', labels={'kubernetes.io/metadata.name': 'kube-system'})
    assert summarize_catalog(NAMESPACE, labeled, now=NOW).confirm_name == 'kube-system'


def test_summarize_node_matches_headlamp_and_kubectl() -> None:
    taint = V1Taint(key='node-role.kubernetes.io/control-plane', effect='NoSchedule')
    summary = summarize_catalog(NODE, _node(taints=[taint]), now=NOW)
    assert summary.key == 'node-a'
    assert summary.cells == (
        'node-a',
        'Yes',
        'node-role.kubernetes.io/control-plane:NoSchedule',
        'control-plane',
        '10.0.0.1',
        '203.0.113.10',
        'v1.34.0',
        '1d',
    )
    fields = dict(detail_catalog(NODE, _node(taints=[taint], unschedulable=True), now=NOW).fields)
    assert fields['Ready'] == 'Yes'
    assert fields['Conditions'] == 'Scheduling Disabled'
    assert fields['Roles'] == 'control-plane'
    assert fields['Taints'] == 'node-role.kubernetes.io/control-plane:NoSchedule'
    assert fields['Pod CIDR'] == '10.244.0.0/24'
    assert fields['InternalIP'] == '10.0.0.1'
    assert fields['ExternalIP'] == '203.0.113.10'
    assert fields['Capacity cpu'] == '4'
    assert fields['Allocatable memory'] == '15Gi'
    assert fields['Kubelet Version'] == 'v1.34.0'
    assert fields['OS'] == 'linux'


def test_node_not_ready_without_taints_or_external_ip() -> None:
    summary = summarize_catalog(
        NODE,
        _node(ready='False', roles={'kubernetes.io/hostname': 'node-a'}, external_ip=None),
        now=NOW,
    )
    assert summary.cells[1] == 'No'
    assert summary.cells[2] == ''
    assert summary.cells[3] == ''
    assert summary.cells[5] == ''
    fields = dict(detail_catalog(NODE, _node(unschedulable=False), now=NOW).fields)
    assert fields['Conditions'] == 'Scheduling Enabled'
    assert fields['Taints'] == '(none)'


def test_catalog_specs_and_keys() -> None:
    assert is_namespaced(NAMESPACE) is False
    assert is_namespaced(NODE) is False
    assert split_catalog_key(NAMESPACE, 'kube-system') == ('', 'kube-system')
    assert split_catalog_key(NODE, 'node-a') == ('', 'node-a')
    assert CLUSTER_SPECS[NAMESPACE].api_version == 'v1'
    assert CLUSTER_SPECS[NAMESPACE].resource == 'namespaces'
    assert CLUSTER_SPECS[NODE].api_version == 'v1'
    assert CLUSTER_SPECS[NODE].resource == 'nodes'


def test_unknown_cluster_kind_raises() -> None:
    with pytest.raises(ValueError, match='Unknown cluster kind'):
        summarize_catalog('Event', _namespace())


def test_apply_watch_event_on_namespace() -> None:
    first = summarize_catalog(NAMESPACE, _namespace(), now=NOW)
    items = apply_watch_event({}, 'ADDED', first)
    assert items[first.key].cells[1] == 'Active'
    updated = summarize_catalog(NAMESPACE, _namespace(phase='Terminating'), now=NOW)
    items = apply_watch_event(items, 'MODIFIED', updated)
    assert items[first.key].cells[1] == 'Terminating'
    items = apply_watch_event(items, 'DELETED', updated)
    assert first.key not in items
