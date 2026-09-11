from datetime import datetime, timezone

from kubernetes.client.models import (
    V1Container,
    V1ContainerState,
    V1ContainerStateRunning,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
    V1PodStatus,
)

from roomlamp.k8s.resources import default_container_name, detail_pod, pod_container_names, pod_node_os, summarize_pod
from roomlamp.k8s.watch import apply_watch_event


def _pod(
    *,
    name: str = 'web',
    namespace: str = 'default',
    phase: str = 'Running',
    ready: bool = True,
    restarts: int = 2,
    node: str = 'node-a',
) -> V1Pod:
    return V1Pod(
        metadata=V1ObjectMeta(
            name=name,
            namespace=namespace,
            uid='uid-1',
            creation_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
            labels={'app': 'web'},
        ),
        spec=V1PodSpec(
            containers=[V1Container(name='app', image='nginx:1')],
            init_containers=[V1Container(name='init', image='busybox:1')],
            node_name=node,
        ),
        status=V1PodStatus(
            phase=phase,
            pod_ip='10.1.0.5',
            container_statuses=[
                V1ContainerStatus(
                    name='app',
                    ready=ready,
                    restart_count=restarts,
                    image='nginx:1',
                    image_id='sha256:abc',
                    state=V1ContainerState(running=V1ContainerStateRunning()),
                )
            ],
        ),
    )


def test_summarize_pod_ready_and_restarts() -> None:
    summary = summarize_pod(_pod())
    assert summary.name == 'web'
    assert summary.namespace == 'default'
    assert summary.phase == 'Running'
    assert summary.ready == '1/1'
    assert summary.restarts == 2
    assert summary.node == 'node-a'
    assert summary.key == 'default/web'


def test_detail_pod_includes_labels_and_containers() -> None:
    detail = detail_pod(_pod())
    assert detail.uid == 'uid-1'
    assert detail.pod_ip == '10.1.0.5'
    assert detail.labels == (('app', 'web'),)
    assert any('app:' in line and 'nginx:1' in line for line in detail.containers)
    assert 'dummy-token' not in repr(detail)


def test_pod_container_names_include_init_and_prefer_running() -> None:
    pod = _pod()
    assert pod_container_names(pod) == ('app', 'init')
    assert default_container_name(pod) == 'app'

    waiting = _pod()
    waiting.status.container_statuses[0].state = V1ContainerState(
        waiting=V1ContainerStateWaiting(reason='PodInitializing')
    )
    waiting.status.init_container_statuses = [
        V1ContainerStatus(
            name='init',
            ready=False,
            restart_count=0,
            image='busybox:1',
            image_id='sha256:init',
            state=V1ContainerState(running=V1ContainerStateRunning()),
        )
    ]
    assert default_container_name(waiting) == 'init'


def test_pod_node_os_from_node_selector() -> None:
    pod = _pod()
    assert pod_node_os(pod) is None
    assert detail_pod(pod).node_os is None
    pod.spec.node_selector = {'kubernetes.io/os': 'linux'}
    assert pod_node_os(pod) == 'linux'
    assert detail_pod(pod).node_os == 'linux'
    pod.spec.node_selector = {'beta.kubernetes.io/os': 'windows'}
    assert pod_node_os(pod) == 'windows'


def test_apply_watch_event_add_modify_delete() -> None:
    first = summarize_pod(_pod())
    pods = apply_watch_event({}, 'ADDED', first)
    assert pods[first.key].phase == 'Running'

    updated = summarize_pod(_pod(phase='Failed', restarts=3))
    pods = apply_watch_event(pods, 'MODIFIED', updated)
    assert pods[first.key].phase == 'Failed'
    assert pods[first.key].restarts == 3

    pods = apply_watch_event(pods, 'DELETED', updated)
    assert first.key not in pods
