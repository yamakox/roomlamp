"""Resolve kubeconfig paths the same way kubectl does."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_KUBECONFIG = Path.home() / '.kube' / 'config'


def resolve_kubeconfig(config_file: str | None = None) -> str:
    """Return the kubeconfig location without reading credentials.

    Precedence matches kubectl: an explicit path, then ``KUBECONFIG``,
    then ``~/.kube/config``. ``KUBECONFIG`` may be a list of files
    separated by the platform path separator; that string is passed
    through unchanged so the official client can merge them.
    """
    if config_file:
        return str(Path(config_file).expanduser())
    env = os.environ.get('KUBECONFIG')
    if env:
        return env
    return str(DEFAULT_KUBECONFIG)
