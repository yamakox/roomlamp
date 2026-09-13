from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.delete import (
    ACTION_DELETE,
    ACTION_EVICT,
    api_version_for_kind,
    delete_object,
    delete_params,
    evict_pod,
)


class FakeResource:
    def __init__(self, *, namespaced: bool = True, error: Exception | None = None) -> None:
        self.namespaced = namespaced
        self.error = error
        self.deleted: list[tuple[str | None, str | None, dict[str, object]]] = []

    def delete(self, name=None, namespace=None, **kwargs):
        if self.error is not None:
            raise self.error
        self.deleted.append((name, namespace, dict(kwargs)))
        return {'metadata': {'name': name, 'namespace': namespace}}


class FakeCore:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.evictions: list[tuple[str, str, object]] = []

    def create_namespaced_pod_eviction(self, name, namespace, body, **kwargs):
        if self.error is not None:
            raise self.error
        self.evictions.append((name, namespace, body))
        return body


def test_api_version_for_kind_matches_workload_groups() -> None:
    assert api_version_for_kind('Pod') == 'v1'
    assert api_version_for_kind('Deployment') == 'apps/v1'
    assert api_version_for_kind('Job') == 'batch/v1'
    assert api_version_for_kind('CronJob') == 'batch/v1'
    assert api_version_for_kind('PersistentVolumeClaim') == 'v1'
    assert api_version_for_kind('PersistentVolume') == 'v1'
    assert api_version_for_kind('StorageClass') == 'storage.k8s.io/v1'
    assert api_version_for_kind('Service') == 'v1'
    assert api_version_for_kind('Endpoints') == 'v1'
    assert api_version_for_kind('EndpointSlice') == 'discovery.k8s.io/v1'
    assert api_version_for_kind('Ingress') == 'networking.k8s.io/v1'
    assert api_version_for_kind('Gateway') == 'gateway.networking.k8s.io/v1'
    assert api_version_for_kind('GatewayClass') == 'gateway.networking.k8s.io/v1'
    assert api_version_for_kind('HTTPRoute') == 'gateway.networking.k8s.io/v1'
    try:
        api_version_for_kind('ConfigMap')
    except ValueError as exc:
        assert 'unsupported kind' in str(exc)
    else:
        raise AssertionError('expected unknown kind to fail')


def test_delete_params_job_background_and_force_grace() -> None:
    assert delete_params('Deployment', False) == {}
    assert delete_params('Job', False) == {'propagation_policy': 'Background'}
    assert delete_params('Pod', True) == {'grace_period_seconds': 0}
    assert delete_params('Job', True) == {
        'propagation_policy': 'Background',
        'grace_period_seconds': 0,
    }


def test_delete_object_namespaced_resource() -> None:
    resource = FakeResource()
    deleted = delete_object(resource, 'web', kind='Pod', namespace='default')
    assert deleted.label == 'Pod default/web'
    assert deleted.force is False
    assert deleted.action == ACTION_DELETE
    assert resource.deleted == [('web', 'default', {})]


def test_delete_object_force_and_job_policy() -> None:
    resource = FakeResource()
    deleted = delete_object(resource, 'batch', kind='Job', namespace='jobs', force=True)
    assert deleted.force is True
    assert resource.deleted == [
        (
            'batch',
            'jobs',
            {'propagation_policy': 'Background', 'grace_period_seconds': 0},
        )
    ]


def test_delete_object_cluster_scoped_omits_namespace() -> None:
    resource = FakeResource(namespaced=False)
    deleted = delete_object(resource, 'worker', kind='Node', namespace='ignored')
    assert deleted.namespace is None
    assert deleted.label == 'Node worker'
    assert resource.deleted == [('worker', None, {})]


def test_delete_object_requires_name_and_namespace() -> None:
    resource = FakeResource()
    try:
        delete_object(resource, '', kind='Pod', namespace='default')
    except ValueError as exc:
        assert 'name' in str(exc)
    else:
        raise AssertionError('expected empty name to fail')
    try:
        delete_object(resource, 'web', kind='Pod')
    except ValueError as exc:
        assert 'namespace' in str(exc)
    else:
        raise AssertionError('expected missing namespace to fail')


def test_delete_object_propagates_api_errors() -> None:
    resource = FakeResource(error=ApiException(status=403, reason='Forbidden'))
    try:
        delete_object(resource, 'web', kind='Pod', namespace='default')
    except ApiException as exc:
        assert exc.status == 403
    else:
        raise AssertionError('expected API error to propagate')


def test_evict_pod_posts_metadata_only() -> None:
    core = FakeCore()
    deleted = evict_pod(core, 'default', 'web')
    assert deleted.action == ACTION_EVICT
    assert deleted.label == 'Pod default/web'
    assert deleted.force is False
    assert len(core.evictions) == 1
    name, namespace, body = core.evictions[0]
    assert name == 'web'
    assert namespace == 'default'
    assert body.metadata.name == 'web'
    assert body.metadata.namespace == 'default'


def test_evict_pod_requires_name_and_namespace() -> None:
    core = FakeCore()
    try:
        evict_pod(core, 'default', '')
    except ValueError as exc:
        assert 'name' in str(exc)
    else:
        raise AssertionError('expected empty name to fail')
    try:
        evict_pod(core, '', 'web')
    except ValueError as extra:
        assert 'namespace' in str(extra)
    else:
        raise AssertionError('expected missing namespace to fail')
