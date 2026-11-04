# PRD-21296 · Code review

## Round 1 · 2026-11-04 · reviewed dev/PRD-21296 @ 12a2bcc (base 0438bb2)

Verdict: changes requested

### Findings

1. [must-fix] `src/asana_mcp/` (whole package, confirmed via `grep -rn "log\|logging\|logger" src` → no output) — no structured logging exists anywhere in the implementation, but the tech design's own "Non-functional / Observability" section (`docs/tickets/PRD-21296.md:154`) explicitly commits to it: "structured log line per tool call: tool name, duration, outcome (`ok` / error `code`), and tenant-opaque resource ids touched ... never the credential value, never the raw Asana response body." The same design ties this directly to the ticket's one-line ask (`docs/tickets/PRD-21296.md:30`): "'every action logged' means every tool call is logged ... via the server's structured logging." SOP §6 ("日志与可观测性") and Checklist §14 "日志与敏感信息" (`vendor-mcp-development-sop.md:278-284,482-487`) both require structured per-request logging (tool name, sanitized args, upstream path/status, duration, error code) with credentials/sensitive data excluded. None of that exists: no `logging` import, no log calls, in any of `server.py`, `api_client.py`, `errors.py`, or any `tools/*.py`. The Self-test section's "Deviations from the tech design (and why)" (`docs/tickets/PRD-21296.md:297-306`) lists one deviation (tag-name resolution, which isn't actually a deviation) and states "Everything else matches ... verbatim" — the missing Observability implementation is not disclosed anywhere as a known gap or WARN. This is a tech-design-required change that was not done (`legs/review.md` R3 "范围" row), and an undocumented gap that would otherwise need a WARN entry per `REVIEW.md` §3, which escalates to a BLOCKER when undocumented (`REVIEW.md` §3's closing rule). Fix: add structured logging (tool name, duration, outcome/error code, resource ids touched) at the point each tool call completes (e.g. a thin decorator/wrapper around each `register()`'d tool, or inline in each tool after the Asana call), emitting via the stdlib `logging` module as JSON/key=value, with no credential or raw-response-body fields — or, if logging is intentionally deferred, say so explicitly in the Self-test/Handoff sections as a disclosed WARN with a reason, and drop the "every action logged" claim from the Goals section's answer to the one-line ask.

### Independent verification performed

- `uv sync && uv run pytest -q` on `dev/PRD-21296 @ 12a2bcc`: 29 passed, 0 failed (matches the Self-test claim).
- `grep -rnP '[\x{4e00}-\x{9fff}]' src tests README.md Dockerfile pyproject.toml`: no output (clean, matches claim).
- `diff` of README.md's "MSPbots Connector" section against `vendor-mcp-development/reference/readme-connector-section.md`: identical.
- Tool count and hints: 9 tools across `tools/*.py`, each annotated `readOnlyHint`/`destructiveHint`/`idempotentHint` consistent with the design's Data & API contract; no tool is marked destructive (matches "No delete tools in v1").
- `.dockerignore` does not exclude `README.md` (the `pyproject.toml` `readme = "README.md"` + excluded-README failure seen on a prior ticket does not apply here).
- `git merge-base origin/main HEAD` = `0438bb2` = `origin/main` HEAD: base is current, work branch not yet merged.

No other must-fix found. No suggestions beyond the one logging gap above, which already covers the relevant scope.

### Fixes (round 1)

Only the one must-fix above was addressed; no other changes were made.

