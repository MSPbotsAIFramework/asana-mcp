"""Thin async wrapper around the Asana REST API v1.0.

One instance is created per tool call (see server.get_client_from_context) and
holds a single httpx.AsyncClient for the lifetime of that call, so a tool that
makes several Asana requests (e.g. asana_manage_task_tags) reuses one
connection pool (SOP §5) instead of opening a new client per request. Callers
must `await client.aclose()` when the tool call is done.
"""

import asyncio
import json

import httpx

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
# Single tool call (including retries) must stay under the SOP §5 120s hard
# limit; budget a margin under that so we never race the caller's own timeout.
TOTAL_BUDGET_SECONDS = 110.0
# Sentinel status for timeouts/network failures that never got an HTTP
# response -- maps to "upstream_error" in errors.from_status (not one of the
# real HTTP codes handled there).
NETWORK_ERROR_STATUS = 599


class AsanaError(Exception):
    """Raised for any Asana API failure. Callers catch this and map
    `status_code` to the error envelope vocabulary via errors.from_status."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Asana API error {status_code}: {message}")


class AsanaClient:
    def __init__(self, token: str, api_root: str):
        self._token = token
        self._base_url = api_root.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(TOTAL_BUDGET_SECONDS, connect=CONNECT_TIMEOUT, read=READ_TIMEOUT)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    async def _request_body(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        url = f"{self._base_url}{path}"
        loop = asyncio.get_event_loop()
        deadline = loop.time() + TOTAL_BUDGET_SECONDS
        attempt = 0
        resp: httpx.Response
        while True:
            try:
                resp = await self._client.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=_clean(params),
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                raise AsanaError(NETWORK_ERROR_STATUS, f"timeout calling Asana: {exc}") from exc
            except httpx.HTTPError as exc:
                raise AsanaError(
                    NETWORK_ERROR_STATUS, f"network error calling Asana: {exc}"
                ) from exc

            if resp.status_code not in RETRY_STATUS or attempt >= MAX_RETRIES:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            wait = min(
                _retry_after_seconds(resp)
                if _retry_after_seconds(resp) is not None
                else (2**attempt),
                remaining,
            )
            await asyncio.sleep(max(wait, 0))
            attempt += 1

        if resp.status_code >= 400:
            raise AsanaError(resp.status_code, _error_message(resp))
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def get(self, path: str, params: dict | None = None) -> dict:
        body = await self._request_body("GET", path, params=params)
        return body.get("data", {})

    async def get_page(self, path: str, params: dict | None = None) -> tuple[list, dict | None]:
        body = await self._request_body("GET", path, params=params)
        return body.get("data", []), body.get("next_page")

    async def post(self, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        json_body = {"data": data} if data is not None else None
        body = await self._request_body("POST", path, params=params, json_body=json_body)
        return body.get("data", {})

    async def put(self, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        json_body = {"data": data} if data is not None else None
        body = await self._request_body("PUT", path, params=params, json_body=json_body)
        return body.get("data", {})


def _clean(params: dict | None) -> dict | None:
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except Exception:
        return resp.text[:500]
    errors_list = body.get("errors") if isinstance(body, dict) else None
    if errors_list:
        return "; ".join(e.get("message", "") for e in errors_list if isinstance(e, dict))
    return json.dumps(body)[:500]
