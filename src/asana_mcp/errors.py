"""Structured error envelope for tool results.

Every tool returns a JSON string. On failure it returns
`{"error": {"code", "message", "retryable"}}` instead of raising, so the
calling agent can branch on `code` and decide whether to retry. `code` is
drawn from a fixed, small vocabulary -- never invented per-tool.
"""

import json

_RETRYABLE_BY_CODE = {
    "not_configured": False,
    "unauthorized": False,
    "not_found": False,
    "invalid_argument": False,
    "rate_limited": True,
    "upstream_error": True,
}


def envelope(code: str, message: str, retryable: bool | None = None) -> str:
    if retryable is None:
        retryable = _RETRYABLE_BY_CODE.get(code, False)
    body = {"error": {"code": code, "message": message, "retryable": retryable}}
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def from_status(status_code: int, message: str) -> str:
    """Map an upstream HTTP status (or the client's internal timeout/network
    sentinel, see api_client.NETWORK_ERROR_STATUS) to the error vocabulary."""
    if status_code in (401, 403):
        code = "unauthorized"
    elif status_code == 404:
        code = "not_found"
    elif status_code in (400, 422):
        code = "invalid_argument"
    elif status_code == 429:
        code = "rate_limited"
    else:
        code = "upstream_error"
    return envelope(code, message)
