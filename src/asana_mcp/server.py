import contextvars

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import AsanaClient
from .config import ASANA_TOKEN_HEADER, Settings
from .observability import new_request_id, reset_request_id, set_request_id

# Per-request credential contextvar. GatewayCredsMiddleware sets this before
# the MCP handler runs. Python asyncio copies context per task, so concurrent
# requests carrying different tenants' tokens never see each other's value
# (AC10) -- this is the one place a bug here would mean a cross-tenant leak.
_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("asana_token", default=None)

INSTRUCTIONS = (
    "Asana task and project management. Find, create, and update tasks, browse "
    "projects and sections in a workspace, comment on tasks, and manage tags. "
    "Typical flow: asana_list_workspaces to get a workspace_gid, then "
    "asana_list_projects or asana_search_tasks scoped to it. Searching and "
    "creating a task both need a workspace_gid or a project_gid -- this mirrors "
    "a requirement of Asana's own API, not a limitation of this connector."
)


def get_client_from_context(settings: Settings) -> AsanaClient | None:
    """Resolve the active AsanaClient for the current request context.

    Returns None only if a tool is somehow invoked without the credential
    middleware having run first (e.g. a test calling the tool function
    directly) -- in normal operation GatewayCredsMiddleware already rejects
    the request with 401 before any tool code runs.
    """
    token = _token_var.get()
    if not token:
        return None
    return AsanaClient(token, settings.asana_api_root)


class GatewayCredsMiddleware:
    """Reads the Asana Personal Access Token from X-Asana-Access-Token on every
    /mcp request and stores it in a contextvar for the duration of that
    request. Missing header -> 401 before the request reaches the MCP handler,
    and therefore before any call to Asana (AC2).

    Also mints a per-request correlation id (observability.new_request_id())
    with the same set/reset-in-finally lifetime as the token, so every
    structured tool-call log line this request produces (observability.py)
    can be grouped by request_id without ever logging the token itself.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        # Header lookup is case-insensitive in Starlette.
        token = request.headers.get(ASANA_TOKEN_HEADER.lower())
        if not token:
            response = JSONResponse(
                {
                    "error": {
                        "code": "not_configured",
                        "message": f"Missing required header: {ASANA_TOKEN_HEADER}",
                        "retryable": False,
                    },
                    "required_headers": [ASANA_TOKEN_HEADER],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        token_ctx = _token_var.set(token)
        request_id_ctx = set_request_id(new_request_id())
        try:
            await self.app(scope, receive, send)
        finally:
            _token_var.reset(token_ctx)
            reset_request_id(request_id_ctx)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all tools."""
    # DNS-rebinding protection is disabled because this container runs behind
    # the MSPbots MCP gateway on an internal network and is never publicly
    # exposed; the proxy's forwarded Host would otherwise be rejected (421).
    mcp = FastMCP(
        name="asana-mcp",
        instructions=INSTRUCTIONS,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
        json_response=True,
    )

    def client_factory() -> AsanaClient | None:
        return get_client_from_context(settings)

    from .tools import comments, projects, tags, tasks, workspaces

    workspaces.register(mcp, client_factory)
    tasks.register(mcp, client_factory)
    projects.register(mcp, client_factory)
    comments.register(mcp, client_factory)
    tags.register(mcp, client_factory)

    return mcp
