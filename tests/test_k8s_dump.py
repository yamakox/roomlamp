from datetime import datetime, timezone

from kubernetes.client.models import (
    V1Container,
    V1ManagedFieldsEntry,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
    V1PodStatus,
)

from roomlamp.k8s.dump import dump_resource


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
