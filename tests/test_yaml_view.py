import asyncio

from textual.widgets import TextArea

from roomlamp.app import RoomlampApp
from roomlamp.k8s.apply import AppliedObject
from roomlamp.k8s.context import ClusterInfo
from roomlamp.ui.screens.yaml_view import YamlViewScreen


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


class _Cluster:
    def apply_yaml(self, text: str, dry_run: bool = False, default_namespace: str = 'default'):
        self.calls.append((text, dry_run, default_namespace))
        if self.error is not None:
            raise self.error
        return [AppliedObject('Pod', 'web', default_namespace, dry_run)]

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, str]] = []
        self.error: Exception | None = None


def test_yaml_apply_sends_edited_text_and_closes() -> None:
    cluster = _Cluster()
    app = RoomlampApp(_info(), cluster=None, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            original = 'apiVersion: v1\nkind: Pod\nmetadata:\n  name: web\n'
            edited = original + '  labels:\n    app: web\n'
            called: list[bool] = []
            await app.push_screen(
                YamlViewScreen(
                    'Pod default/web',
                    original,
                    apply=lambda text, dry_run=False: cluster.apply_yaml(
                        text, dry_run=dry_run, default_namespace='default'
                    ),
                    on_applied=lambda: called.append(True),
                )
            )
            await pilot.pause()
            editor = app.screen.query_one('#yaml-view', TextArea)
            editor.load_text(edited)
            await app.screen.action_apply()
            await pilot.pause()
            assert cluster.calls == [(edited, False, 'default')]
            assert not isinstance(app.screen, YamlViewScreen)
            assert called == [True]

    asyncio.run(_run())


def test_yaml_dry_run_stays_open() -> None:
    cluster = _Cluster()
    app = RoomlampApp(_info(), cluster=None, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            original = 'apiVersion: v1\nkind: Pod\nmetadata:\n  name: web\n'
            called: list[bool] = []
            await app.push_screen(
                YamlViewScreen(
                    'Pod default/web',
                    original,
                    apply=lambda text, dry_run=False: cluster.apply_yaml(
                        text, dry_run=dry_run, default_namespace='default'
                    ),
                    on_applied=lambda: called.append(True),
                )
            )
            await pilot.pause()
            app.screen.query_one('#yaml-view', TextArea).load_text(original + '# edit\n')
            await app.screen.action_dry_run()
            await pilot.pause()
            assert cluster.calls[0][1] is True
            assert isinstance(app.screen, YamlViewScreen)
            assert called == []

    asyncio.run(_run())


def test_yaml_apply_error_stays_open() -> None:
    cluster = _Cluster()
    cluster.error = ValueError('Invalid YAML: mapping values are not allowed')
    app = RoomlampApp(_info(), cluster=None, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            original = 'apiVersion: v1\nkind: Pod\nmetadata:\n  name: web\n'
            await app.push_screen(
                YamlViewScreen(
                    'Pod default/web',
                    original,
                    apply=lambda text, dry_run=False: cluster.apply_yaml(text, dry_run=dry_run),
                )
            )
            await pilot.pause()
            app.screen.query_one('#yaml-view', TextArea).load_text(original + 'bad: [\n')
            await app.screen.action_apply()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)

    asyncio.run(_run())


def test_yaml_apply_skips_unchanged() -> None:
    cluster = _Cluster()
    app = RoomlampApp(_info(), cluster=None, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            original = 'apiVersion: v1\nkind: Pod\nmetadata:\n  name: web\n'
            await app.push_screen(
                YamlViewScreen(
                    'Pod default/web',
                    original,
                    apply=lambda text, dry_run=False: cluster.apply_yaml(text, dry_run=dry_run),
                )
            )
            await pilot.pause()
            await app.screen.action_apply()
            await pilot.pause()
            assert cluster.calls == []
            assert isinstance(app.screen, YamlViewScreen)

    asyncio.run(_run())