- **Added `src/asana_mcp/observability.py`**: a `log_tool_call(tool_name)` decorator plus a per-request-id `contextvar`. One structured JSON log line is emitted per completed tool call: `event`, `request_id`, `tool`, `duration_ms`, `outcome` (`ok` / `error`), `error_code` (the error envelope's `code`, parsed from the tool's own JSON result — never the raw Asana response), and `resource_ids` (every `*_gid` keyword argument the call received, e.g. `["task_gid=123"]`). Never logs the credential: the token is never a tool function argument (it lives only in `server._token_var`, read via `get_client_from_context`), so there is nothing for the decorator to see or log.
- **Applied `@log_tool_call("<tool name>")` to all 9 tools**, innermost to `@mcp.tool(...)`, across `tools/workspaces.py`, `tools/tasks.py` (4 tools), `tools/projects.py` (2 tools), `tools/comments.py`, `tools/tags.py`. `functools.wraps` on the wrapper keeps `__wrapped__` pointing at the original function, and FastMCP's schema builder (`inspect.signature`/`get_type_hints`, see `fastmcp/tools/function_tool.py:125`) follows `__wrapped__` by default — verified live against the running container's `tools/list` response: every tool's `inputSchema` still lists its real parameters (`task_gid`, `workspace_gid`, etc.), not a generic `*args`/`**kwargs` shape.
- **`server.py`**: `GatewayCredsMiddleware` now also mints a 12-hex-char request id (`observability.new_request_id()`) per inbound `/mcp` request and sets/resets it in the same `try`/`finally` block as the credential contextvar, so every tool-call log line from that request carries the same `request_id` and the id never leaks past the request (mirrors the existing AC10 discipline for the token).
- **`__main__.py`**: added `logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)` in `main()` — without a configured handler, `logger.info(...)` calls in `observability.py` would not reach stdout at all in the real running process (only in tests, which attach their own handler via `caplog`). `format="%(message)s"` is required because the message is already a complete JSON object; any other format would corrupt it with a prefix.
- **`README.md`**: added a `## Logging` section (after `## Tools`, before `## Local development`) documenting the log line's fields. Did not touch the frozen "MSPbots Connector" section (re-diffed against `vendor-mcp-development/reference/readme-connector-section.md` after this change — still identical).
- **Tests**: added `tests/test_observability.py` (7 new tests — successful call logs one `ok` line with `duration_ms`/`resource_ids`; an upstream-error call logs `outcome: "error"` with the envelope's `code`; a log line never contains the token string; multiple/absent `*_gid` arguments are captured correctly; the decorator preserves the wrapped function's `inspect.signature` — the regression this whole fix would be invisible without; the request-id contextvar round-trips and resets). Extended `tests/test_middleware.py`'s two existing tests to also assert a `request_id` is minted and reset. These are dev-leg tests for the fix itself, not new acceptance criteria — `PRD-21296.ac.json` is unchanged, per `legs/dev.md` S1 ("review rework": only the listed must-fix, no AC/test-case changes).
- **Re-ran the full gate suite on the fixed code** (`dev/PRD-21296`, synced with `main @ 0438bb2` — unchanged since round 1):
  - `uv run pytest -v`: **36 passed**, 0 failed (29 before the fix + 7 new observability tests).
  - `uv run ruff check .`: All checks passed.
  - `uv run ruff format --check .`: 23 files already formatted.
  - `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv src tests README.md Dockerfile pyproject.toml`: no output (clean) — the fix's own code/docstrings were written in English (one SOP §6 quote inside a draft docstring was caught by this grep and rewritten in English before commit).
  - `git diff -- . | grep -Ei '(token|secret|api[_-]?key|password|bearer)\s*[=:]' | grep -vi example`: no output (gitleaks not installed in this sandbox, same as round 1 — this is the same heuristic the round-1 Self-test used).
  - `docker build --platform linux/amd64`: builds clean, same 3 benign `UndefinedVar` warnings as round 1 (unset `$VERSION`/`$BUILD_DATE`/`$COMMIT_SHA` build args).
  - `docker run` + `GET /health`: `200 {"status":"ok"}`; `docker inspect --format '{{.Config.User}}'`: `asana` (non-root) — unchanged from round 1.
  - **Live protocol-level check of the fix itself** (not just unit tests): ran the built container, called `POST /mcp` `tools/call` for `asana_get_task` with a dummy (invalid) token — got the expected `unauthorized` error envelope back over the wire, and `docker logs` showed exactly one line: `{"event":"tool_call","request_id":"f221af89b372","tool":"asana_get_task","duration_ms":116.4,"outcome":"error","error_code":"unauthorized","resource_ids":["task_gid=999"]}` — confirms the feature works end-to-end in the real container, not only under mocked unit tests, and that the dummy token string itself does not appear anywhere in that line.
