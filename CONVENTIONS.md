# Coding Conventions — iq-foundry-iq-lab

## Language & Frameworks

| Component | Technology | Version |
|---|---|---|
| Tool Service | Python + FastAPI | 3.12+ / 0.110+ |
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

- Framework: `pytest` + `pytest-asyncio` + `httpx`
- DB layer mocked by default via `unittest.mock.patch`
- Set `TEST_USE_DB=true` to run integration tests against local SQL container
- Test file naming: `test_*.py`
- One test file per module minimum; `test_endpoints.py` covers all API tests
- Assert both response status codes and response body structure
- Run: `cd services/api-tools && uv run pytest`
