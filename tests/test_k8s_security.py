from datetime import datetime, timezone

import pytest
from kubernetes.client.models import (
    RbacV1Subject,
    V1ClusterRole,
    V1ClusterRoleBinding,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1ObjectReference,
    V1PolicyRule,
    V1Role,
    V1RoleBinding,
    V1RoleRef,
    V1ServiceAccount,
)

from roomlamp.k8s.security import (
    CLUSTER_ROLE,
    CLUSTER_ROLE_BINDING,
    ROLE,
    ROLE_BINDING,
    SECURITY_SPECS,
    SERVICE_ACCOUNT,
    detail_security,
    is_namespaced,
    list_kinds_for,
    split_security_key,
    summarize_security,
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
        labels={'app': 'api'},
    )


def _service_account() -> V1ServiceAccount:
    return V1ServiceAccount(
        metadata=_meta('builder'),
        secrets=[V1ObjectReference(name='builder-token')],
        image_pull_secrets=[V1LocalObjectReference(name='registry')],
        automount_service_account_token=False,
    )


def _role() -> V1Role:
    return V1Role(
        metadata=_meta('pod-reader'),
        rules=[
            V1PolicyRule(
                api_groups=[''],
                resources=['pods'],
                verbs=['get', 'list', 'watch'],
            ),
            V1PolicyRule(
                api_groups=['apps'],
                resources=['deployments'],
                verbs=['get'],
            ),
        ],
    )


def _role_binding() -> V1RoleBinding:
    return V1RoleBinding(
        metadata=_meta('pod-reader-binding'),
        role_ref=V1RoleRef(api_group='rbac.authorization.k8s.io', kind='Role', name='pod-reader'),
        subjects=[
            RbacV1Subject(kind='User', name='jane', api_group='rbac.authorization.k8s.io'),
            RbacV1Subject(kind='Group', name='devs', api_group='rbac.authorization.k8s.io'),
            RbacV1Subject(kind='ServiceAccount', name='builder', namespace='default'),
        ],
    )


def _cluster_role() -> V1ClusterRole:
    return V1ClusterRole(
        metadata=_meta('cluster-admin', namespace=None),
        rules=[V1PolicyRule(api_groups=['*'], resources=['*'], verbs=['*'])],
    )


def _cluster_role_binding() -> V1ClusterRoleBinding:
    return V1ClusterRoleBinding(
        metadata=_meta('cluster-admin-binding', namespace=None),
        role_ref=V1RoleRef(api_group='rbac.authorization.k8s.io', kind='ClusterRole', name='cluster-admin'),
        subjects=[RbacV1Subject(kind='Group', name='system:masters', api_group='rbac.authorization.k8s.io')],
    )


