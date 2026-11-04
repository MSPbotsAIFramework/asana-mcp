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
