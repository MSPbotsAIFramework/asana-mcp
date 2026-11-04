"""Asana workspace tools.

Endpoints (Asana REST API v1.0):
  - GET /workspaces   list workspaces visible to the token
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from .. import errors
from ..api_client import AsanaClient, AsanaError
from ..pagination import DEFAULT_LIMIT, dump, page_result, paginate_params


def register(mcp: FastMCP, client_factory: Callable[[], AsanaClient | None]) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
    async def asana_list_workspaces(limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> str:
        """List the Asana workspaces visible to the connected account.

        Args:
            limit: Max workspaces to return (default 50, hard cap 200).
            cursor: Opaque pagination token from a previous call's response.
        """
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")
        try:
            data, next_page = await client.get_page(
                "/workspaces", params=paginate_params(limit, cursor)
            )
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()

        items = [{"gid": w.get("gid"), "name": w.get("name")} for w in data]
        return dump(page_result("workspaces", items, next_page))
