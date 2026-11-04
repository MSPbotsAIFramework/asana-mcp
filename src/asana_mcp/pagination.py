"""Shared list-tool conventions: limit/cursor in, has_more/cursor out, and the
single JSON serialization rule every tool result uses (SOP §2.5 -- compact,
not indent=2, ensure_ascii=False so non-ASCII isn't escaped into extra tokens).

Asana's own pagination token is called `offset`; the tool contract calls it
the opaque `cursor` (vendor-agnostic name) but passes the value through
unmodified -- see "Decisions made by DEV01" in the design doc.
"""

import json

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: int) -> int:
    if limit is None or limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def paginate_params(limit: int, cursor: str | None) -> dict:
    params: dict = {"limit": clamp_limit(limit)}
    if cursor:
        params["offset"] = cursor
    return params


def page_result(key: str, items: list, next_page: dict | None) -> dict:
    return {
        key: items,
        "has_more": next_page is not None,
        "cursor": next_page.get("offset") if next_page else None,
    }


def dump(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
