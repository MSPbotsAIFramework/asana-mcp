"""errors.py vocabulary mapping -- supports TC3, TC12, TC13."""

import json

from asana_mcp import errors


def _decode(s: str) -> dict:
    return json.loads(s)


def test_from_status_maps_known_http_codes():
    assert _decode(errors.from_status(401, "bad token"))["error"] == {
        "code": "unauthorized",
        "message": "bad token",
        "retryable": False,
    }
    assert _decode(errors.from_status(404, "nope"))["error"]["code"] == "not_found"
    assert _decode(errors.from_status(422, "bad arg"))["error"]["code"] == "invalid_argument"
    assert _decode(errors.from_status(400, "bad arg"))["error"]["code"] == "invalid_argument"


def test_from_status_rate_limited_is_retryable():
    body = _decode(errors.from_status(429, "slow down"))["error"]
    assert body == {"code": "rate_limited", "message": "slow down", "retryable": True}


def test_from_status_unknown_code_is_upstream_error_and_retryable():
    body = _decode(errors.from_status(503, "boom"))["error"]
    assert body["code"] == "upstream_error"
    assert body["retryable"] is True


def test_envelope_is_compact_json_no_indent():
    s = errors.envelope("not_found", "x", False)
    assert "\n" not in s
    assert s == '{"error":{"code":"not_found","message":"x","retryable":false}}'
