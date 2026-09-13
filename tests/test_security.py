import asyncio
from datetime import datetime, timezone

from textual.widgets import DataTable, Static, TextArea

from helpers import open_kind
from roomlamp.app import RoomlampApp
from roomlamp.k8s.apply import AppliedObject
from roomlamp.k8s.context import ClusterInfo
from roomlamp.k8s.resources import ALL_NAMESPACES
from roomlamp.k8s.security import (
    CLUSTER_ROLE,
    CLUSTER_ROLE_BINDING,
    ROLE,
    ROLE_BINDING,
    SERVICE_ACCOUNT,
    SecurityDetail,
    SecuritySummary,
    is_namespaced,
    list_kinds_for,
)
from roomlamp.ui.screens.menu import MainMenuScreen
from roomlamp.ui.screens.security import SecurityDetailScreen, SecurityListScreen, sort_security
from roomlamp.ui.screens.yaml_view import YamlViewScreen

CREATED = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _summary(
    kind: str,
    name: str,
    namespace: str,
    cells: tuple[str, ...],
    sort_keys: tuple[object, ...],
) -> SecuritySummary:
    return SecuritySummary(
        kind=kind,
        name=name,
        namespace=namespace,
        created=CREATED,
        cells=cells,
        sort_keys=sort_keys,
    )


class FakeCluster:
    def __init__(self) -> None:
        self.security = {
            SERVICE_ACCOUNT: [
                _summary(
                    SERVICE_ACCOUNT,
                    'builder',
                    'default',
                    ('default', 'builder', '1', '1d'),
                    ('default', 'builder', 1, 1.0),
                ),
                _summary(
                    SERVICE_ACCOUNT,
                    'coredns',
                    'kube-system',
                    ('kube-system', 'coredns', '0', '2d'),
                    ('kube-system', 'coredns', 0, 2.0),
                ),
            ],
            ROLE: [
                _summary(
                    ROLE,
                    'pod-reader',
                    'default',
                    ('Role', 'pod-reader', 'default', '1d'),
                    ('Role', 'pod-reader', 'default', 1.0),
                ),
            ],
            CLUSTER_ROLE: [
                _summary(
                    CLUSTER_ROLE,
                    'cluster-admin',
                    '',
                    ('ClusterRole', 'cluster-admin', '', '8d'),
                    ('ClusterRole', 'cluster-admin', '', 8.0),
                ),
            ],
            ROLE_BINDING: [
                _summary(
                    ROLE_BINDING,
                    'pod-reader-binding',
                    'default',
                    ('RoleBinding', 'pod-reader-binding', 'default', 'pod-reader', 'jane', 'devs', 'builder', '1d'),
                    ('RoleBinding', 'pod-reader-binding', 'default', 'pod-reader', 'jane', 'devs', 'builder', 1.0),
                ),
            ],
            CLUSTER_ROLE_BINDING: [
                _summary(
                    CLUSTER_ROLE_BINDING,
                    'cluster-admin-binding',
                    '',
                    (
                        'ClusterRoleBinding',
                        'cluster-admin-binding',
                        '',
                        'cluster-admin',
                        '',
                        'system:masters',
                        '',
                        '8d',
                    ),
                    ('ClusterRoleBinding', 'cluster-admin-binding', '', 'cluster-admin', '', 'system:masters', '', 8.0),
                ),
            ],
        }
        self.labels: dict[tuple[str, str, str], tuple[tuple[str, str], ...]] = {}

    def list_namespaces(self) -> list[str]:
        return ['default', 'kube-system']

    def list_security(self, kind: str, namespace: str) -> list[SecuritySummary]:
        items: list[SecuritySummary] = []
        for listed in list_kinds_for(kind):
            for item in self.security.get(listed, []):
                if is_namespaced(listed) and namespace != ALL_NAMESPACES and item.namespace != namespace:
                    continue
                items.append(item)
        return items

    def get_security(self, kind: str, namespace: str, name: str) -> SecurityDetail:
        fields: tuple[tuple[str, str], ...]
        if kind == SERVICE_ACCOUNT:
            fields = (('Secrets', 'builder-token'), ('Automount Service Account Token', 'No'))
        elif kind in {ROLE, CLUSTER_ROLE}:
            fields = (('Rule Resources', 'pods'), ('Rule Verbs', 'get, list'))
        else:
            fields = (('Reference Kind', 'Role'), ('Reference Name', 'pod-reader'))
        return SecurityDetail(
            kind=kind,
            name=name,
            namespace=namespace,
            uid='uid-1',
            created='2026-01-02T00:00:00+00:00',
            labels=self.labels.get((kind, namespace, name), (('app', name),)),
            fields=fields,
        )

    def get_security_yaml(
        self,
        kind: str,
        namespace: str,
        name: str,
        hide_managed_fields: bool = True,
    ) -> str:
        ns = f'  namespace: {namespace}\n' if namespace else ''
        version = SECURITY_VERSIONS[kind]
        return f'apiVersion: {version}\nkind: {kind}\nmetadata:\n  name: {name}\n{ns}'

    def apply_yaml(self, text: str, dry_run: bool = False, default_namespace: str = 'default'):
        if not dry_run:
            self.labels[(SERVICE_ACCOUNT, 'default', 'builder')] = (('app', 'saved'),)
        return [AppliedObject(SERVICE_ACCOUNT, 'builder', 'default', dry_run)]


SECURITY_VERSIONS = {
    SERVICE_ACCOUNT: 'v1',
    ROLE: 'rbac.authorization.k8s.io/v1',
    CLUSTER_ROLE: 'rbac.authorization.k8s.io/v1',
    ROLE_BINDING: 'rbac.authorization.k8s.io/v1',
    CLUSTER_ROLE_BINDING: 'rbac.authorization.k8s.io/v1',
}


