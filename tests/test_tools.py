"""Tool-level tests against a mocked Asana API (respx, no network, no
credentials) -- covers TC1, TC4, TC6, TC8, TC9, TC10, TC11, plus tool-level
error-envelope checks for TC3/TC13."""

import json

import httpx
import pytest
import respx

from asana_mcp.config import Settings
from asana_mcp.server import _token_var, create_mcp_server

ROOT = "https://app.asana.com/api/1.0"

EXPECTED_TOOLS = {
    "asana_list_workspaces",
    "asana_search_tasks",
    "asana_get_task",
    "asana_create_task",
    "asana_update_task",
    "asana_add_comment",
    "asana_list_projects",
    "asana_list_sections",
    "asana_manage_task_tags",
}

READ_ONLY_TOOLS = {
    "asana_list_workspaces",
    "asana_search_tasks",
    "asana_get_task",
    "asana_list_projects",
    "asana_list_sections",
}


def _text(call_result) -> str:
    """Normalize FastMCP's call_tool return (content_list, meta_dict) into the
    tool's single text result."""
    content = call_result[0] if isinstance(call_result, tuple) else call_result
    return "".join(getattr(item, "text", str(item)) for item in content)


class _WithToken:
    """Sets the gateway contextvar for the duration of a `with` block, the way
    GatewayCredsMiddleware would for a real /mcp request carrying this token."""

    def __init__(self, token: str):
        self._token = token

    def __enter__(self):
        self._ctx = _token_var.set(self._token)
        return self

    def __exit__(self, *exc):
        _token_var.reset(self._ctx)


def _mcp():
    return create_mcp_server(Settings())


# ---------------------------------------------------------------------------
# TC1 (AC1): tools/list catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_has_all_nine_tools_with_hints():
    mcp = _mcp()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS

    by_name = {t.name: t for t in tools}
    for name in READ_ONLY_TOOLS:
        assert by_name[name].annotations.readOnlyHint is True, name
    for name in EXPECTED_TOOLS - READ_ONLY_TOOLS:
        assert by_name[name].annotations.readOnlyHint is False, name
    # No delete tools in v1 -- nothing is destructive.
    for name in EXPECTED_TOOLS:
        assert by_name[name].annotations.destructiveHint is not True, name


# ---------------------------------------------------------------------------
# TC2 covered in test_middleware.py (missing header never reaches a tool)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TC3 (AC9): upstream 401 -> structured "unauthorized", not an exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_task_maps_upstream_401_to_unauthorized_envelope():
    respx.get(f"{ROOT}/tasks/1").mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "Not Authorized"}]})
    )
    mcp = _mcp()
    with _WithToken("bad-token"):
        result = await mcp.call_tool("asana_get_task", {"task_gid": "1"})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# TC4 (AC4): search_tasks normalization + limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_search_tasks_normalizes_fields_and_respects_limit():
    route = respx.get(f"{ROOT}/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "gid": "1",
                        "name": "Renew SSL cert",
                        "completed": False,
                        "assignee": {"gid": "u1", "name": "Ada"},
                        "due_on": "2026-12-01",
                        "permalink_url": "https://app.asana.com/0/1/1",
                    }
                ],
                "next_page": None,
            },
        )
    )
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool(
            "asana_search_tasks", {"workspace_gid": "w1", "query": "SSL", "limit": 10}
        )
    body = json.loads(_text(result))
    assert body["tasks"] == [
        {
            "gid": "1",
            "name": "Renew SSL cert",
            "completed": False,
            "assignee_gid": "u1",
            "due_on": "2026-12-01",
            "permalink_url": "https://app.asana.com/0/1/1",
        }
    ]
    assert body["has_more"] is False
    req = route.calls.last.request
    assert req.url.params["limit"] == "10"
    assert req.url.params["workspace"] == "w1"
    assert req.url.params["text"] == "SSL"


@pytest.mark.asyncio
async def test_search_tasks_requires_workspace_or_project():
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_search_tasks", {"query": "x"})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "invalid_argument"


