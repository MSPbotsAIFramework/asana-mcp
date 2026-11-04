"""Gateway middleware tests -- covers TC2 (missing header -> 401) and TC14
(request-level isolation under concurrency, AC10)."""

import asyncio

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from asana_mcp.config import ASANA_TOKEN_HEADER
from asana_mcp.observability import get_request_id
from asana_mcp.server import GatewayCredsMiddleware, _token_var


def _build_app() -> Starlette:
    async def echo(_):
        # Reaching here proves the middleware let the request through.
        return JSONResponse({"token": _token_var.get(), "request_id": get_request_id()})

    app = Starlette(routes=[Route("/mcp", echo, methods=["POST"])])
    return GatewayCredsMiddleware(app)


def test_missing_header_returns_401_before_reaching_handler():
    client = TestClient(_build_app())
    resp = client.post("/mcp", json={})
    assert resp.status_code == 401
    body = resp.json()
    assert body["required_headers"] == [ASANA_TOKEN_HEADER]
    assert body["error"]["code"] == "not_configured"
    assert ASANA_TOKEN_HEADER in body["error"]["message"]


def test_header_present_passes_through_and_resets_after():
    client = TestClient(_build_app())
    resp = client.post("/mcp", json={}, headers={ASANA_TOKEN_HEADER: "tok-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] == "tok-123"
    # A request id was minted for this request (observability.py) and is
    # distinguishable from the credential.
    assert body["request_id"] is not None
    assert body["request_id"] != "tok-123"
    # Both contextvars must not leak past the request.
    assert _token_var.get() is None
    assert get_request_id() is None


async def test_concurrent_requests_do_not_leak_tokens():
    """Simulates two concurrent /mcp requests (AC10): each asyncio Task gets its
    own copy of the context, mirroring how Starlette handles each inbound
    request in its own Task."""
    seen: dict[str, str | None] = {}

    async def handle(token: str, delay: float) -> None:
        token_ctx = _token_var.set(token)
        try:
            await asyncio.sleep(delay)
            seen[token] = _token_var.get()
        finally:
            _token_var.reset(token_ctx)

    await asyncio.gather(handle("tenant-a", 0.05), handle("tenant-b", 0.0))
    assert seen == {"tenant-a": "tenant-a", "tenant-b": "tenant-b"}
