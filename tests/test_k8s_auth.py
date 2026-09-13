from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.auth import (
    SUBRESOURCE_EVICTION,
    SUBRESOURCE_EXEC,
    SUBRESOURCE_LOG,
    ResourceActions,
    api_resource_for_kind,
    resource_actions,
    review_access,
)
from roomlamp.k8s.gateway import GATEWAY, GATEWAY_CLASS, HTTP_ROUTE
from roomlamp.k8s.network import ENDPOINT_SLICE, ENDPOINTS, INGRESS, SERVICE
from roomlamp.k8s.catalog import NAMESPACE, NODE
from roomlamp.k8s.configuration import CONFIG_MAP, SECRET
from roomlamp.k8s.security import CLUSTER_ROLE, CLUSTER_ROLE_BINDING, ROLE, ROLE_BINDING, SERVICE_ACCOUNT
from roomlamp.k8s.storage import PV, PVC, STORAGE_CLASS
from roomlamp.k8s.workloads import CRONJOB, DEPLOYMENT, JOB, POD_KIND


class FakeStatus:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.reason = 'test'


class FakeReview:
    def __init__(self, allowed: bool) -> None:
        self.status = FakeStatus(allowed)


class FakeAuthApi:
    def __init__(self, *, allowed: bool = True, error: Exception | None = None) -> None:
        self.allowed = allowed
        self.error = error
        self.reviews: list[object] = []

    def create_self_subject_access_review(self, body, **kwargs):
        self.reviews.append(body)
        if self.error is not None:
            raise self.error
        return FakeReview(self.allowed)


class FakeChecker:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str, str | None, str | None, str | None]] = []

    def check_access(
        self,
        verb: str,
        kind: str,
        *,
        namespace: str | None = None,
        name: str | None = None,
        subresource: str | None = None,
    ) -> bool:
        self.calls.append((verb, kind, namespace, name, subresource))
        return self.allowed


def test_api_resource_for_kind_matches_headlamp_api_names() -> None:
    pod = api_resource_for_kind(POD_KIND)
    assert (pod.group, pod.version, pod.resource) == ('', 'v1', 'pods')
    deployment = api_resource_for_kind(DEPLOYMENT)
    assert (deployment.group, deployment.version, deployment.resource) == ('apps', 'v1', 'deployments')
    job = api_resource_for_kind(JOB)
    assert (job.group, job.version, job.resource) == ('batch', 'v1', 'jobs')
    cron = api_resource_for_kind(CRONJOB)
    assert (cron.group, cron.version, cron.resource) == ('batch', 'v1', 'cronjobs')
    pvc = api_resource_for_kind(PVC)
    assert (pvc.group, pvc.version, pvc.resource) == ('', 'v1', 'persistentvolumeclaims')
    pv = api_resource_for_kind(PV)
    assert (pv.group, pv.version, pv.resource) == ('', 'v1', 'persistentvolumes')
    storage_class = api_resource_for_kind(STORAGE_CLASS)
    assert (storage_class.group, storage_class.version, storage_class.resource) == (
        'storage.k8s.io',
        'v1',
        'storageclasses',
    )
    service = api_resource_for_kind(SERVICE)
    assert (service.group, service.version, service.resource) == ('', 'v1', 'services')
    endpoints = api_resource_for_kind(ENDPOINTS)
    assert (endpoints.group, endpoints.version, endpoints.resource) == ('', 'v1', 'endpoints')
    endpoint_slice = api_resource_for_kind(ENDPOINT_SLICE)
    assert (endpoint_slice.group, endpoint_slice.version, endpoint_slice.resource) == (
        'discovery.k8s.io',
        'v1',
        'endpointslices',
    )
    ingress = api_resource_for_kind(INGRESS)
    assert (ingress.group, ingress.version, ingress.resource) == (
        'networking.k8s.io',
        'v1',
        'ingresses',
    )
    gateway = api_resource_for_kind(GATEWAY)
    assert (gateway.group, gateway.version, gateway.resource) == (
        'gateway.networking.k8s.io',
        'v1',
        'gateways',
    )
    gateway_class = api_resource_for_kind(GATEWAY_CLASS)
    assert (gateway_class.group, gateway_class.version, gateway_class.resource) == (
        'gateway.networking.k8s.io',
        'v1',
        'gatewayclasses',
    )
    http_route = api_resource_for_kind(HTTP_ROUTE)
    assert (http_route.group, http_route.version, http_route.resource) == (
        'gateway.networking.k8s.io',
        'v1',
        'httproutes',
    )
    service_account = api_resource_for_kind(SERVICE_ACCOUNT)
    assert (service_account.group, service_account.version, service_account.resource) == (
        '',
        'v1',
        'serviceaccounts',
    )
    role = api_resource_for_kind(ROLE)
    assert (role.group, role.version, role.resource) == ('rbac.authorization.k8s.io', 'v1', 'roles')
    role_binding = api_resource_for_kind(ROLE_BINDING)
    assert (role_binding.group, role_binding.version, role_binding.resource) == (
        'rbac.authorization.k8s.io',
        'v1',
        'rolebindings',
    )
    cluster_role = api_resource_for_kind(CLUSTER_ROLE)
    assert (cluster_role.group, cluster_role.version, cluster_role.resource) == (
        'rbac.authorization.k8s.io',
        'v1',
        'clusterroles',
    )
    cluster_role_binding = api_resource_for_kind(CLUSTER_ROLE_BINDING)
    assert (cluster_role_binding.group, cluster_role_binding.version, cluster_role_binding.resource) == (
        'rbac.authorization.k8s.io',
        'v1',
        'clusterrolebindings',
    )
    config_map = api_resource_for_kind(CONFIG_MAP)
    assert (config_map.group, config_map.version, config_map.resource) == ('', 'v1', 'configmaps')
    secret = api_resource_for_kind(SECRET)
    assert (secret.group, secret.version, secret.resource) == ('', 'v1', 'secrets')
    namespace = api_resource_for_kind(NAMESPACE)
    assert (namespace.group, namespace.version, namespace.resource) == ('', 'v1', 'namespaces')
    node = api_resource_for_kind(NODE)
    assert (node.group, node.version, node.resource) == ('', 'v1', 'nodes')


