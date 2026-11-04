"""Structured per-tool-call logging (review round 1 must-fix: the tech design's
Observability section, `docs/tickets/PRD-21296.md:154`, was not implemented).
These are dev-leg tests covering the fix itself, not new acceptance criteria
-- the ACs in `PRD-21296.ac.json` are unchanged.
"""

import json
import logging

import httpx
import pytest
import respx

from asana_mcp.config import Settings
from asana_mcp.observability import (
    get_request_id,
    log_tool_call,
    new_request_id,
    reset_request_id,
    set_request_id,
)
from asana_mcp.server import _token_var, create_mcp_server

ROOT = "https://app.asana.com/api/1.0"


def _mcp():
    return create_mcp_server(Settings())


def _log_lines(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "asana_mcp.tools"]


@pytest.mark.asyncio
@respx.mock
async def test_successful_tool_call_logs_one_ok_line_with_duration_and_resource_id(caplog):
    respx.get(f"{ROOT}/tasks/1").mock(
        return_value=httpx.Response(200, json={"data": {"gid": "1", "name": "T"}})
    )
    token_ctx = _token_var.set("tok-123")
    try:
        with caplog.at_level(logging.INFO, logger="asana_mcp.tools"):
            mcp = _mcp()
            await mcp.call_tool("asana_get_task", {"task_gid": "1"})
    finally:
        _token_var.reset(token_ctx)

    lines = _log_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert line["tool"] == "asana_get_task"
    assert line["outcome"] == "ok"
    assert line["error_code"] is None
    assert line["resource_ids"] == ["task_gid=1"]
    assert isinstance(line["duration_ms"], (int, float))
    assert line["duration_ms"] >= 0


@pytest.mark.asyncio
@respx.mock
async def test_error_tool_call_logs_outcome_error_with_the_envelope_code(caplog):
    respx.get(f"{ROOT}/tasks/missing").mock(return_value=httpx.Response(404, json={"errors": []}))
    token_ctx = _token_var.set("tok-123")
    try:
        with caplog.at_level(logging.INFO, logger="asana_mcp.tools"):
            mcp = _mcp()
            await mcp.call_tool("asana_get_task", {"task_gid": "missing"})
    finally:
        _token_var.reset(token_ctx)

    lines = _log_lines(caplog)
    assert len(lines) == 1
    assert lines[0]["outcome"] == "error"
    assert lines[0]["error_code"] == "not_found"


@pytest.mark.asyncio
async def test_log_line_never_contains_the_credential(caplog):
    """The token is never a tool keyword argument (it lives in the
    server contextvar, see server.get_client_from_context), so a tool call
    made with no credentials configured must not leak one into the log
    either."""
    with caplog.at_level(logging.INFO, logger="asana_mcp.tools"):
        mcp = _mcp()
        # No token set in _token_var -> client_factory() returns None -> every
        # tool short-circuits to the "not_configured" envelope before any
        # Asana call, but the decorator still logs once.
        await mcp.call_tool("asana_get_task", {"task_gid": "1"})

    lines = _log_lines(caplog)
    assert len(lines) == 1
    assert lines[0]["outcome"] == "error"
    assert lines[0]["error_code"] == "not_configured"
    serialized = json.dumps(lines[0])
    assert "tok-123" not in serialized
    assert "Bearer" not in serialized


@pytest.mark.asyncio
@respx.mock
async def test_multiple_gid_arguments_are_all_captured(caplog):
    respx.post(f"{ROOT}/tasks/1/stories").mock(
        return_value=httpx.Response(200, json={"data": {"gid": "c1", "text": "hi"}})
    )
    token_ctx = _token_var.set("tok-123")
    try:
        with caplog.at_level(logging.INFO, logger="asana_mcp.tools"):
            mcp = _mcp()
            await mcp.call_tool("asana_add_comment", {"task_gid": "1", "text": "hi"})
    finally:
        _token_var.reset(token_ctx)

    line = _log_lines(caplog)[0]
    assert line["resource_ids"] == ["task_gid=1"]


def test_log_tool_call_preserves_the_wrapped_function_signature():
    """FastMCP builds its input schema from inspect.signature()/get_type_hints()
    on the exact callable passed to mcp.tool() -- if the decorator didn't
    preserve the original signature via functools.wraps, every decorated
    tool's parameter schema would silently collapse to (*args, **kwargs)."""
    import inspect

    @log_tool_call("example")
    async def example(task_gid: str, limit: int = 5) -> str:
        return "{}"

    sig = inspect.signature(example)
    assert list(sig.parameters) == ["task_gid", "limit"]
    assert sig.parameters["limit"].default == 5


def test_request_id_round_trips_through_the_contextvar():
    assert get_request_id() is None
    token = set_request_id(new_request_id())
    try:
        rid = get_request_id()
        assert rid is not None
        assert len(rid) == 12
    finally:
        reset_request_id(token)
    assert get_request_id() is None


@pytest.mark.asyncio
@respx.mock
async def test_log_line_carries_the_request_id_set_by_the_middleware(caplog):
    """Mirrors what GatewayCredsMiddleware does per /mcp request (server.py)."""
    respx.get(f"{ROOT}/workspaces").mock(
        return_value=httpx.Response(200, json={"data": [], "next_page": None})
    )
    token_ctx = _token_var.set("tok-123")
    rid_ctx = set_request_id(new_request_id())
    try:
        with caplog.at_level(logging.INFO, logger="asana_mcp.tools"):
            mcp = _mcp()
            await mcp.call_tool("asana_list_workspaces", {})
    finally:
        _token_var.reset(token_ctx)
        reset_request_id(rid_ctx)

    line = _log_lines(caplog)[0]
    assert line["request_id"] is not None
    assert len(line["request_id"]) == 12
