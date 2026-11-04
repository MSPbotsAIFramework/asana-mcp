"""Asana task tools.

Endpoints (Asana REST API v1.0):
  - GET  /tasks               search/list tasks, scoped by workspace/project/assignee/text/completed
  - GET  /tasks/{gid}          get one task
  - POST /tasks                create a task
  - PUT  /tasks/{gid}          partial update of a task
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from .. import errors
from ..api_client import AsanaClient, AsanaError
from ..observability import log_tool_call
from ..pagination import DEFAULT_LIMIT, dump, page_result, paginate_params

_SEARCH_FIELDS = "name,completed,assignee,due_on,permalink_url"
_DETAIL_FIELDS = "name,notes,completed,assignee,due_on,tags,permalink_url"
_CREATE_RESPONSE_FIELDS = "name,permalink_url"
_UPDATE_RESPONSE_FIELDS = "name,completed,assignee,due_on"

_MISSING_SCOPE = errors.envelope(
    "invalid_argument",
    "At least one of workspace_gid or project_gid is required",
)


def _summary(task: dict) -> dict:
    assignee = task.get("assignee") or {}
    return {
        "gid": task.get("gid"),
        "name": task.get("name"),
        "completed": task.get("completed"),
        "assignee_gid": assignee.get("gid"),
        "due_on": task.get("due_on"),
        "permalink_url": task.get("permalink_url"),
    }


def _detail(task: dict) -> dict:
    assignee = task.get("assignee") or {}
    tags = task.get("tags") or []
    return {
        "gid": task.get("gid"),
        "name": task.get("name"),
        "notes": task.get("notes"),
        "completed": task.get("completed"),
        "assignee_gid": assignee.get("gid"),
        "due_on": task.get("due_on"),
        "tags": [{"gid": t.get("gid"), "name": t.get("name")} for t in tags],
        "permalink_url": task.get("permalink_url"),
    }


def register(mcp: FastMCP, client_factory: Callable[[], AsanaClient | None]) -> None:
    @mcp.tool(annotations={"readOnlyHint": True})
    @log_tool_call("asana_search_tasks")
    async def asana_search_tasks(
        workspace_gid: str | None = None,
        project_gid: str | None = None,
        query: str | None = None,
        assignee_gid: str | None = None,
        completed: bool | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> str:
        """Search Asana tasks, scoped to a workspace or project and optionally
        filtered by free-text name, assignee, or completion state.

        Args:
            workspace_gid: Workspace to search in. Required if project_gid is not given.
            project_gid: Project to search in. Required if workspace_gid is not given.
            query: Free-text match against task names.
            assignee_gid: Only tasks assigned to this user gid.
            completed: Filter by completion state.
            limit: Max tasks to return (default 50, hard cap 200).
            cursor: Opaque pagination token from a previous call's response.
        """
        if not workspace_gid and not project_gid:
            return _MISSING_SCOPE
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")

        params = paginate_params(limit, cursor)
        params.update(
            {
                "workspace": workspace_gid,
                "project": project_gid,
                "text": query,
                "assignee": assignee_gid,
                "completed": completed,
                "opt_fields": _SEARCH_FIELDS,
            }
        )
        try:
            data, next_page = await client.get_page("/tasks", params=params)
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()

        tasks = [_summary(t) for t in data]
        return dump(page_result("tasks", tasks, next_page))

    @mcp.tool(annotations={"readOnlyHint": True})
    @log_tool_call("asana_get_task")
    async def asana_get_task(task_gid: str) -> str:
        """Get a single Asana task by id, including its notes and tags.

        Args:
            task_gid: The Asana task gid to fetch.
        """
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")
        try:
            data = await client.get(f"/tasks/{task_gid}", params={"opt_fields": _DETAIL_FIELDS})
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()
        return dump(_detail(data))

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
    )
    @log_tool_call("asana_create_task")
    async def asana_create_task(
        name: str,
        workspace_gid: str | None = None,
        project_gid: str | None = None,
        notes: str | None = None,
        assignee_gid: str | None = None,
        due_on: str | None = None,
    ) -> str:
        """Create a new Asana task. Calling this twice creates two tasks -- it is
        not idempotent, same as creating a task twice in the Asana UI.

        Args:
            name: Task title.
            workspace_gid: Workspace to create the task in. Required if project_gid is not given.
            project_gid: Project to create the task in. Required if workspace_gid is not given.
            notes: Task description.
            assignee_gid: User gid to assign the task to.
            due_on: Due date, YYYY-MM-DD.
        """
        if not workspace_gid and not project_gid:
            return _MISSING_SCOPE
        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")

        body: dict = {"name": name}
        if workspace_gid:
            body["workspace"] = workspace_gid
        if project_gid:
            body["projects"] = [project_gid]
        if notes is not None:
            body["notes"] = notes
        if assignee_gid is not None:
            body["assignee"] = assignee_gid
        if due_on is not None:
            body["due_on"] = due_on

        try:
            data = await client.post("/tasks", body, params={"opt_fields": _CREATE_RESPONSE_FIELDS})
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()
        return dump(
            {
                "gid": data.get("gid"),
                "name": data.get("name"),
                "permalink_url": data.get("permalink_url"),
            }
        )

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
    @log_tool_call("asana_update_task")
    async def asana_update_task(
        task_gid: str,
        name: str | None = None,
        notes: str | None = None,
        completed: bool | None = None,
        assignee_gid: str | None = None,
        due_on: str | None = None,
    ) -> str:
        """Update one or more fields on an existing Asana task. Only the fields
        you supply are changed; fields you omit are left as-is.

        Args:
            task_gid: The Asana task gid to update.
            name: New task title.
            notes: New task description.
            completed: Mark the task complete/incomplete.
            assignee_gid: New assignee user gid.
            due_on: New due date, YYYY-MM-DD.
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if notes is not None:
            body["notes"] = notes
        if completed is not None:
            body["completed"] = completed
        if assignee_gid is not None:
            body["assignee"] = assignee_gid
        if due_on is not None:
            body["due_on"] = due_on
        if not body:
            return errors.envelope(
                "invalid_argument", "At least one field besides task_gid must be supplied"
            )

        client = client_factory()
        if client is None:
            return errors.envelope("not_configured", "No Asana credentials in request context")
        try:
            data = await client.put(
                f"/tasks/{task_gid}", body, params={"opt_fields": _UPDATE_RESPONSE_FIELDS}
            )
        except AsanaError as e:
            return errors.from_status(e.status_code, str(e))
        finally:
            await client.aclose()

        assignee = data.get("assignee") or {}
        return dump(
            {
                "gid": data.get("gid"),
                "name": data.get("name"),
                "completed": data.get("completed"),
                "assignee_gid": assignee.get("gid"),
                "due_on": data.get("due_on"),
            }
        )
