"""Structured per-tool-call logging.

Tech design "Non-functional / Observability" (`docs/tickets/PRD-21296.md:154`)
and the ticket's own "every action logged" ask commit to one structured log
line per tool call: tool name, duration, outcome (`ok` / error `code`), and
the tenant-opaque resource ids the call touched. SOP §6 ("Logging and
observability") additionally requires a request-id so one request's log
lines can be correlated. This module is the single place that does both, so
every tool in `tools/*.py` gets the same behavior from one decorator instead
of nine hand-written log calls.

Never logged: the credential (it is never a function argument -- tools read
it from the server's contextvar, see `server.get_client_from_context`), and
never the raw Asana response body (only the gids a tool's own arguments name,
and the error envelope's `code`, which this connector already redacts).
"""

import contextvars
import functools
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

logger = logging.getLogger("asana_mcp.tools")

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "asana_mcp_request_id", default=None
)

_GID_SUFFIX = "_gid"


def new_request_id() -> str:
    """A short correlation id for one inbound /mcp request. Not a security
    token -- it only needs to be unique enough to group this request's log
    lines, so 12 hex chars (48 bits) is plenty."""
    return uuid.uuid4().hex[:12]


def set_request_id(value: str | None) -> contextvars.Token:
    """Set the current request's id; returns the token `reset_request_id`
    needs. Called once per /mcp request by GatewayCredsMiddleware, alongside
    (and reset in the same `finally`, same discipline as) the credential
    contextvar -- see server.py."""
    return _request_id_var.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def _touched_resource_ids(kwargs: dict) -> list[str]:
    """Resource ids a tool call touched, read from its own keyword arguments.
    Every tool in this connector names its id parameters `*_gid` (task_gid,
    project_gid, workspace_gid, assignee_gid, ...), so this extraction is
    generic across all nine tools rather than duplicated per tool."""
    return [
        f"{key}={value}" for key, value in kwargs.items() if key.endswith(_GID_SUFFIX) and value
    ]


def _outcome(result: str) -> tuple[str, str | None]:
    """('ok', None) or ('error', <code>) -- parsed from the tool's own JSON
    string result (what errors.envelope()/pagination.dump() produce), never
    from the raw Asana response, which this function never sees."""
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        return "ok", None
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
        return "error", parsed["error"].get("code")
    return "ok", None


def _emit(tool_name: str, start: float, outcome: str, error_code: str | None, kwargs: dict) -> None:
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        json.dumps(
            {
                "event": "tool_call",
                "request_id": get_request_id(),
                "tool": tool_name,
                "duration_ms": duration_ms,
                "outcome": outcome,
                "error_code": error_code,
                "resource_ids": _touched_resource_ids(kwargs),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )


ToolFunc = Callable[..., Awaitable[str]]


def log_tool_call(tool_name: str) -> Callable[[ToolFunc], ToolFunc]:
    """Decorator for an `@mcp.tool()`-registered async function. It wraps,
    rather than replaces, the function: `functools.wraps` keeps `__wrapped__`
    pointing at the original, and FastMCP's schema builder reads the
    function's signature/annotations via `inspect.signature`/`get_type_hints`,
    both of which follow `__wrapped__` by default -- so the registered tool's
    parameter schema is unaffected by this wrapper. Apply it closest to the
    function (innermost), with `@mcp.tool(...)` on the outside:

        @mcp.tool(annotations={...})
        @log_tool_call("asana_get_task")
        async def asana_get_task(task_gid: str) -> str:
            ...
    """

    def decorator(fn: ToolFunc) -> ToolFunc:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> str:
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                _emit(tool_name, start, "error", "unhandled_exception", kwargs)
                raise
            outcome, error_code = _outcome(result)
            _emit(tool_name, start, outcome, error_code, kwargs)
            return result

        return wrapper

    return decorator
