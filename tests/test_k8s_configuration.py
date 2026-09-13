from datetime import datetime, timezone

import pytest
from kubernetes.client.models import V1ConfigMap, V1ObjectMeta, V1Secret

from roomlamp.k8s.configuration import (
    CONFIG_MAP,
    CONFIGURATION_SPECS,
    SECRET,
    detail_configuration,
    is_namespaced,
    split_configuration_key,
    summarize_configuration,
)
from roomlamp.k8s.watch import apply_watch_event

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)

SECRET_PLAIN = 'secret-value'
SECRET_B64 = 'c2VjcmV0LXZhbHVl'


def _meta(name: str, namespace: str | None = 'default') -> V1ObjectMeta:
    return V1ObjectMeta(
        name=name,
        namespace=namespace,
        uid='uid-1',
        creation_timestamp=CREATED,
        labels={'app': 'api'},
    )


def _config_map() -> V1ConfigMap:
    return V1ConfigMap(
        metadata=_meta('app-config'),
        data={'app': 'web', 'log': 'info'},
        binary_data={'logo': 'AQID'},
    )


def _secret() -> V1Secret:
    return V1Secret(
        metadata=_meta('db'),
        type='Opaque',
        data={'password': SECRET_B64, 'username': 'amFuZQ=='},
    )


def test_summarize_config_map_matches_headlamp_and_kubectl() -> None:
    summary = summarize_configuration(CONFIG_MAP, _config_map(), now=NOW)
    assert summary.key == 'default/app-config'
    assert summary.cells == ('default', 'app-config', '3', '1d')
    fields = dict(detail_configuration(CONFIG_MAP, _config_map(), now=NOW).fields)
    assert fields['Data app'] == 'web'
    assert fields['Data log'] == 'info'
    assert fields['Binary Data logo'] == 'AQID'
    assert detail_configuration(CONFIG_MAP, _config_map(), now=NOW).labels == (('app', 'api'),)


def test_config_map_empty_data_and_binary() -> None:
    obj = V1ConfigMap(metadata=_meta('empty'))
    summary = summarize_configuration(CONFIG_MAP, obj, now=NOW)
    assert summary.cells[2] == '0'
    fields = dict(detail_configuration(CONFIG_MAP, obj, now=NOW).fields)
    assert fields['Data'] == '(none)'
    assert fields['Binary Data'] == '(none)'


def test_summarize_secret_matches_headlamp_and_kubectl() -> None:
    summary = summarize_configuration(SECRET, _secret(), now=NOW)
    assert summary.key == 'default/db'
    assert summary.cells == ('default', 'db', 'Opaque', '2', '1d')
    fields = dict(detail_configuration(SECRET, _secret(), now=NOW).fields)
    assert fields['Type'] == 'Opaque'
    assert fields['Data password'] == '12 bytes'
    assert fields['Data username'] == '4 bytes'


def test_secret_detail_omits_data_values() -> None:
    detail = detail_configuration(SECRET, _secret(), now=NOW)
    blob = repr(detail)
    assert SECRET_B64 not in blob
    assert SECRET_PLAIN not in blob
    for _label, value in detail.fields:
        assert SECRET_B64 not in value
        assert SECRET_PLAIN not in value
    summary = summarize_configuration(SECRET, _secret(), now=NOW)
    assert SECRET_B64 not in repr(summary)
    assert SECRET_PLAIN not in ''.join(summary.cells)


def test_secret_empty_data() -> None:
    obj = V1Secret(metadata=_meta('empty'), type='kubernetes.io/service-account-token', data=None)
    summary = summarize_configuration(SECRET, obj, now=NOW)
    assert summary.cells[2] == 'kubernetes.io/service-account-token'
    assert summary.cells[3] == '0'
    fields = dict(detail_configuration(SECRET, obj, now=NOW).fields)
    assert fields['Data'] == '(none)'


def test_configuration_specs_and_keys() -> None:
    assert is_namespaced(CONFIG_MAP) is True
    assert is_namespaced(SECRET) is True
    assert split_configuration_key(CONFIG_MAP, 'default/app-config') == ('default', 'app-config')
    assert split_configuration_key(SECRET, 'kube-system/db') == ('kube-system', 'db')
    assert CONFIGURATION_SPECS[CONFIG_MAP].api_version == 'v1'
    assert CONFIGURATION_SPECS[CONFIG_MAP].resource == 'configmaps'
    assert CONFIGURATION_SPECS[SECRET].api_version == 'v1'
    assert CONFIGURATION_SPECS[SECRET].resource == 'secrets'


def test_unknown_configuration_kind_raises() -> None:
    with pytest.raises(ValueError, match='Unknown configuration kind'):
        summarize_configuration('HorizontalPodAutoscaler', _config_map())


def test_apply_watch_event_on_config_map() -> None:
    first = summarize_configuration(CONFIG_MAP, _config_map(), now=NOW)
    items = apply_watch_event({}, 'ADDED', first)
    assert items[first.key].cells[2] == '3'
    updated_obj = _config_map()
    updated_obj.data = {'app': 'web'}
    updated_obj.binary_data = None
    updated = summarize_configuration(CONFIG_MAP, updated_obj, now=NOW)
    items = apply_watch_event(items, 'MODIFIED', updated)
    assert items[first.key].cells[2] == '1'
    items = apply_watch_event(items, 'DELETED', updated)
    assert first.key not in items