def test_summarize_service_account_matches_headlamp_and_kubectl() -> None:
    summary = summarize_security(SERVICE_ACCOUNT, _service_account(), now=NOW)
    assert summary.key == 'default/builder'
    assert summary.cells == ('default', 'builder', '1', '1d')
    detail = detail_security(SERVICE_ACCOUNT, _service_account(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Secrets'] == 'builder-token'
    assert fields['Image Pull Secrets'] == 'registry'
    assert fields['Automount Service Account Token'] == 'No'
    assert detail.labels == (('app', 'api'),)
    assert 'dummy-token' not in repr(detail)


def test_service_account_hides_empty_secrets_and_undefined_automount() -> None:
    obj = V1ServiceAccount(metadata=_meta('default'))
    summary = summarize_security(SERVICE_ACCOUNT, obj, now=NOW)
    assert summary.cells[2] == '0'
    fields = dict(detail_security(SERVICE_ACCOUNT, obj, now=NOW).fields)
    assert 'Secrets' not in fields
    assert 'Image Pull Secrets' not in fields
    assert 'Automount Service Account Token' not in fields


def test_summarize_role_and_rules() -> None:
    summary = summarize_security(ROLE, _role(), now=NOW)
    assert summary.key == 'default/pod-reader'
    assert summary.cells == ('Role', 'pod-reader', 'default', '1d')
    fields = dict(detail_security(ROLE, _role(), now=NOW).fields)
    assert 'Rule 1 API Groups' not in fields
    assert fields['Rule 1 Resources'] == 'pods'
    assert fields['Rule 1 Verbs'] == 'get, list, watch'
    assert fields['Rule 2 API Groups'] == 'apps'
    assert fields['Rule 2 Resources'] == 'deployments'
    assert fields['Rule 2 Verbs'] == 'get'
    assert 'Non Resources' not in ' '.join(fields)


def test_role_empty_rules_and_non_resource_urls() -> None:
    empty = V1Role(metadata=_meta('empty'), rules=[])
    assert dict(detail_security(ROLE, empty, now=NOW).fields) == {'Rules': '(none)'}
    non_resource = V1Role(
        metadata=_meta('health'),
        rules=[V1PolicyRule(non_resource_urls=['/healthz'], verbs=['get'])],
    )
    fields = dict(detail_security(ROLE, non_resource, now=NOW).fields)
    assert fields['Rule Non Resources'] == '/healthz'
    assert fields['Rule Verbs'] == 'get'


def test_summarize_role_binding_matches_headlamp() -> None:
    summary = summarize_security(ROLE_BINDING, _role_binding(), now=NOW)
    assert summary.key == 'default/pod-reader-binding'
    assert summary.cells == (
        'RoleBinding',
        'pod-reader-binding',
        'default',
        'pod-reader',
        'jane',
        'devs',
        'builder',
        '1d',
    )
    fields = dict(detail_security(ROLE_BINDING, _role_binding(), now=NOW).fields)
    assert fields['Reference Kind'] == 'Role'
    assert fields['Reference Name'] == 'pod-reader'
    assert fields['Ref. API Group'] == 'rbac.authorization.k8s.io'
    assert fields['Subject 1 Kind'] == 'User'
    assert fields['Subject 1 Name'] == 'jane'
    assert fields['Subject 2 Kind'] == 'Group'
    assert fields['Subject 3 Kind'] == 'ServiceAccount'
    assert fields['Subject 3 Namespace'] == 'default'


def test_role_binding_cluster_role_ref_and_empty_subjects() -> None:
    obj = V1RoleBinding(
        metadata=_meta('admin-binding'),
        role_ref=V1RoleRef(api_group='rbac.authorization.k8s.io', kind='ClusterRole', name='admin'),
        subjects=[],
    )
    summary = summarize_security(ROLE_BINDING, obj, now=NOW)
    assert summary.cells[3] == 'admin'
    assert summary.cells[4] == ''
    fields = dict(detail_security(ROLE_BINDING, obj, now=NOW).fields)
    assert fields['Reference Kind'] == 'ClusterRole'
    assert fields['Subjects'] == '(none)'


def test_summarize_cluster_role_and_binding() -> None:
    role = summarize_security(CLUSTER_ROLE, _cluster_role(), now=NOW)
    assert role.key == 'cluster-admin'
    assert role.cells == ('ClusterRole', 'cluster-admin', '', '1d')
    fields = dict(detail_security(CLUSTER_ROLE, _cluster_role(), now=NOW).fields)
    assert fields['Rule API Groups'] == '*'
    assert fields['Rule Verbs'] == '*'
    binding = summarize_security(CLUSTER_ROLE_BINDING, _cluster_role_binding(), now=NOW)
    assert binding.key == 'cluster-admin-binding'
    assert binding.cells[0] == 'ClusterRoleBinding'
    assert binding.cells[2] == ''
    assert binding.cells[3] == 'cluster-admin'
    assert binding.cells[5] == 'system:masters'
    detail_fields = dict(detail_security(CLUSTER_ROLE_BINDING, _cluster_role_binding(), now=NOW).fields)
    assert detail_fields['Reference Kind'] == 'ClusterRole'
    assert detail_fields['Subject Kind'] == 'Group'


def test_security_specs_and_keys() -> None:
    assert is_namespaced(SERVICE_ACCOUNT) is True
    assert is_namespaced(ROLE) is True
    assert is_namespaced(CLUSTER_ROLE) is False
    assert is_namespaced(ROLE_BINDING) is True
    assert is_namespaced(CLUSTER_ROLE_BINDING) is False
    assert split_security_key(SERVICE_ACCOUNT, 'default/builder') == ('default', 'builder')
    assert split_security_key(CLUSTER_ROLE, 'cluster-admin') == ('', 'cluster-admin')
    assert SECURITY_SPECS[SERVICE_ACCOUNT].api_version == 'v1'
    assert SECURITY_SPECS[SERVICE_ACCOUNT].resource == 'serviceaccounts'
    assert SECURITY_SPECS[ROLE].api_version == 'rbac.authorization.k8s.io/v1'
    assert SECURITY_SPECS[ROLE].resource == 'roles'
    assert SECURITY_SPECS[CLUSTER_ROLE].resource == 'clusterroles'
    assert SECURITY_SPECS[ROLE_BINDING].api_version == 'rbac.authorization.k8s.io/v1'
    assert SECURITY_SPECS[ROLE_BINDING].resource == 'rolebindings'
    assert SECURITY_SPECS[CLUSTER_ROLE_BINDING].resource == 'clusterrolebindings'
    assert list_kinds_for(ROLE) == (ROLE, CLUSTER_ROLE)
    assert list_kinds_for(ROLE_BINDING) == (ROLE_BINDING, CLUSTER_ROLE_BINDING)
    assert list_kinds_for(SERVICE_ACCOUNT) == (SERVICE_ACCOUNT,)


def test_unknown_security_kind_raises() -> None:
    with pytest.raises(ValueError, match='Unknown security kind'):
        summarize_security('NetworkPolicy', _role())


def test_apply_watch_event_on_service_account() -> None:
    first = summarize_security(SERVICE_ACCOUNT, _service_account(), now=NOW)
    items = apply_watch_event({}, 'ADDED', first)
    assert items[first.key].cells[2] == '1'
    updated_obj = _service_account()
    updated_obj.secrets = []
    updated = summarize_security(SERVICE_ACCOUNT, updated_obj, now=NOW)
    items = apply_watch_event(items, 'MODIFIED', updated)
    assert items[first.key].cells[2] == '0'
    items = apply_watch_event(items, 'DELETED', updated)
    assert first.key not in items
