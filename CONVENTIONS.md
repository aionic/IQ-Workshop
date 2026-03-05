# Coding Conventions — iq-foundry-iq-lab

## Language & Frameworks

| Component | Technology | Version |
|---|---|---|
| Tool Service | Python + FastAPI | 3.11+ / 0.110+ |
| MCP Server | FastMCP co-hosted at `/mcp` | Streamable HTTP transport |
| Models | Pydantic v2 | 2.0+ |
| Database | Azure SQL (deployed) / SQL Server Developer (local) | 2022 |
| Infrastructure | Bicep | latest |
| Observability | azure-monitor-opentelemetry | latest |
| Auth | azure-identity | latest |
| Container | Docker, Azure Container Apps | linux/amd64 |
| Package Manager | **uv** (never pip) | latest |

## Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Python variables/functions | snake_case | `get_ticket_context` |
| Python classes | PascalCase | `QueryTicketContextRequest` |
| URL paths | kebab-case | `/tools/query-ticket-context` |
| Environment variables | UPPER_SNAKE_CASE | `AZURE_SQL_SERVER_FQDN` |
| Bicep resources | camelCase symbolic names | `containerApp` |
| Azure resource names | kebab-prefix pattern | `ca-iq-lab-dev` |
| SQL tables | snake_case with `iq_` prefix | `iq_tickets` |
| SQL columns | snake_case | `ticket_id` |
| Correlation IDs | UUID v4 | `550e8400-e29b-41d4-a716-446655440000` |

## Python Code Style

- Type hints on all function signatures and return types
- Docstrings on all public functions (Google style)
- No `import *`
- Imports ordered: stdlib → third-party → local (enforced by `ruff`)
- Max line length: 120 characters
- Use `async def` for all FastAPI endpoint handlers and DB functions
- Use `Annotated` types for FastAPI dependency injection

## Database Access Rules

1. **All DB access goes through `app/db.py`** — no direct `pyodbc` usage in endpoints
2. **Parameterized queries only** — never use f-strings, `.format()`, or `%` for SQL
3. **Return minimal fields** — no `SELECT *`; explicitly list columns
4. **Read vs Write separation:**
   - `get_*` functions: read-only queries
   - `create_*`, `update_*`, `write_*` functions: mutations (only for `iq_remediation_log` and `iq_tickets.status`)
5. **Connection management:** connection pool created at startup, token refresh handled internally

## Security

### Auth Modes
```
DB_AUTH_MODE=password  → local SQL container (SA auth, dev only)
DB_AUTH_MODE=token     → Azure SQL (Managed Identity, all deployed environments)
```

### Rules
- **No passwords in Azure deployments** — managed identity + token auth only
- **No connection strings with passwords committed to git** — `.env` is gitignored
- **All Azure resources use managed identity** regardless of `networkMode` (public or private)
- **OIDC for GitHub Actions** — no stored client secrets
- **Scoped write access** — `id-iq-tools` MI can only write to `iq_remediation_log` and update `iq_tickets.status`

## Observability

- Every log entry is JSON structured
- Required fields in every log: `correlation_id`, `action`, `timestamp`
- Optional context fields: `ticket_id`, `device_id`, `severity`, `proposed_action`
- Use `logging.getLogger("iq-tools")` — matches the `configure_azure_monitor(logger_name=...)` config
- Log levels: INFO for normal operations, WARNING for fallback paths, ERROR for failures
- App Insights configured via `APPLICATIONINSIGHTS_CONNECTION_STRING` env var

## TODO Markers

Format: `# TODO(phase-N): description`

This enables the agentic coder to find remaining work by phase:
```bash
grep -rn "TODO(phase-1)" .   # Find all Phase 1 remaining tasks
grep -rn "TODO(phase-2)" .   # Find all Phase 2 remaining tasks
grep -rn "TODO(phase-3)" .   # Find all Phase 3 remaining tasks
```

## Error Handling

- All endpoints return structured error responses using `ErrorResponse` schema
- Safe fallback: if DB or external dependency is unreachable, return available data + `"fallback": true`
- Never return raw stack traces to clients — log them, return a clean error
- HTTP status codes: 200 (success), 400 (bad input), 403 (unauthorized/unapproved), 404 (not found), 503 (dependency unavailable)

## Package Management

- **`uv` is the ONLY Python package manager.** Never use `pip`, `pip install`, `pip freeze`, or `pip-compile`.
- Install dependencies: `uv sync` (uses `pyproject.toml`) or `uv pip install -r requirements.txt` (in Docker)
- Run tools: `uv run pytest`, `uv run ruff check .`
- Run scripts with inline deps (PEP 723): `uv run scripts/create_agent.py`
- In Dockerfiles: `COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv` then `uv pip install --system`
- In CI: install uv first, then use `uv sync` and `uv run`

## Testing

### Unit Tests

- Framework: `pytest` + `pytest-asyncio` + `httpx`
- DB layer mocked by default via `unittest.mock.patch`
- Set `TEST_USE_DB=true` to run integration tests against local SQL container
- Test file naming: `test_*.py`
- One test file per module minimum; `test_endpoints.py` covers all API tests
- Assert both response status codes and response body structure
- Run: `cd services/api-tools && uv run pytest`

#### Test file inventory (56 tests)

