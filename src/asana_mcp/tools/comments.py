"""Asana comment tool.

Endpoint (Asana REST API v1.0):
  - POST /tasks/{gid}/stories   add a comment (story) to a task
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from .. import errors
from ..api_client import AsanaClient, AsanaError
from ..observability import log_tool_call
from ..pagination import dump


def register(mcp: FastMCP, client_factory: Callable[[], AsanaClient | None]) -> None:
    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
    )
    @log_tool_call("asana_add_comment")
    async def asana_add_comment(task_gid: str, text: str) -> str:
        """Add a comment to an Asana task. Calling this twice posts two comments
        -- it is not idempotent, same as posting a comment twice in the Asana UI.

        Args:
            task_gid: The Asana task gid to comment on.
            text: Comment text.
        """
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")
        try:
            data = await client.post(
                f"/tasks/{task_gid}/stories",
                {"text": text},
                params={"opt_fields": "text,created_at"},
            )
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()
        return dump(
            {"gid": data.get("gid"), "text": data.get("text"), "created_at": data.get("created_at")}
        )
