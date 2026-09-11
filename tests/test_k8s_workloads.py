from datetime import datetime, timedelta, timezone

import pytest
from kubernetes.client.models import (
    V1Container,
    V1CronJob,
    V1CronJobSpec,
    V1CronJobStatus,
    V1DaemonSet,
    V1DaemonSetSpec,
    V1DaemonSetStatus,
    V1Deployment,
    V1DeploymentCondition,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1DeploymentStrategy,
    V1Job,
    V1JobCondition,
    V1JobSpec,
    V1JobStatus,
    V1JobTemplateSpec,
    V1LabelSelector,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ReplicaSet,
    V1ReplicaSetSpec,
    V1ReplicaSetStatus,
    V1StatefulSet,
    V1StatefulSetSpec,
    V1StatefulSetStatus,
    V1StatefulSetUpdateStrategy,
)

from roomlamp.k8s.watch import apply_watch_event
from roomlamp.k8s.workloads import (
    CRONJOB,
    DAEMONSET,
    DEPLOYMENT,
    JOB,
    REPLICASET,
    STATEFULSET,
    detail_workload,
    format_age,
    summarize_workload,
)

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _template() -> V1PodTemplateSpec:
    return V1PodTemplateSpec(
        metadata=V1ObjectMeta(labels={'app': 'web'}),
        spec=V1PodSpec(containers=[V1Container(name='app', image='nginx:1')]),
    )


def _selector() -> V1LabelSelector:
    return V1LabelSelector(match_labels={'app': 'web'})


def _meta(name: str, namespace: str = 'default') -> V1ObjectMeta:
    return V1ObjectMeta(
        name=name,
        namespace=namespace,
        uid='uid-1',
        creation_timestamp=CREATED,
        labels={'app': 'web'},
    )


def _deployment() -> V1Deployment:
    return V1Deployment(
        metadata=_meta('web'),
        spec=V1DeploymentSpec(
            replicas=3,
            selector=_selector(),
            template=_template(),
            strategy=V1DeploymentStrategy(type='RollingUpdate'),
            min_ready_seconds=5,
            progress_deadline_seconds=600,
            revision_history_limit=10,
        ),
        status=V1DeploymentStatus(
            replicas=3,
            ready_replicas=2,
            updated_replicas=3,
            available_replicas=2,
            conditions=[V1DeploymentCondition(type='Available', status='True')],
        ),
    )


def test_format_age_units() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert format_age(start, start + timedelta(seconds=9)) == '9s'
    assert format_age(start, start + timedelta(minutes=5)) == '5m'
    assert format_age(start, start + timedelta(hours=3)) == '3h'
    assert format_age(start, start + timedelta(days=2)) == '2d'
    assert format_age(None, start) == ''


def test_summarize_deployment_ready_like_kubectl() -> None:
    summary = summarize_workload(DEPLOYMENT, _deployment(), now=NOW)
    assert summary.key == 'default/web'
    assert summary.cells[2] == '2/3'
    assert summary.cells[3] == '3'
    assert summary.cells[4] == '2'
    assert summary.cells[5] == '1d'


def test_detail_deployment_includes_headlamp_extra_info() -> None:
    detail = detail_workload(DEPLOYMENT, _deployment(), now=NOW)
    fields = dict(detail.fields)
    assert detail.kind == DEPLOYMENT
    assert detail.labels == (('app', 'web'),)
    assert fields['Ready'] == '2/3'
    assert fields['Strategy'] == 'RollingUpdate'
    assert fields['Selector'] == 'app=web'
    assert fields['Min Ready Seconds'] == '5s'
    assert fields['Progress Deadline'] == '600s'
    assert fields['Revision History Limit'] == '10'
    assert any('app:' in line and 'nginx:1' in line for line in detail.containers)
    assert 'dummy-token' not in repr(detail)


