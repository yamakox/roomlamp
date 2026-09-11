"""Click command-line entry for the TUI."""

from __future__ import annotations

import click

from roomlamp.app import RoomlampApp
from roomlamp.config import load_env
from roomlamp.k8s.cluster import open_cluster
from roomlamp.k8s.context import load_cluster_info


@click.command()
@click.option(
    '--kubeconfig',
    default=None,
    help='Path to kubeconfig (defaults to KUBECONFIG or ~/.kube/config).',
)
@click.option(
    '--context',
    default=None,
    help='kubeconfig context to use instead of current-context.',
)
def main(kubeconfig: str | None, context: str | None) -> None:
    """Start the Roomlamp terminal UI."""
    load_env()
    info = load_cluster_info(config_file=kubeconfig, context=context)
    RoomlampApp(info, cluster=open_cluster(info)).run()