def test_review_access_posts_self_subject_access_review() -> None:
    api = FakeAuthApi()
    assert review_access(api, 'delete', POD_KIND, namespace='default', name='web') is True
    body = api.reviews[0]
    attrs = body.spec.resource_attributes
    assert body.kind == 'SelfSubjectAccessReview'
    assert attrs.verb == 'delete'
    assert attrs.group == ''
    assert attrs.version == 'v1'
    assert attrs.resource == 'pods'
    assert attrs.namespace == 'default'
    assert attrs.name == 'web'
    assert attrs.subresource is None


def test_review_access_evict_uses_create_on_eviction_subresource() -> None:
    api = FakeAuthApi()
    review_access(
        api,
        'create',
        POD_KIND,
        namespace='default',
        name='web',
        subresource=SUBRESOURCE_EVICTION,
    )
    attrs = api.reviews[0].spec.resource_attributes
    assert attrs.verb == 'create'
    assert attrs.resource == 'pods'
    assert attrs.subresource == 'eviction'


def test_review_access_denies_on_false_invalid_verb_and_errors() -> None:
    denied = FakeAuthApi(allowed=False)
    assert review_access(denied, 'delete', POD_KIND, namespace='default', name='web') is False
    invalid = FakeAuthApi()
    assert review_access(invalid, 'not-a-verb', POD_KIND, namespace='default', name='web') is False
    assert invalid.reviews == []
    failing = FakeAuthApi(error=ApiException(status=403, reason='Forbidden'))
    assert review_access(failing, 'delete', POD_KIND, namespace='default', name='web') is False
    unknown = FakeAuthApi()
    assert review_access(unknown, 'delete', 'HorizontalPodAutoscaler', namespace='default', name='web') is False
    assert unknown.reviews == []


def test_review_access_storage_class_is_cluster_scoped() -> None:
    api = FakeAuthApi()
    assert review_access(api, 'delete', STORAGE_CLASS, namespace='', name='standard') is True
    attrs = api.reviews[0].spec.resource_attributes
    assert attrs.group == 'storage.k8s.io'
    assert attrs.resource == 'storageclasses'
    assert attrs.namespace is None
    assert attrs.name == 'standard'


def test_resource_actions_uses_headlamp_authvisible_verbs() -> None:
    checker = FakeChecker()
    actions = resource_actions(checker, POD_KIND, 'default', 'web')
    assert actions.update is True
    assert actions.delete is True
    assert actions.evict is True
    assert actions.logs is True
    assert actions.exec is True
    assert actions.can_remove is True
    assert checker.calls == [
        ('update', POD_KIND, 'default', 'web', None),
        ('delete', POD_KIND, 'default', 'web', None),
        ('create', POD_KIND, 'default', 'web', SUBRESOURCE_EVICTION),
        ('get', POD_KIND, 'default', 'web', SUBRESOURCE_LOG),
        ('create', POD_KIND, 'default', 'web', SUBRESOURCE_EXEC),
    ]


def test_resource_actions_workloads_omit_pod_subresources() -> None:
    checker = FakeChecker(allowed=False)
    actions = resource_actions(checker, DEPLOYMENT, 'default', 'web')
    assert actions == ResourceActions.none()
    verbs = [(verb, sub) for verb, _kind, _ns, _name, sub in checker.calls]
    assert verbs == [('update', None), ('delete', None)]
