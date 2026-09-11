from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.apply import apply_error_message, apply_object, apply_yaml, parse_objects


class FakeResource:
    def __init__(self, *, namespaced: bool = True, create_error: ApiException | None = None) -> None:
        self.namespaced = namespaced
        self.create_error = create_error
        self.created: list[tuple[dict[str, object], str | None, object]] = []
        self.replaced: list[tuple[dict[str, object], str | None, str | None, object]] = []

    def create(self, body=None, namespace=None, **kwargs):
        if self.create_error is not None:
            raise self.create_error
        self.created.append((body, namespace, kwargs.get('dry_run')))
        return body

    def replace(self, body=None, name=None, namespace=None, **kwargs):
        self.replaced.append((body, name, namespace, kwargs.get('dry_run')))
        return body


def test_parse_objects_yaml_and_json() -> None:
    yaml_docs = parse_objects(
        'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: a\n---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: b\n'
    )
    assert [item['metadata']['name'] for item in yaml_docs] == ['a', 'b']
    json_docs = parse_objects('{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"c"}}')
    assert json_docs[0]['metadata']['name'] == 'c'
    json_list = parse_objects(
        '[{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"d"}},'
        '{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"e"}}]'
    )
    assert [item['metadata']['name'] for item in json_list] == ['d', 'e']


def test_parse_objects_skips_empty_documents() -> None:
    docs = parse_objects('---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: a\n---\n')
    assert len(docs) == 1
    assert docs[0]['metadata']['name'] == 'a'


def test_parse_objects_rejects_empty_and_non_mapping() -> None:
    try:
        parse_objects('   ')
    except ValueError as exc:
        assert 'empty' in str(exc)
    else:
        raise AssertionError('expected empty YAML to fail')
    try:
        parse_objects('- just a list item\n')
    except ValueError as exc:
        assert 'mapping' in str(exc)
    else:
        raise AssertionError('expected non-mapping YAML to fail')


def test_apply_object_posts_new_resource_and_strips_resource_version() -> None:
    resource = FakeResource()
    body = {
        'apiVersion': 'v1',
        'kind': 'ConfigMap',
        'metadata': {'name': 'web', 'namespace': 'default', 'resourceVersion': '10'},
        'data': {'k': 'v'},
    }
    applied = apply_object(body, resource)
    assert applied.label == 'ConfigMap default/web'
    assert applied.dry_run is False
    assert len(resource.created) == 1
    posted, namespace, dry_run = resource.created[0]
    assert namespace == 'default'
    assert dry_run is None
    assert posted['metadata']['name'] == 'web'
    assert 'resourceVersion' not in posted['metadata']
    assert body['metadata']['resourceVersion'] == '10'
    assert resource.replaced == []


def test_apply_object_puts_after_conflict_and_restores_resource_version() -> None:
    resource = FakeResource(create_error=ApiException(status=409, reason='Conflict'))
    body = {
        'apiVersion': 'v1',
        'kind': 'ConfigMap',
        'metadata': {'name': 'web', 'namespace': 'ns', 'resourceVersion': '7'},
    }
    apply_object(body, resource)
    assert resource.created == []
    assert len(resource.replaced) == 1
    replaced, name, namespace, dry_run = resource.replaced[0]
    assert name == 'web'
    assert namespace == 'ns'
    assert dry_run is None
    assert replaced['metadata']['resourceVersion'] == '7'


def test_apply_object_puts_after_forbidden_create() -> None:
    resource = FakeResource(create_error=ApiException(status=403, reason='Forbidden'))
    body = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'web'}}
    apply_object(body, resource, default_namespace='apps')
    replaced, name, namespace, _dry_run = resource.replaced[0]
    assert name == 'web'
    assert namespace == 'apps'
    assert replaced['metadata']['namespace'] == 'apps'


def test_apply_object_dry_run_passes_query() -> None:
    resource = FakeResource()
    body = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'web'}}
    applied = apply_object(body, resource, dry_run=True)
    assert applied.dry_run is True
    assert resource.created[0][2] == 'All'


def test_apply_object_cluster_scoped_omits_namespace() -> None:
    resource = FakeResource(namespaced=False)
    body = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'apps'}}
    applied = apply_object(body, resource)
    assert applied.namespace is None
    posted, namespace, _dry_run = resource.created[0]
    assert namespace is None
    assert 'namespace' not in posted['metadata']


def test_apply_object_other_errors_are_not_retried() -> None:
    resource = FakeResource(create_error=ApiException(status=500, reason='Boom'))
    body = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'web'}}
    try:
        apply_object(body, resource)
    except ApiException as exc:
        assert exc.status == 500
    else:
        raise AssertionError('expected 500 to propagate')
    assert resource.replaced == []


def test_apply_yaml_uses_getter_per_document() -> None:
    seen: list[tuple[str, str]] = []
    resource = FakeResource()

    def get_resource(api_version: str, kind: str) -> FakeResource:
        seen.append((api_version, kind))
        return resource

    applied = apply_yaml(
        'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: a\n---\n'
        'apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: b\n',
        get_resource,
        default_namespace='default',
    )
    assert seen == [('v1', 'ConfigMap'), ('apps/v1', 'Deployment')]
    assert [item.label for item in applied] == ['ConfigMap default/a', 'Deployment default/b']


def test_apply_error_message_prefers_status_message() -> None:
    exc = ApiException(status=409, reason='Conflict')
    exc.body = '{"message":"configmaps \\"web\\" already exists"}'
    assert 'already exists' in apply_error_message(exc)
    assert 'dummy-token' not in apply_error_message(ValueError('bad yaml'))
