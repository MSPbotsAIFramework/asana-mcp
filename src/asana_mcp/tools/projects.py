"""Asana project and section tools.

Endpoints (Asana REST API v1.0):
  - GET /projects                     list projects, filtered by workspace
  - GET /projects/{gid}/sections      list the sections (columns) in a project
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from .. import errors
from ..api_client import AsanaClient, AsanaError
from ..observability import log_tool_call
from ..pagination import DEFAULT_LIMIT, dump, page_result, paginate_params


def register(mcp: FastMCP, client_factory: Callable[[], AsanaClient | None]) -> None:
    @mcp.tool(annotations={"readOnlyHint": True})
    @log_tool_call("asana_list_projects")
    async def asana_list_projects(
        workspace_gid: str, limit: int = DEFAULT_LIMIT, cursor: str | None = None
    ) -> str:
        """List Asana projects in a workspace.

        Args:
            workspace_gid: Workspace to list projects from.
            limit: Max projects to return (default 50, hard cap 200).
            cursor: Opaque pagination token from a previous call's response.
        """
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")

        params = paginate_params(limit, cursor)
        params.update({"workspace": workspace_gid, "opt_fields": "name,archived"})
        try:
            data, next_page = await client.get_page("/projects", params=params)
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()

        projects = [
            {"gid": p.get("gid"), "name": p.get("name"), "archived": p.get("archived")}
            for p in data
        ]
        return dump(page_result("projects", projects, next_page))

    @mcp.tool(annotations={"readOnlyHint": True})
    @log_tool_call("asana_list_sections")
    async def asana_list_sections(
        project_gid: str, limit: int = DEFAULT_LIMIT, cursor: str | None = None
    ) -> str:
        """List the sections (columns) in an Asana project.

        Args:
            project_gid: Project to list sections from.
            limit: Max sections to return (default 50, hard cap 200).
            cursor: Opaque pagination token from a previous call's response.
        """
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")

        params = paginate_params(limit, cursor)
        try:
            data, next_page = await client.get_page(
                f"/projects/{project_gid}/sections", params=params
            )
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()

        sections = [{"gid": s.get("gid"), "name": s.get("name")} for s in data]
        return dump(page_result("sections", sections, next_page))