# ---------------------------------------------------------------------------
# TC6 (AC5): create_task request shape + response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_task_sends_documented_body_and_returns_result():
    route = respx.post(f"{ROOT}/tasks").mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "gid": "42",
                    "name": "Ship it",
                    "permalink_url": "https://app.asana.com/0/1/42",
                }
            },
        )
    )
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool(
            "asana_create_task",
            {
                "name": "Ship it",
                "project_gid": "p1",
                "notes": "details",
                "assignee_gid": "u1",
                "due_on": "2026-12-01",
            },
        )
    body = json.loads(_text(result))
    assert body == {"gid": "42", "name": "Ship it", "permalink_url": "https://app.asana.com/0/1/42"}

    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "data": {
            "name": "Ship it",
            "projects": ["p1"],
            "notes": "details",
            "assignee": "u1",
            "due_on": "2026-12-01",
        }
    }


@pytest.mark.asyncio
async def test_create_task_requires_workspace_or_project():
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_create_task", {"name": "x"})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "invalid_argument"


# ---------------------------------------------------------------------------
# TC8 (AC6): update_task partial update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_update_task_only_sends_supplied_field():
    route = respx.put(f"{ROOT}/tasks/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "gid": "1",
                    "name": "T",
                    "completed": False,
                    "assignee": {"gid": "u2"},
                    "due_on": None,
                }
            },
        )
    )
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_update_task", {"task_gid": "1", "assignee_gid": "u2"})
    body = json.loads(_text(result))
    assert body["assignee_gid"] == "u2"

    sent = json.loads(route.calls.last.request.content)
    assert sent == {"data": {"assignee": "u2"}}


@pytest.mark.asyncio
async def test_update_task_requires_at_least_one_field():
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_update_task", {"task_gid": "1"})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "invalid_argument"


# ---------------------------------------------------------------------------
# TC9 (AC7): add_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_add_comment_posts_to_stories_endpoint():
    route = respx.post(f"{ROOT}/tasks/1/stories").mock(
        return_value=httpx.Response(
            201, json={"data": {"gid": "c1", "text": "lgtm", "created_at": "2026-11-04T00:00:00Z"}}
        )
    )
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_add_comment", {"task_gid": "1", "text": "lgtm"})
    body = json.loads(_text(result))
    assert body == {"gid": "c1", "text": "lgtm", "created_at": "2026-11-04T00:00:00Z"}
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"data": {"text": "lgtm"}}


# ---------------------------------------------------------------------------
# TC10 (AC3): list_projects pagination round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_list_projects_pagination_round_trip():
    route = respx.get(f"{ROOT}/projects")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "data": [{"gid": "p1", "name": "Alpha", "archived": False}],
                "next_page": {"offset": "page2"},
            },
        ),
        httpx.Response(
            200,
            json={"data": [{"gid": "p2", "name": "Beta", "archived": False}], "next_page": None},
        ),
    ]
    mcp = _mcp()
    with _WithToken("tok-123"):
        first = await mcp.call_tool("asana_list_projects", {"workspace_gid": "w1"})
    first_body = json.loads(_text(first))
    assert first_body["has_more"] is True
    assert first_body["cursor"] == "page2"

    with _WithToken("tok-123"):
        second = await mcp.call_tool(
            "asana_list_projects", {"workspace_gid": "w1", "cursor": first_body["cursor"]}
        )
    second_body = json.loads(_text(second))
    assert second_body["projects"] == [{"gid": "p2", "name": "Beta", "archived": False}]
    assert second_body["has_more"] is False

    # Second call must have passed the first call's cursor through as `offset`.
    assert route.calls[1].request.url.params["offset"] == "page2"


