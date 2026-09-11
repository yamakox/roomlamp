"""Resolve kubeconfig paths and build an official API client."""

from __future__ import annotations

import os
from pathlib import Path

from kubernetes.client import ApiClient, Configuration
from kubernetes.config.kube_config import load_kube_config

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


def build_api_client(config_file: str, context: str | None = None) -> ApiClient:
    """Build a client from kubeconfig without rewriting the file."""
    configuration = Configuration()
    load_kube_config(
        config_file=config_file,
        context=context,
        client_configuration=configuration,
        persist_config=False,
    )
    return ApiClient(configuration)
