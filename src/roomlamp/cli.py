"""Click command-line entry for the TUI."""

from __future__ import annotations

import click

from roomlamp.app import RoomlampApp
from roomlamp.config import load_env
from roomlamp.k8s.cluster import open_cluster
from roomlamp.k8s.context import load_cluster_info

def _show_version():
    import sys
    from importlib.metadata import version, metadata
    package_name = metadata(__package__).get('Name')
    version_number = version(package_name)
    click.echo(f'{package_name} v{version_number}')
    sys.exit()

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
@click.option(
    '--version', 
    is_flag=True, 
    help='Show the version information and exit.'
)
def main(kubeconfig: str | None, context: str | None, version: bool) -> None:
    """Start the Roomlamp terminal UI."""
    if version:
        _show_version()
    load_env()
    info = load_cluster_info(config_file=kubeconfig, context=context)
    RoomlampApp(info, cluster=open_cluster(info)).run()
