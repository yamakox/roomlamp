from kubernetes.client.exceptions import ApiException

from roomlamp.k8s.apply import apply_error_message
from roomlamp.k8s.errors import api_error_message


def _forbidden() -> ApiException:
    exc = ApiException(status=403, reason='Forbidden')
    exc.body = (
        '{"kind":"Status","apiVersion":"v1","metadata":{},"status":"Failure",'
        '"message":"User \\"system:serviceaccount:default:roomlamp-readonly\\" '
        'cannot watch resource \\"deployments\\" in API group \\"apps\\" in the '
        'namespace \\"default\\"","reason":"Forbidden","details":{"group":"apps",'
        '"kind":"deployments"},"code":403}'
    )
    exc.headers = {
        'Content-Type': 'application/json',
        'Audit-Id': 'secret-audit-id',
    }
    return exc


def test_api_error_message_json_is_yaml_with_reason_first() -> None:
    text = api_error_message(_forbidden())
    assert text.startswith('Reason: Forbidden\n')
    assert 'kind: Status' in text
    assert 'details:\n  group: apps\n  kind: deployments' in text
    assert 'code: 403' in text
    assert 'HTTP response headers' not in text
    assert 'Audit-Id' not in text
    assert 'secret-audit-id' not in text
    assert 'dummy-token' not in text


def test_api_error_message_non_json_keeps_body() -> None:
    exc = ApiException(status=502, reason='Bad Gateway')
    exc.body = 'upstream unavailable'
    text = api_error_message(exc)
    assert text == 'Reason: Bad Gateway\nupstream unavailable'


def test_api_error_message_invalid_json_keeps_body() -> None:
    exc = ApiException(status=500, reason='Internal Server Error')
    exc.body = '{"not valid'
    exc.headers = {'Content-Type': 'application/json'}
    text = api_error_message(exc)
    assert text == 'Reason: Internal Server Error\n{"not valid'


def test_api_error_message_non_http_keeps_str() -> None:
    assert api_error_message(ValueError('bad yaml')) == 'bad yaml'
    assert 'dummy-token' not in api_error_message(ValueError('bad yaml'))


def test_apply_error_message_uses_same_http_format() -> None:
    exc = ApiException(status=409, reason='Conflict')
    exc.body = '{"message":"configmaps \\"web\\" already exists"}'
    text = apply_error_message(exc)
    assert text.startswith('Reason: Conflict\n')
    assert 'already exists' in text
    assert 'dummy-token' not in apply_error_message(ValueError('bad yaml'))
