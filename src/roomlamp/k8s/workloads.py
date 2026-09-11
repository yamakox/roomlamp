"""List and get common workload objects with the official client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from kubernetes.client import ApiClient, AppsV1Api, BatchV1Api

from roomlamp.k8s.resources import ALL_NAMESPACES, _format_time

POD_KIND = 'Pod'
DEPLOYMENT = 'Deployment'
REPLICASET = 'ReplicaSet'
STATEFULSET = 'StatefulSet'
DAEMONSET = 'DaemonSet'
JOB = 'Job'
CRONJOB = 'CronJob'

WORKLOAD_KINDS = (DEPLOYMENT, REPLICASET, STATEFULSET, DAEMONSET, JOB, CRONJOB)
PICKER_KINDS = (POD_KIND, *WORKLOAD_KINDS)


@dataclass(frozen=True)
class KindSpec:
    kind: str
    label: str
    group: str
    list_namespaced: str
    list_all: str
    read_namespaced: str
    columns: tuple[str, ...]


KIND_SPECS: dict[str, KindSpec] = {
    DEPLOYMENT: KindSpec(
        DEPLOYMENT,
        'Deployments',
        'apps',
        'list_namespaced_deployment',
        'list_deployment_for_all_namespaces',
        'read_namespaced_deployment',
        ('Namespace', 'Name', 'Ready', 'Up-to-date', 'Available', 'Age'),
    ),
    REPLICASET: KindSpec(
        REPLICASET,
        'ReplicaSets',
        'apps',
        'list_namespaced_replica_set',
        'list_replica_set_for_all_namespaces',
        'read_namespaced_replica_set',
        ('Namespace', 'Name', 'Desired', 'Current', 'Ready', 'Age'),
    ),
    STATEFULSET: KindSpec(
        STATEFULSET,
        'StatefulSets',
        'apps',
        'list_namespaced_stateful_set',
        'list_stateful_set_for_all_namespaces',
        'read_namespaced_stateful_set',
        ('Namespace', 'Name', 'Ready', 'Replicas', 'Age'),
    ),
    DAEMONSET: KindSpec(
        DAEMONSET,
        'DaemonSets',
        'apps',
        'list_namespaced_daemon_set',
        'list_daemon_set_for_all_namespaces',
        'read_namespaced_daemon_set',
        ('Namespace', 'Name', 'Desired', 'Current', 'Ready', 'Up-to-date', 'Available', 'Age'),
    ),
    JOB: KindSpec(
        JOB,
        'Jobs',
        'batch',
        'list_namespaced_job',
        'list_job_for_all_namespaces',
        'read_namespaced_job',
        ('Namespace', 'Name', 'Completions', 'Conditions', 'Duration', 'Age'),
    ),
    CRONJOB: KindSpec(
        CRONJOB,
        'CronJobs',
        'batch',
        'list_namespaced_cron_job',
        'list_cron_job_for_all_namespaces',
        'read_namespaced_cron_job',
        ('Namespace', 'Name', 'Schedule', 'Suspend', 'Active', 'Last Schedule', 'Age'),
    ),
}

KIND_LABELS = {
    POD_KIND: 'Pods',
    **{spec.kind: spec.label for spec in KIND_SPECS.values()},
}


@dataclass(frozen=True)
class WorkloadSummary:
    kind: str
    name: str
    namespace: str
    created: datetime | None
    cells: tuple[str, ...]
    sort_keys: tuple[object, ...]

    @property
    def key(self) -> str:
        return f'{self.namespace}/{self.name}'


@dataclass(frozen=True)
class WorkloadDetail:
    kind: str
    name: str
    namespace: str
    uid: str | None
    created: str | None
    labels: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]
    containers: tuple[str, ...]


class WorkloadReader(Protocol):
    def list_workloads(self, kind: str, namespace: str) -> list[WorkloadSummary]: ...

    def get_workload(self, kind: str, namespace: str, name: str) -> WorkloadDetail: ...


class ApiWorkloadReader:
    """Workload reads through a live ``ApiClient``."""

    def __init__(self, api_client: ApiClient) -> None:
        self._apps = AppsV1Api(api_client)
        self._batch = BatchV1Api(api_client)

    def list_workloads(self, kind: str, namespace: str) -> list[WorkloadSummary]:
        items = self._list_raw(kind, namespace)
        return [summarize_workload(kind, item) for item in items]

    def get_workload(self, kind: str, namespace: str, name: str) -> WorkloadDetail:
        spec = _require_kind(kind)
        api = self._api(spec)
        raw = getattr(api, spec.read_namespaced)(name, namespace)
        return detail_workload(kind, raw)

    def list_call(self, kind: str, namespace: str) -> tuple[object, tuple[object, ...]]:
        spec = _require_kind(kind)
        api = self._api(spec)
        if namespace == ALL_NAMESPACES:
            return getattr(api, spec.list_all), ()
        return getattr(api, spec.list_namespaced), (namespace,)

    def _list_raw(self, kind: str, namespace: str) -> list[object]:
        spec = _require_kind(kind)
        api = self._api(spec)
        if namespace == ALL_NAMESPACES:
            listed = getattr(api, spec.list_all)()
        else:
            listed = getattr(api, spec.list_namespaced)(namespace)
        return list(listed.items or [])

    def _api(self, spec: KindSpec) -> AppsV1Api | BatchV1Api:
        return self._apps if spec.group == 'apps' else self._batch


def summarize_workload(kind: str, obj: object, now: datetime | None = None) -> WorkloadSummary:
    spec = _require_kind(kind)
    summarizer = _SUMMARIZERS[kind]
    return summarizer(obj, spec, now)


def detail_workload(kind: str, obj: object, now: datetime | None = None) -> WorkloadDetail:
    _require_kind(kind)
    summary = summarize_workload(kind, obj, now)
    meta = getattr(obj, 'metadata', None)
    labels = ()
    if meta and getattr(meta, 'labels', None):
        labels = tuple(sorted(meta.labels.items()))
    created = None
    if meta and getattr(meta, 'creation_timestamp', None):
        created = _format_time(meta.creation_timestamp)
    return WorkloadDetail(
        kind=kind,
        name=summary.name,
        namespace=summary.namespace,
        uid=getattr(meta, 'uid', None) if meta else None,
        created=created,
        labels=labels,
        fields=_detail_fields(kind, obj, summary, now),
        containers=_container_lines(obj),
    )


def format_age(created: datetime | None, now: datetime | None = None) -> str:
    if created is None:
        return ''
    start = _aware(created)
    current = _aware(now or datetime.now(timezone.utc))
    seconds = max(0, int((current - start).total_seconds()))
    if seconds < 60:
        return f'{seconds}s'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m'
    hours = seconds // 3600
    if hours < 24:
        return f'{hours}h'
    return f'{hours // 24}d'


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _require_kind(kind: str) -> KindSpec:
    spec = KIND_SPECS.get(kind)
    if spec is None:
        raise ValueError(f'Unknown workload kind: {kind}')
    return spec


def _meta_name(obj: object) -> tuple[str, str, datetime | None]:
    meta = getattr(obj, 'metadata', None)
    name = getattr(meta, 'name', None) if meta else None
    namespace = getattr(meta, 'namespace', None) if meta else None
    created = getattr(meta, 'creation_timestamp', None) if meta else None
    return name or '', namespace or '', created


def _count(value: object | None) -> int:
    if value is None:
        return 0
    return int(value)


def _age_parts(created: datetime | None, now: datetime | None) -> tuple[str, float]:
    return format_age(created, now), created.timestamp() if created is not None else 0.0


def _make_summary(
    kind: str,
    name: str,
    namespace: str,
    created: datetime | None,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> WorkloadSummary:
    return WorkloadSummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=created,
        cells=cells,
        sort_keys=sort_keys,
    )


def _summarize_deployment(obj: object, spec: KindSpec, now: datetime | None) -> WorkloadSummary:
    name, namespace, created = _meta_name(obj)
    desired = _count(getattr(getattr(obj, 'spec', None), 'replicas', None))
    status = getattr(obj, 'status', None)
    ready = _count(getattr(status, 'ready_replicas', None))
    updated = _count(getattr(status, 'updated_replicas', None))
    available = _count(getattr(status, 'available_replicas', None))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, f'{ready}/{desired}', str(updated), str(available), age),
        (namespace, name, (ready, desired), updated, available, age_key),
    )


def _summarize_replicaset(obj: object, spec: KindSpec, now: datetime | None) -> WorkloadSummary:
    name, namespace, created = _meta_name(obj)
    desired = _count(getattr(getattr(obj, 'spec', None), 'replicas', None))
    status = getattr(obj, 'status', None)
    current = _count(getattr(status, 'replicas', None))
    ready = _count(getattr(status, 'ready_replicas', None))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, str(desired), str(current), str(ready), age),
        (namespace, name, desired, current, ready, age_key),
    )


def _summarize_statefulset(obj: object, spec: KindSpec, now: datetime | None) -> WorkloadSummary:
    name, namespace, created = _meta_name(obj)
    desired = _count(getattr(getattr(obj, 'spec', None), 'replicas', None))
    status = getattr(obj, 'status', None)
    ready = _count(getattr(status, 'ready_replicas', None))
    replicas = _count(getattr(status, 'replicas', None)) or desired
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, f'{ready}/{desired}', str(replicas), age),
        (namespace, name, (ready, desired), replicas, age_key),
    )


def _summarize_daemonset(obj: object, spec: KindSpec, now: datetime | None) -> WorkloadSummary:
    name, namespace, created = _meta_name(obj)
    status = getattr(obj, 'status', None)
    desired = _count(getattr(status, 'desired_number_scheduled', None))
    current = _count(getattr(status, 'current_number_scheduled', None))
    ready = _count(getattr(status, 'number_ready', None))
    updated = _count(getattr(status, 'updated_number_scheduled', None))
    available = _count(getattr(status, 'number_available', None))
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, str(desired), str(current), str(ready), str(updated), str(available), age),
        (namespace, name, desired, current, ready, updated, available, age_key),
    )


def _summarize_job(obj: object, spec: KindSpec, now: datetime | None) -> WorkloadSummary:
    name, namespace, created = _meta_name(obj)
    job_spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    completions = _count(getattr(job_spec, 'completions', None)) or 1
    succeeded = _count(getattr(status, 'succeeded', None))
    condition = _job_condition(status)
    start = getattr(status, 'start_time', None) if status else None
    completion = getattr(status, 'completion_time', None) if status else None
    duration = format_age(start, completion or now) if start is not None else '-'
    duration_key = 0.0
    if start is not None:
        finish = completion or now or datetime.now(timezone.utc)
        duration_key = (_aware(finish) - _aware(start)).total_seconds()
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, f'{succeeded}/{completions}', condition, duration, age),
        (namespace, name, (succeeded, completions), condition, duration_key, age_key),
    )


def _summarize_cronjob(obj: object, spec: KindSpec, now: datetime | None) -> WorkloadSummary:
    name, namespace, created = _meta_name(obj)
    cron_spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    schedule = str(getattr(cron_spec, 'schedule', None) or '')
    suspend = str(bool(getattr(cron_spec, 'suspend', None))).lower()
    active = len(getattr(status, 'active', None) or []) if status else 0
    last = getattr(status, 'last_schedule_time', None) if status else None
    last_text = format_age(last, now) if last is not None else ''
    last_key = last.timestamp() if last is not None else 0.0
    age, age_key = _age_parts(created, now)
    return _make_summary(
        spec.kind,
        name,
        namespace,
        created,
        (namespace, name, schedule, suspend, str(active), last_text, age),
        (namespace, name, schedule, suspend, active, last_key, age_key),
    )


_SUMMARIZERS = {
    DEPLOYMENT: _summarize_deployment,
    REPLICASET: _summarize_replicaset,
    STATEFULSET: _summarize_statefulset,
    DAEMONSET: _summarize_daemonset,
    JOB: _summarize_job,
    CRONJOB: _summarize_cronjob,
}


def _job_condition(status: object | None) -> str:
    conditions = getattr(status, 'conditions', None) if status else None
    if not conditions:
        return '-'
    for wanted in ('Failed', 'Complete', 'Suspended'):
        for item in conditions:
            if getattr(item, 'type', None) == wanted and str(getattr(item, 'status', '')).lower() == 'true':
                return wanted
    return '-'


def _match_labels(spec: object | None) -> str:
    selector = getattr(spec, 'selector', None)
    labels = getattr(selector, 'match_labels', None) if selector else None
    if not labels:
        return '(none)'
    return ', '.join(f'{key}={value}' for key, value in sorted(labels.items()))


def _pod_spec(obj: object) -> object | None:
    spec = getattr(obj, 'spec', None)
    if spec is None:
        return None
    template = getattr(spec, 'template', None)
    if template is not None:
        return getattr(template, 'spec', None)
    job_template = getattr(spec, 'job_template', None)
    job_spec = getattr(job_template, 'spec', None) if job_template else None
    template = getattr(job_spec, 'template', None) if job_spec else None
    return getattr(template, 'spec', None) if template else None


def _container_lines(obj: object) -> tuple[str, ...]:
    pod_spec = _pod_spec(obj)
    containers = getattr(pod_spec, 'containers', None) if pod_spec else None
    if not containers:
        return ()
    return tuple(f'{item.name}: image={item.image}' for item in containers)


def _detail_fields(
    kind: str,
    obj: object,
    summary: WorkloadSummary,
    _now: datetime | None,
) -> tuple[tuple[str, str], ...]:
    spec = getattr(obj, 'spec', None)
    status = getattr(obj, 'status', None)
    columns = KIND_SPECS[kind].columns
    fields: list[tuple[str, str]] = []
    skip = {'Namespace', 'Name', 'Age'}
    for index, label in enumerate(columns):
        if label in skip:
            continue
        fields.append((label, summary.cells[index]))
    if kind == DEPLOYMENT:
        fields.extend(
            (
                ('Replicas', str(_count(getattr(spec, 'replicas', None)))),
                ('Strategy', str(getattr(getattr(spec, 'strategy', None), 'type', None) or '(none)')),
                ('Selector', _match_labels(spec)),
            )
        )
        min_ready = getattr(spec, 'min_ready_seconds', None)
        if min_ready is not None:
            fields.append(('Min Ready Seconds', f'{min_ready}s'))
        deadline = getattr(spec, 'progress_deadline_seconds', None)
        if deadline is not None:
            fields.append(('Progress Deadline', f'{deadline}s'))
        history = getattr(spec, 'revision_history_limit', None)
        if history is not None:
            fields.append(('Revision History Limit', str(history)))
        fields.append(('Conditions', _all_conditions(status)))
    elif kind == REPLICASET:
        fields.append(('Selector', _match_labels(spec)))
    elif kind == STATEFULSET:
        fields.extend(
            (
                ('Service Name', str(getattr(spec, 'service_name', None) or '(none)')),
                ('Pod Management Policy', str(getattr(spec, 'pod_management_policy', None) or '(none)')),
                ('Update Strategy', str(getattr(getattr(spec, 'update_strategy', None), 'type', None) or '(none)')),
                ('Selector', _match_labels(spec)),
            )
        )
    elif kind == DAEMONSET:
        pod_spec = _pod_spec(obj)
        node_selector = getattr(pod_spec, 'node_selector', None) if pod_spec else None
        selector_text = (
            ', '.join(f'{key}={value}' for key, value in sorted(node_selector.items())) if node_selector else '(none)'
        )
        fields.append(('Node Selector', selector_text))
        fields.append(('Selector', _match_labels(spec)))
    elif kind == JOB:
        fields.extend(
            (
                ('Parallelism', str(getattr(spec, 'parallelism', None) if spec else '(none)')),
                ('Backoff Limit', str(getattr(spec, 'backoff_limit', None) if spec else '(none)')),
                (
                    'Pods Status',
                    ', '.join(
                        part
                        for part in (
                            f'Active: {_count(getattr(status, "active", None))}',
                            f'Ready: {_count(getattr(status, "ready", None))}',
                            f'Succeeded: {_count(getattr(status, "succeeded", None))}',
                            f'Failed: {_count(getattr(status, "failed", None))}',
                        )
                    ),
                ),
            )
        )
        start = getattr(status, 'start_time', None) if status else None
        completion = getattr(status, 'completion_time', None) if status else None
        if start is not None:
            fields.append(('Start Time', _format_time(start)))
        if completion is not None:
            fields.append(('Completion Time', _format_time(completion)))
        suspend = getattr(spec, 'suspend', None)
        if suspend is not None:
            fields.append(('Suspend', str(suspend)))
    elif kind == CRONJOB:
        concurrency = getattr(spec, 'concurrency_policy', None)
        if concurrency:
            fields.append(('Concurrency Policy', str(concurrency)))
    return tuple(fields)


def _all_conditions(status: object | None) -> str:
    conditions = getattr(status, 'conditions', None) if status else None
    if not conditions:
        return '(none)'
    parts = []
    for item in conditions:
        cond_type = getattr(item, 'type', None)
        cond_status = getattr(item, 'status', None)
        if cond_type:
            parts.append(f'{cond_type}={cond_status}')
    return ', '.join(parts) or '(none)'
