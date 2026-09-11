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
    assert review_access(unknown, 'delete', 'ConfigMap', namespace='default', name='web') is False
    assert unknown.reviews == []


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
