import asyncio

from roomlamp.app import RoomlampApp
from roomlamp.k8s.context import ClusterInfo
from roomlamp.ui.screens.home import HomeScreen
from textual.widgets import Static


def test_home_screen_shows_current_context() -> None:
    info = ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='roomlamp-test',
        context_names=('test-context', 'other-context'),
    )
    app = RoomlampApp(info)

    async def _run() -> None:
        async with app.run_test():
            identity = app.query_one('#home-identity', Static)
            text = str(identity.content)
            assert isinstance(app.screen, HomeScreen)
            assert 'test-context' in text
            assert 'test-cluster' in text
            assert 'test-user' in text
            assert '/tmp/kubeconfig' in text
            assert 'dummy-token' not in text

    asyncio.run(_run())


def test_home_screen_shows_load_error() -> None:
    info = ClusterInfo(
        kubeconfig='/tmp/missing',
        context_name=None,
        cluster_name=None,
        user_name=None,
        namespace=None,
        context_names=(),
        error='No such file',
    )
    app = RoomlampApp(info)

    async def _run() -> None:
        async with app.run_test():
            identity = app.query_one('#home-identity', Static)
            text = str(identity.content)
            assert 'Could not load kubeconfig' in text
            assert 'No such file' in text

    asyncio.run(_run())
