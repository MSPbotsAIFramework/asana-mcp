"""AsanaClient tests against a mocked Asana API (respx, no network) -- covers
the retry/backoff and error-status plumbing behind TC12 and TC13."""

import httpx
import pytest
import respx

from asana_mcp.api_client import AsanaClient, AsanaError

ROOT = "https://app.asana.com/api/1.0"


def _client() -> AsanaClient:
    return AsanaClient(token="tok-123", api_root=ROOT)


@pytest.mark.asyncio
@respx.mock
async def test_get_attaches_bearer_token_and_unwraps_data():
    route = respx.get(f"{ROOT}/tasks/1").mock(
        return_value=httpx.Response(200, json={"data": {"gid": "1", "name": "T"}})
    )
    client = _client()
    data = await client.get("/tasks/1")
    await client.aclose()

    assert data == {"gid": "1", "name": "T"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok-123"


@pytest.mark.asyncio
@respx.mock
async def test_get_page_returns_data_and_next_page():
    respx.get(f"{ROOT}/workspaces").mock(
        return_value=httpx.Response(
            200, json={"data": [{"gid": "1", "name": "W"}], "next_page": {"offset": "abc"}}
        )
    )
    client = _client()
    data, next_page = await client.get_page("/workspaces")
    await client.aclose()

    assert data == [{"gid": "1", "name": "W"}]
    assert next_page == {"offset": "abc"}


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_asana_error_with_status_and_message():
    respx.get(f"{ROOT}/tasks/missing").mock(
        return_value=httpx.Response(404, json={"errors": [{"message": "task not found"}]})
    )
    client = _client()
    with pytest.raises(AsanaError) as exc:
        await client.get("/tasks/missing")
    await client.aclose()

    assert exc.value.status_code == 404
    assert "task not found" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_429_retries_honoring_retry_after_then_succeeds():
    route = respx.get(f"{ROOT}/workspaces").mock(
        side_effect=[
            httpx.Response(
                429, headers={"Retry-After": "0"}, json={"errors": [{"message": "slow down"}]}
            ),
            httpx.Response(200, json={"data": [{"gid": "1", "name": "W"}], "next_page": None}),
        ]
    )
    client = _client()
    data, next_page = await client.get_page("/workspaces")
    await client.aclose()

    assert route.call_count == 2
    assert data == [{"gid": "1", "name": "W"}]
    assert next_page is None


@pytest.mark.asyncio
@respx.mock
async def test_429_exhausted_retries_raises_with_429_status():
    route = respx.get(f"{ROOT}/workspaces").mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "0"}, json={"errors": [{"message": "slow down"}]}
        )
    )
    client = _client()
    with pytest.raises(AsanaError) as exc:
        await client.get_page("/workspaces")
    await client.aclose()

    assert exc.value.status_code == 429
    # 1 initial attempt + MAX_RETRIES retries
    assert route.call_count == 4


@pytest.mark.asyncio
@respx.mock
async def test_post_wraps_body_in_data_envelope():
    route = respx.post(f"{ROOT}/tasks").mock(
        return_value=httpx.Response(201, json={"data": {"gid": "9", "name": "New"}})
    )
    client = _client()
    data = await client.post("/tasks", {"name": "New", "workspace": "1"})
    await client.aclose()

    assert data == {"gid": "9", "name": "New"}
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {
        "data": {"name": "New", "workspace": "1"}
    }
