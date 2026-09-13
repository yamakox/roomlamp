from datetime import datetime, timezone

import yaml
from kubernetes.client.models import (
    V1ConfigMap,
    V1Container,
    V1ManagedFieldsEntry,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
    V1PodStatus,
    V1Service,
    V1ServiceSpec,
)

from roomlamp.k8s.dump import dump_resource

LAST_APPLIED = (
    '{"apiVersion":"v1","kind":"Service","metadata":{"annotations":{},'
    '"name":"metallb-webhook-service","namespace":"metallb-system"},'
    '"spec":{"ports":[{"port":443,"targetPort":9443}],'
    '"selector":{"component":"controller"}}}\n'
)


def test_dump_resource_hides_managed_fields_and_fills_gvk() -> None:
    pod = V1Pod(
        metadata=V1ObjectMeta(
            name='web',
            namespace='default',
            uid='uid-1',
            creation_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
            managed_fields=[V1ManagedFieldsEntry(manager='kubectl', operation='Update')],
            labels={'app': 'web'},
        ),
        spec=V1PodSpec(containers=[V1Container(name='app', image='nginx:1')]),
        status=V1PodStatus(phase='Running'),
    )
    text = dump_resource(pod, kind='Pod', api_version='v1')
    assert 'apiVersion: v1' in text
    assert 'kind: Pod' in text
    assert 'name: web' in text
    assert 'managedFields' not in text
    assert 'dummy-token' not in text


def test_dump_resource_can_keep_managed_fields() -> None:
    pod = V1Pod(
        metadata=V1ObjectMeta(
            name='web',
            namespace='default',
            managed_fields=[V1ManagedFieldsEntry(manager='kubectl', operation='Update')],
        )
    )
    text = dump_resource(pod, kind='Pod', api_version='v1', hide_managed_fields=False)
    assert 'managedFields' in text
    assert 'kubectl' in text


def test_dump_resource_folds_last_applied_configuration() -> None:
    service = V1Service(
        metadata=V1ObjectMeta(
            name='metallb-webhook-service',
            namespace='metallb-system',
            annotations={'kubectl.kubernetes.io/last-applied-configuration': LAST_APPLIED},
        ),
        spec=V1ServiceSpec(cluster_ip='10.103.35.223'),
    )
    text = dump_resource(service, kind='Service', api_version='v1')
    assert 'kubectl.kubernetes.io/last-applied-configuration: >' in text
    assert "\n      '" not in text
    loaded = yaml.safe_load(text)
    assert loaded['metadata']['annotations']['kubectl.kubernetes.io/last-applied-configuration'] == LAST_APPLIED


def test_dump_resource_uses_literal_for_multiline_configmap_data() -> None:
    body = 'allowed_directories:\n- /etc/nginx\n- /usr/share/nginx\nfeatures:\n- configuration\n- certificates\n'
    config_map = V1ConfigMap(
        metadata=V1ObjectMeta(name='agent', namespace='default'),
        data={'nginx-agent.conf': body},
    )
    text = dump_resource(config_map, kind='ConfigMap', api_version='v1')
    assert 'nginx-agent.conf: |' in text
    assert '- /etc/nginx\n    - /usr/share/nginx' in text
    assert '- /etc/nginx\n\n    - /usr/share/nginx' not in text
    loaded = yaml.safe_load(text)
    assert loaded['data']['nginx-agent.conf'] == body