def test_summarize_replicaset_counts() -> None:
    obj = V1ReplicaSet(
        metadata=_meta('web-abc'),
        spec=V1ReplicaSetSpec(replicas=3, selector=_selector(), template=_template()),
        status=V1ReplicaSetStatus(replicas=3, ready_replicas=2),
    )
    summary = summarize_workload(REPLICASET, obj, now=NOW)
    assert summary.cells[2:5] == ('3', '3', '2')


def test_summarize_statefulset_ready() -> None:
    obj = V1StatefulSet(
        metadata=_meta('db'),
        spec=V1StatefulSetSpec(
            replicas=2,
            selector=_selector(),
            service_name='db',
            template=_template(),
            pod_management_policy='OrderedReady',
            update_strategy=V1StatefulSetUpdateStrategy(type='RollingUpdate'),
        ),
        status=V1StatefulSetStatus(replicas=2, ready_replicas=1),
    )
    summary = summarize_workload(STATEFULSET, obj, now=NOW)
    assert summary.cells[2] == '1/2'
    detail = detail_workload(STATEFULSET, obj, now=NOW)
    fields = dict(detail.fields)
    assert fields['Service Name'] == 'db'
    assert fields['Pod Management Policy'] == 'OrderedReady'


def test_summarize_daemonset_counts() -> None:
    obj = V1DaemonSet(
        metadata=_meta('agent', 'kube-system'),
        spec=V1DaemonSetSpec(selector=_selector(), template=_template()),
        status=V1DaemonSetStatus(
            current_number_scheduled=2,
            desired_number_scheduled=2,
            number_ready=2,
            number_available=2,
            updated_number_scheduled=2,
            number_misscheduled=0,
        ),
    )
    summary = summarize_workload(DAEMONSET, obj, now=NOW)
    assert summary.namespace == 'kube-system'
    assert summary.cells[2:7] == ('2', '2', '2', '2', '2')


def test_summarize_job_completions_and_duration() -> None:
    done = CREATED + timedelta(minutes=4)
    obj = V1Job(
        metadata=_meta('batch'),
        spec=V1JobSpec(completions=1, parallelism=1, backoff_limit=6, template=_template()),
        status=V1JobStatus(
            succeeded=1,
            start_time=CREATED,
            completion_time=done,
            conditions=[V1JobCondition(type='Complete', status='True')],
        ),
    )
    summary = summarize_workload(JOB, obj, now=NOW)
    assert summary.cells[2] == '1/1'
    assert summary.cells[3] == 'Complete'
    assert summary.cells[4] == '4m'


def test_summarize_cronjob_schedule() -> None:
    obj = V1CronJob(
        metadata=_meta('tick'),
        spec=V1CronJobSpec(
            schedule='*/5 * * * *',
            suspend=False,
            concurrency_policy='Allow',
            job_template=V1JobTemplateSpec(spec=V1JobSpec(template=_template())),
        ),
        status=V1CronJobStatus(last_schedule_time=CREATED, active=[]),
    )
    summary = summarize_workload(CRONJOB, obj, now=NOW)
    assert summary.cells[2] == '*/5 * * * *'
    assert summary.cells[3] == 'false'
    assert summary.cells[4] == '0'
    assert summary.cells[5] == '1d'
    detail = detail_workload(CRONJOB, obj, now=NOW)
    assert dict(detail.fields)['Concurrency Policy'] == 'Allow'
    assert any('nginx:1' in line for line in detail.containers)


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match='Unknown workload kind'):
        summarize_workload('Service', _deployment())


def test_apply_watch_event_on_workload_summary() -> None:
    first = summarize_workload(DEPLOYMENT, _deployment(), now=NOW)
    items = apply_watch_event({}, 'ADDED', first)
    assert items[first.key].cells[2] == '2/3'
    updated_obj = _deployment()
    updated_obj.status.ready_replicas = 3
    updated = summarize_workload(DEPLOYMENT, updated_obj, now=NOW)
    items = apply_watch_event(items, 'MODIFIED', updated)
    assert items[first.key].cells[2] == '3/3'
    items = apply_watch_event(items, 'DELETED', updated)
    assert first.key not in items
