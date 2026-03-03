# Phase 5 — MCP Integration (Co-Hosted)

> Status: **In Progress** (Phases A–F done, G remaining)

## Overview

Wrap the existing tool service in a Model Context Protocol (MCP) server, co-hosted
on the same FastAPI/ASGI application at `/mcp`. Existing REST tool endpoints are
deprecated (still functional) — the MCP surface becomes the primary agent integration.

### Architecture (target)

```
Foundry Agent (gpt-4.1-mini)
    ↕ MCP protocol (Streamable HTTP)
Container App (:8000/mcp)   ←  FastMCP co-hosted on existing app
    ↕ app.db module
Azure SQL
```

- Foundry Agent Service talks directly to the MCP server — no client-side tool loop
  needed for tool execution.
- Agent registered with `McpTool(server_label, server_url)` instead of `FunctionTool`.
- `chat_agent.py` shifts to MCP approval-flow pattern (approve/reject tool calls).
- Existing REST endpoints (`/tools/*`) remain as deprecated fallback + admin API.

### Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Hosting | Co-host on existing FastAPI via Starlette Mount at `/mcp` | Single container, shared DB layer, zero duplication |
| Existing endpoints | Deprecate, keep functional | Backward compat during transition; remove in Phase 6 |
| MCP transport | Streamable HTTP (`stateless_http=True, json_response=True`) | Scalable, no session state; recommended for production |
| Approval mode | `require_approval="always"` on agent registration | Preserves human-in-the-loop governance |
| DB layer | Shared `app.db` — MCP tools import directly | No code duplication |
| Auth | No MCP-level auth initially (Foundry handles identity) | Add `token_verifier` as hardening step later |

## Phase A — MCP Server Module

- [x] Add `mcp[cli]>=1.9` to `requirements.txt` and `pyproject.toml`
- [x] Create `app/mcp_server.py` with `FastMCP` instance
- [x] Implement 4 `@mcp.tool()` decorated functions:
  - `query_ticket_context(ticket_id)` → wraps `db.get_ticket_context()`
  - `request_approval(ticket_id, proposed_action, rationale, correlation_id)` → wraps `db.create_approval_request()`
  - `execute_remediation(ticket_id, action, approved_by, approval_token, correlation_id)` → wraps `db.execute_remediation()`
  - `post_teams_summary(ticket_id, summary, action_taken, approved_by, correlation_id)` → webhook/log
- [x] Structured JSON logging with `correlation_id` propagation
- [x] Mount `FastMCP.streamable_http_app()` on main FastAPI app at `/mcp`
- [x] Wire lifespan to manage both FastAPI + MCP session manager

## Phase B — Deprecate REST Tool Endpoints

- [x] Add deprecation headers (`Deprecation`, `Sunset`) to all `/tools/*` responses
- [x] Add `deprecated=True` to FastAPI route decorators
- [x] Log deprecation warnings on each call
- [x] Update OpenAPI spec: mark operations as `deprecated: true`

## Phase C — Agent Registration Swap

- [x] Update `scripts/create_agent.py`:
  - Replaced `FunctionTool` with `MCPTool` from `azure.ai.projects.tools.mcp` (high-level)
  - `MCPTool(server_label="iq-tools", server_url=url+"/mcp", require_approval="always")`
  - `FunctionTool` path kept behind `--legacy` flag
- [ ] Update `foundry/agent.yaml` tool definitions section to document MCP

## Phase D — Client Loop (MCP Approval Flow)

- [x] Update `scripts/chat_agent.py`:
  - Replaced `requires_action` HTTP dispatch with `SubmitToolApprovalAction` handling
  - Auto-approve `query_ticket_context`, `request_approval`, `post_teams_summary`
  - Prompt user for `execute_remediation` approval (human-in-the-loop)
  - Kept legacy dispatch path behind `--legacy` flag
  - Correlation ID injection via `mcp_tool.update_headers()`
- [x] Update `evals/run_evals.py` with MCP approval pattern (auto-approve all for evals)

## Phase E — Infrastructure & Docker

- [x] Update `services/api-tools/Dockerfile` — no change needed (same app, new dep)
- [x] Update `docker-compose.yml` — no new service needed (co-hosted)
- [x] Verify MCP endpoint reachable at `http://localhost:8000/mcp` (confirmed via route list)
- [ ] Update Bicep outputs to document MCP URL path (optional)

## Phase F — Testing & CI

- [x] Add `tests/test_mcp_server.py`:
  - MCP tool listing returns 4 tools
  - `query_ticket_context` roundtrip returns expected shape
  - `request_approval` roundtrip creates pending record
  - `execute_remediation` without approval returns error
  - `post_teams_summary` roundtrip returns logged=true
  - Error/fallback behavior (13 tests total)
- [ ] Update CI: MCP smoke test (curl `/mcp` endpoint)
- [ ] Update smoke-test script for MCP health probe

## Phase G — Documentation & Cleanup

- [ ] Update `docs/architecture.md` with MCP architecture diagram
- [ ] Update `foundry/agent.yaml` tool definitions commentary
- [ ] Update lab docs to reference MCP flow
- [ ] Update `CONVENTIONS.md` file routing table for MCP

## Complexity Estimate

| Phase | Effort | Risk |
|---|---|---|
| A: MCP Server Module | ~4h | Low — thin wrappers over `db.py` |
| B: Deprecate REST | ~0.5h | Low — decorators + headers |
| C: Agent Registration | ~1h | Low — type swap |
| D: Client Loop | ~2h | Medium — new approval pattern |
| E: Infra/Docker | ~0.5h | Low — co-hosted, minimal change |
| F: Testing/CI | ~2h | Low-Medium — new test surface |
| G: Docs/Cleanup | ~1h | Low |
| **Total** | **~11h** | |
