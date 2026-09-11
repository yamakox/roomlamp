"""Format Kubernetes HTTP errors for the TUI without dumping request headers."""

from __future__ import annotations

import json
from typing import Any

import yaml

_JSON_TYPES = '{['


def api_error_message(exc: BaseException) -> str:
    """Return a user-facing HTTP error: Reason first, then JSON as YAML or the raw body.

    Non-HTTP exceptions keep ``str(exc)``. Headers and kubeconfig values are not included.
    """
    reason = getattr(exc, 'reason', None)
    raw_body = getattr(exc, 'body', None)
    status = getattr(exc, 'status', None)
    if raw_body is None and reason is None and status is None:
        return str(exc)
    body = _decode_body(raw_body)
    parsed = _json_payload(exc, body)
    if parsed is not None:
        rendered = _to_yaml(parsed)
    else:
        rendered = body
    reason_text = str(reason) if reason else ''
    if reason_text and rendered:
        return f'Reason: {reason_text}\n{rendered}'
    if reason_text:
        return f'Reason: {reason_text}'
    return rendered or str(exc)


def _decode_body(raw: object) -> str:
    if raw is None:
        return ''
    if isinstance(raw, bytes):
        return raw.decode('utf-8', errors='replace')
    return str(raw)


def _json_payload(exc: BaseException, body: str) -> Any | None:
    stripped = body.strip()
    if not stripped:
        return None
    if stripped[0] in _JSON_TYPES or _is_json_content_type(exc):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return None


def _is_json_content_type(exc: BaseException) -> bool:
    headers = getattr(exc, 'headers', None)
    get = getattr(headers, 'get', None)
    if not callable(get):
        return False
    content_type = get('Content-Type') or get('content-type') or ''
    return 'application/json' in str(content_type).lower()


def _to_yaml(data: Any) -> str:
    return yaml.safe_dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        indent=2,
        width=2**20,
    ).rstrip('\n')