- No destructive writes, no schema change, no new dependency, no change to any tool's name/parameters/annotations/return shape — scope is exactly the one must-fix.

## Round 2 · 2026-11-04 · reviewed dev/PRD-21296 @ c080c02 (base 0438bb2)

Verdict: approved

### Fix verification (round 1 must-fix)

The round 1 must-fix (no structured per-tool-call logging) is resolved. Independently re-derived, not taken on the dev leg's word:

- `src/asana_mcp/observability.py` exists: `log_tool_call(tool_name)` decorator + `contextvars`-based request id (`new_request_id`/`set_request_id`/`reset_request_id`/`get_request_id`). One JSON line per completed call via `logging.getLogger("asana_mcp.tools").info(...)`: `event`, `request_id`, `tool`, `duration_ms`, `outcome`, `error_code`, `resource_ids`. Matches the design's Observability sentence verbatim (`docs/tickets/PRD-21296.md:154`) — tool name, duration, outcome/error code, tenant-opaque resource ids, never the credential or raw response body.
- `error_code` is read from the tool's own JSON result via `_outcome()`, which matches `src/asana_mcp/errors.py:envelope()`'s shape (`{"error": {"code", "message", "retryable"}}`) exactly — checked both files side by side, not assumed.
- `resource_ids` reads only `kwargs` keys ending in `_gid`. Confirmed this is not a gap: FastMCP (`fastmcp/tools/function_tool.py` in this worktree's own `.venv`) invokes the registered function by validating the inbound JSON object against its signature and calling it with that dict — never positionally — and `tests/test_observability.py` exercises the real path (`mcp.call_tool("asana_get_task", {"task_gid": "1"})`, not a direct function call), so the capture mechanism is exercised the same way production traffic hits it.
- `git diff 12a2bcc..c080c02 -- src/asana_mcp/tools/*.py | grep -c '@log_tool_call'` = 9, `grep -c '@mcp.tool' src/asana_mcp/tools/*.py` totals 9 — every tool decorated, none missed. Decorator order is `@mcp.tool(...)` outer / `@log_tool_call(...)` inner in every case (matches the module's own docstring example).
- Credential path re-checked: the token lives only in `server._token_var` (set by `GatewayCredsMiddleware`), is never passed as a tool argument, and `log_tool_call`'s wrapper only ever sees `*args, **kwargs` of the tool call itself — there is no code path for the decorator to observe or log it.
- Re-ran the gates myself on `dev/PRD-21296 @ c080c02` (`uv sync && uv run pytest -q`): **36 passed**, 0 failed — matches the Fixes section's claim (29 + 7 new). `uv run ruff check .`: all checks passed. `uv run ruff format --check .`: 23 files already formatted. Chinese-char scan (`src tests README.md Dockerfile pyproject.toml`): no output.
- README: diffed the "MSPbots Connector" section (lines 14–85) against `vendor-mcp-development/reference/readme-connector-section.md` again after the round 1 fix — still identical (only a trailing-blank-line artifact of section boundaries, no content change). The new `## Logging` section sits after `## Tools`, does not touch the frozen connector section.
- `tests/test_observability.py` (7 cases) and the extended `tests/test_middleware.py` assertions read as real regression coverage for the fix, not padding: they assert on `outcome`/`error_code`/`resource_ids` values, that the token string never appears in a log line, that `inspect.signature` survives the wrapper (the exact thing that would silently break FastMCP's schema if `functools.wraps` were dropped), and that the request-id contextvar resets after the request.
- `git merge-base --is-ancestor origin/main HEAD` on `c080c02`: true, and `origin/main` is still `0438bb2` (unchanged since round 1) — base has not moved, no re-sync needed before merging.

### New findings in this round's diff

None. The diff `12a2bcc..c080c02` (`README.md`, `src/asana_mcp/observability.py`, `src/asana_mcp/__main__.py`, `src/asana_mcp/server.py`, 5 files under `src/asana_mcp/tools/`, `tests/test_middleware.py`, `tests/test_observability.py`, plus this review doc) is scoped exactly to the round 1 must-fix, as the Fixes section claims. No new dependency, no schema, no tool signature/annotation change, no destructive behavior added.

Status: frozen @ c080c02
