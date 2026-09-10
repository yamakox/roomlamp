"""Sample kubeconfig files for tests. They contain dummy tokens only."""

from __future__ import annotations

from pathlib import Path

import pytest

SAMPLE_KUBECONFIG = """apiVersion: v1
kind: Config
clusters:
  - cluster:
      server: https://127.0.0.1:6443
      insecure-skip-tls-verify: true
    name: test-cluster
  - cluster:
      server: https://10.0.0.1:6443
      insecure-skip-tls-verify: true
    name: other-cluster
contexts:
  - context:
      cluster: test-cluster
      user: test-user
      namespace: roomlamp-test
    name: test-context
  - context:
      cluster: other-cluster
      user: other-user
    name: other-context
current-context: test-context
users:
  - name: test-user
    user:
      token: dummy-token-do-not-log
  - name: other-user
    user:
      token: other-dummy-token
"""


def write_kubeconfig(directory: Path, content: str = SAMPLE_KUBECONFIG) -> Path:
    path = directory / 'config'
    path.write_text(content, encoding='utf-8')
    return path


@pytest.fixture
def kubeconfig_path(tmp_path: Path) -> Path:
    return write_kubeconfig(tmp_path)
