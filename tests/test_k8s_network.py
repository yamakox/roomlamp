from datetime import datetime, timezone

import pytest
from kubernetes.client.models import (
    CoreV1EndpointPort,
    DiscoveryV1EndpointPort,
    V1ClientIPConfig,
    V1Endpoint,
    V1EndpointAddress,
    V1EndpointConditions,
    V1Endpoints,
    V1EndpointSlice,
    V1EndpointSubset,
    V1HTTPIngressPath,
    V1HTTPIngressRuleValue,
    V1Ingress,
    V1IngressBackend,
    V1IngressLoadBalancerIngress,
    V1IngressLoadBalancerStatus,
    V1IngressRule,
    V1IngressServiceBackend,
    V1IngressSpec,
    V1IngressStatus,
    V1IngressTLS,
    V1LoadBalancerIngress,
    V1LoadBalancerStatus,
    V1ObjectMeta,
    V1ObjectReference,
    V1Service,
    V1ServiceBackendPort,
    V1ServicePort,
    V1ServiceSpec,
    V1ServiceStatus,
    V1SessionAffinityConfig,
    V1TypedLocalObjectReference,
)

from roomlamp.k8s.network import (
    ENDPOINT_SLICE,
    ENDPOINTS,
    INGRESS,
    NETWORK_SPECS,
    SERVICE,
    detail_network,
    is_namespaced,
    split_network_key,
    summarize_network,
)
from roomlamp.k8s.watch import apply_watch_event

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _meta(name: str, namespace: str | None = 'default') -> V1ObjectMeta:
    return V1ObjectMeta(
        name=name,
        namespace=namespace,
        uid='uid-1',
        creation_timestamp=CREATED,
        labels={'app': 'web'},
    )


def _service() -> V1Service:
    return V1Service(
        metadata=_meta('web'),
        spec=V1ServiceSpec(
            type='NodePort',
            cluster_ip='10.96.0.10',
            cluster_ips=['10.96.0.10'],
            ports=[
                V1ServicePort(name='http', port=80, target_port=8080, node_port=30080, protocol='TCP'),
            ],
            selector={'app': 'web'},
            external_ips=['203.0.113.10'],
            session_affinity='ClientIP',
            session_affinity_config=V1SessionAffinityConfig(client_ip=V1ClientIPConfig(timeout_seconds=10800)),
            external_traffic_policy='Local',
            ip_families=['IPv4'],
            ip_family_policy='SingleStack',
        ),
        status=V1ServiceStatus(
            load_balancer=V1LoadBalancerStatus(ingress=[V1LoadBalancerIngress(ip='198.51.100.2')]),
        ),
    )


def _endpoints() -> V1Endpoints:
    return V1Endpoints(
        metadata=_meta('web'),
        subsets=[
            V1EndpointSubset(
                addresses=[
                    V1EndpointAddress(
                        ip='10.1.0.5',
                        hostname='web-0',
                        target_ref=V1ObjectReference(kind='Pod', name='web-0', namespace='default'),
                    )
                ],
                not_ready_addresses=[V1EndpointAddress(ip='10.1.0.6')],
                ports=[CoreV1EndpointPort(name='http', port=80, protocol='TCP')],
            )
        ],
    )


def _endpoint_slice() -> V1EndpointSlice:
    return V1EndpointSlice(
        metadata=_meta('web-abc'),
        address_type='IPv4',
        endpoints=[
            V1Endpoint(
                addresses=['10.1.0.5'],
                hostname='web-0',
                node_name='worker',
                zone='zone-a',
                conditions=V1EndpointConditions(ready=True, serving=True, terminating=False),
            )
        ],
        ports=[DiscoveryV1EndpointPort(name='http', port=80, protocol='TCP')],
    )


def _ingress() -> V1Ingress:
    return V1Ingress(
        metadata=_meta('www'),
        spec=V1IngressSpec(
            ingress_class_name='nginx',
            default_backend=V1IngressBackend(
                service=V1IngressServiceBackend(name='fallback', port=V1ServiceBackendPort(number=8080)),
            ),
            rules=[
                V1IngressRule(
                    host='example.com',
                    http=V1HTTPIngressRuleValue(
                        paths=[
                            V1HTTPIngressPath(
                                path='/',
                                path_type='Prefix',
                                backend=V1IngressBackend(
                                    service=V1IngressServiceBackend(
                                        name='web',
                                        port=V1ServiceBackendPort(number=80),
                                    )
                                ),
                            )
                        ]
                    ),
                )
            ],
            tls=[V1IngressTLS(hosts=['example.com'], secret_name='www-tls')],
        ),
        status=V1IngressStatus(
            load_balancer=V1IngressLoadBalancerStatus(
                ingress=[V1IngressLoadBalancerIngress(ip='192.0.2.10')],
            )
        ),
    )


