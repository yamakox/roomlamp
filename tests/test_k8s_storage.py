from datetime import datetime, timezone

import pytest
from kubernetes.client.models import (
    V1CSIPersistentVolumeSource,
    V1ObjectMeta,
    V1ObjectReference,
    V1PersistentVolume,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimStatus,
    V1PersistentVolumeSpec,
    V1PersistentVolumeStatus,
    V1StorageClass,
    V1VolumeResourceRequirements,
)

from roomlamp.k8s.storage import (
    DEFAULT_STORAGE_CLASS_ANNOTATION,
    PV,
    PVC,
    STORAGE_CLASS,
    STORAGE_SPECS,
    detail_storage,
    is_namespaced,
    split_storage_key,
    summarize_storage,
)
from roomlamp.k8s.watch import apply_watch_event

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _meta(name: str, namespace: str | None = 'default', annotations: dict[str, str] | None = None) -> V1ObjectMeta:
    return V1ObjectMeta(
        name=name,
        namespace=namespace,
        uid='uid-1',
        creation_timestamp=CREATED,
        labels={'app': 'db'},
        annotations=annotations,
    )


def _pvc() -> V1PersistentVolumeClaim:
    return V1PersistentVolumeClaim(
        metadata=_meta('data'),
        spec=V1PersistentVolumeClaimSpec(
            access_modes=['ReadWriteOnce'],
            resources=V1VolumeResourceRequirements(requests={'storage': '8Gi'}),
            storage_class_name='standard',
            volume_mode='Filesystem',
            volume_name='pvc-abc',
        ),
        status=V1PersistentVolumeClaimStatus(
            access_modes=['ReadWriteOnce'],
            capacity={'storage': '8Gi'},
            phase='Bound',
        ),
    )


def _pv() -> V1PersistentVolume:
    return V1PersistentVolume(
        metadata=_meta('pv-disk', namespace=None),
        spec=V1PersistentVolumeSpec(
            capacity={'storage': '10Gi'},
            access_modes=['ReadWriteOnce'],
            persistent_volume_reclaim_policy='Retain',
            storage_class_name='standard',
            volume_mode='Filesystem',
            claim_ref=V1ObjectReference(kind=PVC, name='data', namespace='default'),
            csi=V1CSIPersistentVolumeSource(driver='csi.test', volume_handle='vol-1'),
        ),
        status=V1PersistentVolumeStatus(phase='Bound', reason='test', message='ok'),
    )


def _storage_class(*, default: bool = False, expand: bool | None = True) -> V1StorageClass:
    annotations = {DEFAULT_STORAGE_CLASS_ANNOTATION: 'true'} if default else None
    return V1StorageClass(
        metadata=_meta('standard', namespace=None, annotations=annotations),
        provisioner='csi.test',
        reclaim_policy='Delete',
        volume_binding_mode='WaitForFirstConsumer',
        allow_volume_expansion=expand,
        parameters={'type': 'ssd'},
        mount_options=['noatime'],
    )


def test_summarize_pvc_matches_headlamp_and_kubectl() -> None:
    summary = summarize_storage(PVC, _pvc(), now=NOW)
    assert summary.key == 'default/data'
    assert summary.cells == (
        'default',
        'data',
        'Bound',
        'pvc-abc',
        '8Gi',
        'ReadWriteOnce',
        'standard',
        '1d',
    )
    detail = detail_storage(PVC, _pvc(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Status'] == 'Bound'
    assert fields['Volume'] == 'pvc-abc'
    assert fields['Requested'] == '8Gi'
    assert fields['Capacity'] == '8Gi'
    assert fields['Access Modes'] == 'ReadWriteOnce'
    assert fields['Volume Mode'] == 'Filesystem'
    assert fields['Storage Class'] == 'standard'
    assert detail.labels == (('app', 'db'),)
    assert 'dummy-token' not in repr(detail)


def test_summarize_pv_is_cluster_scoped() -> None:
    summary = summarize_storage(PV, _pv(), now=NOW)
    assert summary.key == 'pv-disk'
    assert summary.namespace == ''
    assert summary.cells[0] == 'pv-disk'
    assert summary.cells[1] == '10Gi'
    assert summary.cells[2] == 'ReadWriteOnce'
    assert summary.cells[3] == 'Retain'
    assert summary.cells[4] == 'Bound'
    assert summary.cells[5] == 'default/data'
    assert summary.cells[6] == 'standard'
    detail = detail_storage(PV, _pv(), now=NOW)
    fields = dict(detail.fields)
    assert fields['Claim'] == 'default/data'
    assert fields['Source'] == 'csi'
    assert fields['Reason'] == 'test'
    assert fields['Message'] == 'ok'
    assert fields['Volume Mode'] == 'Filesystem'
    assert detail.namespace == ''


def test_summarize_storage_class_default_and_expansion() -> None:
    summary = summarize_storage(STORAGE_CLASS, _storage_class(default=True), now=NOW)
    assert summary.key == 'standard'
    assert summary.cells[1] == 'csi.test'
    assert summary.cells[2] == 'Yes'
    assert summary.cells[3] == 'Delete'
    assert summary.cells[4] == 'WaitForFirstConsumer'
    assert summary.cells[5] == 'Yes'
    detail = detail_storage(STORAGE_CLASS, _storage_class(default=True), now=NOW)
    fields = dict(detail.fields)
    assert fields['Default'] == 'Yes'
    assert fields['Allow Volume Expansion'] == 'Yes'
    assert fields['Binding Mode'] == 'WaitForFirstConsumer'
    assert fields['Parameters'] == 'type=ssd'
    assert fields['Mount Options'] == 'noatime'
    not_default = summarize_storage(STORAGE_CLASS, _storage_class(default=False, expand=None), now=NOW)
    assert not_default.cells[2] == ''
    assert not_default.cells[5] == ''
    hidden_expand = dict(detail_storage(STORAGE_CLASS, _storage_class(expand=None), now=NOW).fields)
    assert 'Allow Volume Expansion' not in hidden_expand
    assert hidden_expand['Default'] == 'No'


def test_storage_specs_and_keys() -> None:
    assert is_namespaced(PVC) is True
    assert is_namespaced(PV) is False
    assert is_namespaced(STORAGE_CLASS) is False
    assert split_storage_key(PVC, 'default/data') == ('default', 'data')
    assert split_storage_key(PV, 'pv-disk') == ('', 'pv-disk')
    assert STORAGE_SPECS[STORAGE_CLASS].api_version == 'storage.k8s.io/v1'
    assert STORAGE_SPECS[PVC].api_version == 'v1'
    assert STORAGE_SPECS[STORAGE_CLASS].resource == 'storageclasses'


def test_unknown_storage_kind_raises() -> None:
    with pytest.raises(ValueError, match='Unknown storage kind'):
        summarize_storage('VolumeAttributesClass', _pvc())


def test_apply_watch_event_on_pvc() -> None:
    first = summarize_storage(PVC, _pvc(), now=NOW)
    items = apply_watch_event({}, 'ADDED', first)
    assert items[first.key].cells[2] == 'Bound'
    updated_obj = _pvc()
    updated_obj.status.phase = 'Lost'
    updated = summarize_storage(PVC, updated_obj, now=NOW)
    items = apply_watch_event(items, 'MODIFIED', updated)
    assert items[first.key].cells[2] == 'Lost'
    items = apply_watch_event(items, 'DELETED', updated)
    assert first.key not in items
