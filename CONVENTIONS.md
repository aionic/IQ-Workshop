# Coding Conventions — iq-foundry-iq-lab

## Language & Frameworks

| Component | Technology | Version |
|---|---|---|
| Tool Service | Python + FastAPI | 3.12+ / 0.110+ |
| MCP Server | FastMCP co-hosted at `/mcp` | SSE transport |
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

#### Test file inventory (43 tests)

| File | Tests | Focus |
|---|---|---|
| `test_endpoints.py` | 8 | Core endpoint behavior — query, approval flow, execution, Teams stub |
| `test_fallback.py` | 6 | Safe fallback — every DB endpoint → 503 + `{"fallback": true}` on failure |
| `test_validation.py` | 11 | Schema validation — missing/wrong fields → 422 Unprocessable Entity |
| `test_openapi_spec.py` | 8 | OpenAPI spec validity — JSON parseable, paths exist, `$ref` resolution |
| `test_edge_cases.py` | 10 | Edge cases — empty IDs, null fields, wrong HTTP method, unknown routes |

### Agent Evaluations

- Framework: custom eval runner (`evals/run_evals.py`) with PEP 723 inline dependencies
- Runner: `uv run evals/run_evals.py --resource-group <rg>` (requires live Azure deployment)
- Dataset: `evals/dataset.json` — 12 test cases across 6 categories
- Scorers: `evals/scorers.py` — 5 independent scorers (tool_calls, grounding, format, safety, tool_call_args)
- Results: timestamped JSON reports saved to `evals/results/` (gitignored)
- Categories: triage (3), safety (4), governance (1), grounding (2), tool_use (1), consistency (1)
- Target pass rate: ≥ 90% (LLM non-determinism may cause occasional failures)
- Adding cases: append to `dataset.json` `cases` array with `id`, `category`, `prompt`, `expected_tools`, `assertions`
- Adding scorers: add function to `scorers.py`, register in `ALL_SCORERS` list

## MCP Server

- **MCP tools are defined in `services/api-tools/app/mcp_server.py`** and co-hosted on the FastAPI app at `/mcp`
- Tool definitions delegate to the same `db.py` functions as the REST endpoints — no duplicated logic
- MCP transport is SSE (Server-Sent Events) — compatible with VS Code Copilot, Claude Desktop, etc.
- When adding a new tool: add to both `app/main.py` (REST) and `app/mcp_server.py` (MCP), sharing `db.py` + `schemas.py`
- `create_agent.py` supports dual-mode dispatch: `--legacy` for FunctionTool, default for MCPTool via `mcp_server_url`

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