def test_summarize_service_matches_headlamp_and_kubectl() -> None:
    summary = summarize_network(SERVICE, _service(), now=NOW)
    assert summary.key == 'default/web'
    assert summary.cells == (
        'default',
        'web',
        'NodePort',
        '10.96.0.10',
        '198.51.100.2, 203.0.113.10',
        '80:30080/TCP',
        'app=web',
        '1d',
    )
    detail = detail_network(SERVICE, _service(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Type'] == 'NodePort'
    assert fields['Cluster IP'] == '10.96.0.10'
    assert 'Cluster IPs' not in fields
    assert fields['External IP'] == '198.51.100.2, 203.0.113.10'
    assert fields['Session Affinity'] == 'ClientIP (10800s)'
    assert fields['External Traffic Policy'] == 'Local'
    assert fields['Selector'] == 'app=web'
    assert fields['Ports'] == '80:30080/TCP'
    assert detail.labels == (('app', 'web'),)
    assert 'dummy-token' not in repr(detail)


def test_service_hides_default_affinity_and_formats_same_port() -> None:
    obj = V1Service(
        metadata=_meta('dns'),
        spec=V1ServiceSpec(
            type='ClusterIP',
            cluster_ip='10.96.0.10',
            cluster_ips=['10.96.0.10', 'fd00::10'],
            ports=[V1ServicePort(port=53, target_port=53, protocol='UDP')],
            session_affinity='None',
        ),
    )
    summary = summarize_network(SERVICE, obj, now=NOW)
    assert summary.cells[5] == '53/UDP'
    fields = dict(detail_network(SERVICE, obj, now=NOW).fields)
    assert fields['Cluster IPs'] == '10.96.0.10, fd00::10'
    assert 'Session Affinity' not in fields


def test_summarize_endpoints() -> None:
    summary = summarize_network(ENDPOINTS, _endpoints(), now=NOW)
    assert summary.key == 'default/web'
    assert summary.cells[2] == '10.1.0.5:80'
    detail = detail_network(ENDPOINTS, _endpoints(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Subset Addresses'] == '10.1.0.5 (web-0)'
    assert fields['Subset Ports'] == 'http 80/TCP'
    assert fields['Subset Not Ready'] == '10.1.0.6'


def test_summarize_endpoint_slice() -> None:
    summary = summarize_network(ENDPOINT_SLICE, _endpoint_slice(), now=NOW)
    assert summary.cells[2] == '10.1.0.5'
    assert summary.cells[3] == '80'
    assert summary.cells[4] == 'IPv4'
    detail = detail_network(ENDPOINT_SLICE, _endpoint_slice(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Address Type'] == 'IPv4'
    assert '10.1.0.5' in fields['Endpoints']
    assert 'Ready' in fields['Endpoints']
    assert fields['Ports'] == 'http 80/TCP'


def test_summarize_ingress_matches_kubectl_columns() -> None:
    summary = summarize_network(INGRESS, _ingress(), now=NOW)
    assert summary.cells == (
        'default',
        'www',
        'nginx',
        'example.com',
        '192.0.2.10',
        '80, 443',
        '1d',
    )
    detail = detail_network(INGRESS, _ingress(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Address'] == '192.0.2.10'
    assert fields['Default Backend'] == 'fallback:8080'
    assert fields['Ports'] == '80, 443'
    assert fields['TLS'] == 'www-tls › example.com'
    assert fields['Class Name'] == 'nginx'
    assert fields['Rules'] == 'example.com / (Prefix) › web:80'


def test_ingress_resource_backend_and_empty_host() -> None:
    obj = V1Ingress(
        metadata=_meta('api'),
        spec=V1IngressSpec(
            rules=[
                V1IngressRule(
                    host='',
                    http=V1HTTPIngressRuleValue(
                        paths=[
                            V1HTTPIngressPath(
                                path='/api',
                                path_type='Exact',
                                backend=V1IngressBackend(
                                    resource=V1TypedLocalObjectReference(
                                        api_group='example.com',
                                        kind='StorageBucket',
                                        name='media',
                                    )
                                ),
                            )
                        ]
                    ),
                )
            ]
        ),
    )
    summary = summarize_network(INGRESS, obj, now=NOW)
    assert summary.cells[3] == '*'
    assert summary.cells[5] == 'StorageBucket:media'
    fields = dict(detail_network(INGRESS, obj, now=NOW).fields)
    assert fields['Default Backend'] == '-'
    assert fields['Rules'] == '* /api (Exact) › StorageBucket:media'


def test_network_specs_and_keys() -> None:
    assert is_namespaced(SERVICE) is True
    assert is_namespaced(ENDPOINTS) is True
    assert is_namespaced(ENDPOINT_SLICE) is True
    assert is_namespaced(INGRESS) is True
    assert split_network_key(SERVICE, 'default/web') == ('default', 'web')
    assert NETWORK_SPECS[SERVICE].api_version == 'v1'
    assert NETWORK_SPECS[ENDPOINTS].resource == 'endpoints'
    assert NETWORK_SPECS[ENDPOINT_SLICE].api_version == 'discovery.k8s.io/v1'
    assert NETWORK_SPECS[INGRESS].api_version == 'networking.k8s.io/v1'
    assert NETWORK_SPECS[INGRESS].resource == 'ingresses'


def test_unknown_network_kind_raises() -> None:
    with pytest.raises(ValueError, match='Unknown network kind'):
        summarize_network('IngressClass', _service())


def test_apply_watch_event_on_service() -> None:
    first = summarize_network(SERVICE, _service(), now=NOW)
    items = apply_watch_event({}, 'ADDED', first)
    assert items[first.key].cells[2] == 'NodePort'
    updated_obj = _service()
    updated_obj.spec.type = 'LoadBalancer'
    updated = summarize_network(SERVICE, updated_obj, now=NOW)
    items = apply_watch_event(items, 'MODIFIED', updated)
    assert items[first.key].cells[2] == 'LoadBalancer'
    items = apply_watch_event(items, 'DELETED', updated)
    assert first.key not in items
