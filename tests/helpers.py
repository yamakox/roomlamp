from roomlamp.k8s.workloads import POD_KIND
from roomlamp.ui.bindings import open_kind as push_kind


async def open_kind(app, pilot, kind: str = POD_KIND, *, namespace: str | None = None) -> None:
    """Push a kind list on top of Home (tests used to start on the Pod list)."""
    await pilot.pause()
    push_kind(app, kind, namespace or app.cluster_info.namespace or 'default')
    await pilot.pause()
