"""Asana tag tool.

Endpoints (Asana REST API v1.0):
  - GET  /tags                     look up an existing tag by name, scoped to a workspace
  - POST /tags                     create a tag (for an add that names a tag that doesn't exist yet)
  - POST /tasks/{gid}/addTag       add a tag to a task
  - POST /tasks/{gid}/removeTag    remove a tag from a task

`add`/`remove` accept either a raw tag gid or a tag name. A purely numeric
identifier is treated as a gid (Asana gids are numeric strings) and used
as-is, with no extra Asana call. A non-numeric identifier is resolved against
the task's workspace's existing tags by name; an unknown name passed to `add`
creates that tag (matching Asana's own addTag semantics), and an unknown name
passed to `remove` is a no-op (nothing to remove).
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from .. import errors
from ..api_client import AsanaClient, AsanaError
from ..pagination import dump


async def _resolve_tag_gid(
    client: AsanaClient, workspace_gid: str | None, identifier: str, *, create_if_missing: bool
) -> str | None:
    if identifier.isdigit():
        return identifier
    if not workspace_gid:
        return None
    tags, _ = await client.get_page(
        "/tags", params={"workspace": workspace_gid, "opt_fields": "name"}
    )
    for tag in tags:
        if tag.get("name") == identifier:
            return tag.get("gid")
    if not create_if_missing:
        return None
    created = await client.post("/tags", {"name": identifier, "workspace": workspace_gid})
    return created.get("gid")


def register(mcp: FastMCP, client_factory: Callable[[], AsanaClient | None]) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
    async def asana_manage_task_tags(
        task_gid: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> str:
        """Add or remove tags on an Asana task, by tag name or gid. Adding an
        already-present tag or removing one that isn't there is a no-op, not an
        error -- safe to retry.

        Args:
            task_gid: The Asana task gid to modify.
            add: Tag names or gids to add. An unknown name creates a new tag.
            remove: Tag names or gids to remove.
        """
        if not add and not remove:
            return errors.envelope("invalid_argument", "At least one of add or remove is required")

        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")
        try:
            task = await client.get(f"/tasks/{task_gid}", params={"opt_fields": "workspace"})
            workspace_gid = (task.get("workspace") or {}).get("gid")

            for identifier in add or []:
                tag_gid = await _resolve_tag_gid(
                    client, workspace_gid, identifier, create_if_missing=True
                )
                if tag_gid:
                    await client.post(f"/tasks/{task_gid}/addTag", {"tag": tag_gid})

            for identifier in remove or []:
                tag_gid = await _resolve_tag_gid(
                    client, workspace_gid, identifier, create_if_missing=False
                )
                if tag_gid:
                    await client.post(f"/tasks/{task_gid}/removeTag", {"tag": tag_gid})

            updated = await client.get(f"/tasks/{task_gid}", params={"opt_fields": "tags.name"})
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()

        tags = [{"gid": t.get("gid"), "name": t.get("name")} for t in (updated.get("tags") or [])]
        return dump({"tags": tags})
