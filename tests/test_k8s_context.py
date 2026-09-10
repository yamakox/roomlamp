from pathlib import Path

from roomlamp.k8s.client import resolve_kubeconfig
from roomlamp.k8s.context import load_cluster_info


def test_resolve_kubeconfig_uses_explicit_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv('KUBECONFIG', raising=False)
    path = tmp_path / 'custom.conf'
    assert resolve_kubeconfig(str(path)) == str(path)


def test_resolve_kubeconfig_uses_env(tmp_path: Path, monkeypatch) -> None:
    env_path = str(tmp_path / 'from-env')
    monkeypatch.setenv('KUBECONFIG', env_path)
    assert resolve_kubeconfig() == env_path


def test_load_cluster_info_reads_current_context(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path))
    assert info.ok
    assert info.error is None
    assert info.context_name == 'test-context'
    assert info.cluster_name == 'test-cluster'
    assert info.user_name == 'test-user'
    assert info.namespace == 'roomlamp-test'
    assert info.context_names == ('test-context', 'other-context')
    assert 'dummy-token' not in repr(info)


def test_load_cluster_info_selects_named_context(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path), context='other-context')
    assert info.ok
    assert info.context_name == 'other-context'
    assert info.cluster_name == 'other-cluster'
    assert info.namespace == 'default'


def test_load_cluster_info_unknown_context(kubeconfig_path: Path) -> None:
    info = load_cluster_info(config_file=str(kubeconfig_path), context='missing')
    assert not info.ok
    assert info.error is not None
    assert 'missing' in info.error
    assert info.context_names == ('test-context', 'other-context')


def test_load_cluster_info_missing_file(tmp_path: Path) -> None:
    path = tmp_path / 'does-not-exist'
    info = load_cluster_info(config_file=str(path))
    assert not info.ok
    assert info.error is not None
    assert info.context_name is None