def _info() -> ClusterInfo:
    return ClusterInfo(
        kubeconfig='/tmp/kubeconfig',
        context_name='test-context',
        cluster_name='test-cluster',
        user_name='test-user',
        namespace='default',
        context_names=('test-context',),
    )


def enabled_actions(screen) -> set[str]:
    return {info.binding.action for info in screen.active_bindings.values() if info.enabled}


def test_service_account_list_filters_by_namespace() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SERVICE_ACCOUNT)
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            table = screen.query_one('#security', DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert 'builder' in row
            assert 'coredns' not in row
            assert 'pick_namespace' in enabled_actions(screen)
            screen.namespace = ALL_NAMESPACES
            screen._load_sync()
            assert table.row_count == 2

    asyncio.run(_run())


def test_service_account_detail_and_yaml() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SERVICE_ACCOUNT)
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            await screen._open_detail('default/builder')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, SecurityDetailScreen)
            text = str(detail.query_one('#security-detail', Static).content)
            assert 'ServiceAccount' in text
            assert 'builder' in text
            assert 'builder-token' in text
            await detail.action_show_yaml()
            await pilot.pause()
            assert isinstance(app.screen, YamlViewScreen)
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: ServiceAccount' in yaml_text
            assert 'name: builder' in yaml_text
            assert 'refresh' in enabled_actions(detail)

    asyncio.run(_run())


def test_role_and_role_binding_keep_namespace_picker() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, ROLE)
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            table = screen.query_one('#security', DataTable)
            kinds = [table.get_row_at(i)[0] for i in range(table.row_count)]
            names = [table.get_row_at(i)[1] for i in range(table.row_count)]
            assert 'Role' in kinds
            assert 'ClusterRole' in kinds
            assert 'pod-reader' in names
            assert 'cluster-admin' in names
            assert 'pick_namespace' in enabled_actions(screen)
            await open_kind(app, pilot, ROLE_BINDING)
            binding_screen = app.screen
            assert isinstance(binding_screen, SecurityListScreen)
            binding_table = binding_screen.query_one('#security', DataTable)
            binding_kinds = [binding_table.get_row_at(i)[0] for i in range(binding_table.row_count)]
            binding_names = [binding_table.get_row_at(i)[1] for i in range(binding_table.row_count)]
            assert 'RoleBinding' in binding_kinds
            assert 'ClusterRoleBinding' in binding_kinds
            assert 'pod-reader-binding' in binding_names
            assert 'cluster-admin-binding' in binding_names
            assert 'jane' in binding_table.get_row_at(binding_names.index('pod-reader-binding'))
            assert 'pick_namespace' in enabled_actions(binding_screen)

    asyncio.run(_run())


def test_role_detail_and_menu_key() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, ROLE)
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            await screen._open_detail('default/pod-reader')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, SecurityDetailScreen)
            text = str(detail.query_one('#security-detail', Static).content)
            assert 'Role' in text
            assert 'pods' in text
            await pilot.press('m')
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(_run())


def test_cluster_role_detail_from_role_list() -> None:
    app = RoomlampApp(_info(), cluster=FakeCluster(), enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, ROLE)
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            await screen._open_detail('cluster-admin')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, SecurityDetailScreen)
            assert detail.kind == CLUSTER_ROLE
            text = str(detail.query_one('#security-detail', Static).content)
            assert 'ClusterRole' in text
            assert 'cluster-admin' in text
            await detail.action_show_yaml()
            await pilot.pause()
            yaml_text = app.screen.query_one('#yaml-view', TextArea).text
            assert 'kind: ClusterRole' in yaml_text
            assert 'namespace:' not in yaml_text

    asyncio.run(_run())


def test_security_detail_refresh_and_yaml_apply_reloads() -> None:
    cluster = FakeCluster()
    app = RoomlampApp(_info(), cluster=cluster, enable_watch=False)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await open_kind(app, pilot, SERVICE_ACCOUNT)
            screen = app.screen
            assert isinstance(screen, SecurityListScreen)
            await screen._open_detail('default/builder')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, SecurityDetailScreen)
            text = str(detail.query_one('#security-detail', Static).content)
            assert 'app=builder' in text
            cluster.labels[(SERVICE_ACCOUNT, 'default', 'builder')] = (('app', 'refreshed'),)
            await detail.action_refresh()
            await pilot.pause()
            text = str(detail.query_one('#security-detail', Static).content)
            assert 'app=refreshed' in text
            await detail.action_show_yaml()
            await pilot.pause()
            yaml_screen = app.screen
            assert isinstance(yaml_screen, YamlViewScreen)
            yaml_screen.query_one('#yaml-view', TextArea).load_text(
                yaml_screen.query_one('#yaml-view', TextArea).text + '  labels:\n    app: saved\n'
            )
            await yaml_screen.action_apply()
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, SecurityDetailScreen)
            text = str(detail.query_one('#security-detail', Static).content)
            assert 'app=saved' in text

    asyncio.run(_run())


def test_sort_security_by_column() -> None:
    items = [
        _summary(
            SERVICE_ACCOUNT,
            'builder',
            'default',
            ('default', 'builder', '1', '1d'),
            ('default', 'builder', 1, 1.0),
        ),
        _summary(
            SERVICE_ACCOUNT,
            'api',
            'default',
            ('default', 'api', '0', '2d'),
            ('default', 'api', 0, 2.0),
        ),
    ]
    by_name = [item.name for item in sort_security(items, 1, True)]
    assert by_name == ['api', 'builder']
    by_secrets = [item.cells[2] for item in sort_security(items, 2, True)]
    assert by_secrets == ['0', '1']