| File | Tests | Focus |
|---|---|---|
| `test_endpoints.py` | 8 | Core endpoint behavior — query, approval flow, execution, Teams stub |
| `test_fallback.py` | 6 | Safe fallback — every DB endpoint → 503 + `{"fallback": true}` on failure |
| `test_validation.py` | 11 | Schema validation — missing/wrong fields → 422 Unprocessable Entity |
| `test_openapi_spec.py` | 8 | OpenAPI spec validity — JSON parseable, paths exist, `$ref` resolution |
| `test_edge_cases.py` | 10 | Edge cases — empty IDs, null fields, wrong HTTP method, unknown routes |
| `test_mcp_server.py` | 13 | MCP server — tool registration, JSON-RPC calls, transport security, error handling |

### Agent Evaluations

- Framework: custom eval runner (`evals/run_evals.py`) with PEP 723 inline dependencies
- Runner: `uv run evals/run_evals.py --resource-group <rg>` (requires live Azure deployment)
- Dataset: `evals/dataset.json` — 17 test cases across 7 categories
- Scorers: `evals/scorers.py` — 6 independent scorers (tool_calls, grounding, format, safety, tool_call_args, knowledge)
- Results: timestamped JSON reports saved to `evals/results/` (gitignored)
- Categories: triage (3), safety (4), governance (1), grounding (2), tool_use (1), consistency (1), knowledge (5)
- Target pass rate: ≥ 90% (LLM non-determinism may cause occasional failures)
- Adding cases: append to `dataset.json` `cases` array with `id`, `category`, `prompt`, `expected_tools`, `assertions`
- Adding scorers: add function to `scorers.py`, register in `ALL_SCORERS` list

### Foundry Portal Evaluations

- Upload script: `evals/upload_to_foundry.py` (PEP 723, `uv run` directly)
- Converts local eval results (JSON) → JSONL with conversation-style `response` field
- Uploads as a Foundry dataset, creates an evaluation with 5 built-in evaluators, starts a run
- Built-in evaluators used: `tool_call_accuracy`, `task_adherence`, `intent_resolution`, `coherence`, `groundedness`
- `--no-wait` flag: start run without polling (check results in portal)
- `--dataset-only` flag: upload dataset without creating an evaluation
- Results also saved locally to `evals/results/foundry-eval-*.json`
- Foundry `response` field uses conversation message format (role + content list with tool_call / tool_result types)

## MCP Server

- **MCP tools are defined in `services/api-tools/app/mcp_server.py`** and co-hosted on the FastAPI app at `/mcp`
- Tool definitions delegate to the same `db.py` functions as the REST endpoints — no duplicated logic
- MCP transport is Streamable HTTP (`stateless_http=True, json_response=True`) — compatible with Foundry Agent Service, VS Code Copilot, Claude Desktop, etc.
- **Primary integration**: Foundry Agent Service connects directly to `/mcp` via `McpTool` — no client-side tool loop needed
- REST endpoints (`/tools/*`) are deprecated but still functional for backward compatibility
- When adding a new tool: add to both `app/main.py` (REST, deprecated) and `app/mcp_server.py` (MCP, primary), sharing `db.py` + `schemas.py`
- `create_agent.py` supports dual-mode: default for `McpTool` registration, `--legacy` for `FunctionTool`

### MCP Deployment Lessons Learned

1. **Trailing-slash redirect**: FastAPI `Mount("/mcp", mcp_app)` returns 307 for `/mcp` → `/mcp/`. Foundry Agent Service does NOT follow redirects. Fix: add ASGI middleware to rewrite `/mcp` → `/mcp/` transparently (`_rewrite_mcp_trailing_slash` in `main.py`).
2. **DNS rebinding protection (421)**: MCP library v1.26+ includes `TransportSecurityMiddleware` that validates the `Host` header. Behind Container Apps (TLS termination at load balancer), the Host header is the external FQDN which isn't in the default allowed list → 421. Fix: `TransportSecuritySettings(enable_dns_rebinding_protection=False)` passed to `FastMCP()` constructor.
3. **Proxy headers**: Container Apps forwards `X-Forwarded-*` headers. Uvicorn needs `--proxy-headers --forwarded-allow-ips *` to trust them.
4. **Accept header required**: When `json_response=True`, the MCP server returns 406 "Not Acceptable" if the client doesn't send `Accept: application/json`. Foundry Agent Service sends this automatically; manual `curl` testing must include it.
5. **Agent registration**: Use `McpTool(server_label=..., server_url=..., require_approval="always")` with `PromptAgentDefinition`. The server_url must point to the `/mcp` path, not the root.

## File Routing (MCP additions)

| Change | Files to update |
|---|---|
| New MCP tool | `services/api-tools/app/mcp_server.py`, `services/api-tools/app/db.py` (if new query), `services/api-tools/tests/test_mcp_server.py` |
| MCP config change | `services/api-tools/app/mcp_server.py`, `docker-compose.yml` (MCP_ENABLED env), `foundry/agent.yaml` |
| New deployment script | Add both `scripts/<name>.ps1` (PowerShell) **and** `scripts/<name>.sh` (Bash) |

## Cross-Platform Scripts

- Every deployment script exists in **PowerShell** (`.ps1`) and **Bash** (`.sh`) variants
- PowerShell scripts: Windows primary, `#Requires -Version 7.0`, use `Invoke-RestMethod` / `Invoke-Sqlcmd`
- Bash scripts: macOS/Linux primary, `#!/usr/bin/env bash`, use `curl` / `sqlcmd` CLI / `python3` for JSON
- CI (ubuntu-latest) uses the Bash variants
- Both variants support the same operations and equivalent flags
