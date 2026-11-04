# asana-mcp

Asana MCP server for the MSPbots Agent platform. Asana is a task and project
management product; this service lets any MCP-compatible agent (Claude,
ChatGPT, Cursor, etc.) find, create, and update Asana tasks on behalf of a
tenant, using credentials supplied per request.

- Transport: MCP Streamable HTTP (`POST /mcp`), plus `GET /health`.
- Stack: Python 3.12, `uv`, FastMCP.
- Stateless: no session stickiness, no local persistence, no cross-request
  caching of tenant data or credentials.
- License: Apache-2.0. Copyright MSPbots.ai.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Meaning |
|---|---|---|---|
| `X-Asana-Access-Token` | Yes | password | Asana Personal Access Token. Create one at `https://app.asana.com/0/my-apps` → "Create new token". No OAuth app registration needed. |

Missing header returns HTTP 401 with a body naming the required header,
before any call reaches Asana.

## Tools

All tools return a JSON string. On failure, every tool returns the structured
error envelope `{"error": {"code", "message", "retryable"}}` instead of
raising -- `code` is one of `not_configured`, `unauthorized`, `not_found`,
`invalid_argument`, `rate_limited`, `upstream_error`.

| Tool | Read-only? | Description |
|---|---|---|
| `asana_list_workspaces` | yes | List the Asana workspaces visible to the connected account. |
| `asana_search_tasks` | yes | Search tasks, scoped to a workspace or project, optionally filtered by free-text name, assignee, or completion state. |
| `asana_get_task` | yes | Get a single task by id, including its notes and tags. |
| `asana_create_task` | no | Create a new task. Not idempotent -- calling twice creates two tasks. |
| `asana_update_task` | no | Update one or more fields on an existing task; only the fields supplied are changed. |
| `asana_add_comment` | no | Add a comment to a task. Not idempotent -- calling twice posts two comments. |
| `asana_list_projects` | yes | List projects in a workspace. |
| `asana_list_sections` | yes | List the sections (columns) in a project. |
| `asana_manage_task_tags` | no | Add or remove tags on a task, by name or gid. Idempotent -- re-adding/removing is a no-op. |

List tools take `limit` (default 50, hard cap 200) and an opaque `cursor`
for pagination; the response reports `has_more` and the next `cursor`.

There are no delete tools in this version (no business need was stated, and
there is no test account to rehearse recovery from an accidental delete).

## Logging

Every tool call emits one structured JSON log line to stdout: `tool` name,
`request_id` (one per inbound `/mcp` request), `duration_ms`, `outcome`
(`ok` or `error`), `error_code` (the error envelope's `code`, when any), and
`resource_ids` (the `*_gid` arguments the call touched, e.g.
`["task_gid=123"]`). The credential and the raw Asana response body are never
logged -- see `src/asana_mcp/observability.py`.

## Local development

```bash
uv sync
uv run pytest
MCP_HTTP_PORT=8080 uv run python -m asana_mcp
```

Then, with a real Asana Personal Access Token:

```bash
curl -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'X-Asana-Access-Token: <your token>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Container

```bash
docker build --platform linux/amd64 -t asana-mcp:dev .
docker run --rm -p 8080:8080 asana-mcp:dev
curl -fsS http://localhost:8080/health
```