# ---------------------------------------------------------------------------
# TC11 (AC8): manage_task_tags add/remove
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_manage_task_tags_calls_add_and_remove_by_gid():
    # Purely-numeric identifiers are treated as gids and used directly (no
    # /tags lookup call) -- see tools/tags.py's `.isdigit()` short-circuit.
    respx.get(f"{ROOT}/tasks/1").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"gid": "1", "workspace": {"gid": "w1"}}}),
            httpx.Response(
                200,
                json={
                    "data": {
                        "gid": "1",
                        "tags": [{"gid": "501", "name": "urgent"}],
                    }
                },
            ),
        ]
    )
    add_route = respx.post(f"{ROOT}/tasks/1/addTag").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    remove_route = respx.post(f"{ROOT}/tasks/1/removeTag").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )

    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool(
            "asana_manage_task_tags", {"task_gid": "1", "add": ["501"], "remove": ["502"]}
        )
    body = json.loads(_text(result))
    assert body == {"tags": [{"gid": "501", "name": "urgent"}]}

    assert add_route.called
    assert json.loads(add_route.calls.last.request.content) == {"data": {"tag": "501"}}
    assert remove_route.called
    assert json.loads(remove_route.calls.last.request.content) == {"data": {"tag": "502"}}


@pytest.mark.asyncio
@respx.mock
async def test_manage_task_tags_resolves_tag_name_and_creates_if_missing():
    respx.get(f"{ROOT}/tasks/1").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"gid": "1", "workspace": {"gid": "w1"}}}),
            httpx.Response(
                200, json={"data": {"gid": "1", "tags": [{"gid": "601", "name": "blocked"}]}}
            ),
        ]
    )
    respx.get(f"{ROOT}/tags").mock(
        return_value=httpx.Response(200, json={"data": [], "next_page": None})
    )
    create_route = respx.post(f"{ROOT}/tags").mock(
        return_value=httpx.Response(201, json={"data": {"gid": "601", "name": "blocked"}})
    )
    add_route = respx.post(f"{ROOT}/tasks/1/addTag").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )

    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool(
            "asana_manage_task_tags", {"task_gid": "1", "add": ["blocked"]}
        )
    body = json.loads(_text(result))
    assert body == {"tags": [{"gid": "601", "name": "blocked"}]}

    assert json.loads(create_route.calls.last.request.content) == {
        "data": {"name": "blocked", "workspace": "w1"}
    }
    assert json.loads(add_route.calls.last.request.content) == {"data": {"tag": "601"}}


@pytest.mark.asyncio
@respx.mock
async def test_manage_task_tags_remove_unknown_name_is_a_noop():
    respx.get(f"{ROOT}/tasks/1").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"gid": "1", "workspace": {"gid": "w1"}}}),
            httpx.Response(200, json={"data": {"gid": "1", "tags": []}}),
        ]
    )
    respx.get(f"{ROOT}/tags").mock(
        return_value=httpx.Response(200, json={"data": [], "next_page": None})
    )
    remove_route = respx.post(f"{ROOT}/tasks/1/removeTag")

    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool(
            "asana_manage_task_tags", {"task_gid": "1", "remove": ["not-a-tag"]}
        )
    body = json.loads(_text(result))
    assert body == {"tags": []}
    assert not remove_route.called


@pytest.mark.asyncio
async def test_manage_task_tags_requires_add_or_remove():
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_manage_task_tags", {"task_gid": "1"})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "invalid_argument"


# ---------------------------------------------------------------------------
# TC13 (AC9): upstream 404 -> structured "not_found"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_task_maps_upstream_404_to_not_found_envelope():
    respx.get(f"{ROOT}/tasks/missing").mock(
        return_value=httpx.Response(404, json={"errors": [{"message": "task not found"}]})
    )
    mcp = _mcp()
    with _WithToken("tok-123"):
        result = await mcp.call_tool("asana_get_task", {"task_gid": "missing"})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# Tool called with no credentials in context (middleware bypassed) -> not_configured,
# not an exception. Defends get_client_from_context's fallback path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_without_context_token_returns_not_configured():
    mcp = _mcp()
    result = await mcp.call_tool("asana_list_workspaces", {})
    body = json.loads(_text(result))
    assert body["error"]["code"] == "not_configured"
