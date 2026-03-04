# Phase 2 — API Service + Foundry Agent

**Goal:** Working FastAPI tool service with 3 endpoints + Foundry agent definition deployable to playground.

## Checklist

### Schemas & Models
- [x] `services/api-tools/app/schemas.py` — Pydantic v2 models for all request/response types
- [x] `services/api-tools/app/schemas.py` — `QueryTicketContextRequest` / `QueryTicketContextResponse`
- [x] `services/api-tools/app/schemas.py` — `RequestApprovalRequest` / `RequestApprovalResponse`
- [x] `services/api-tools/app/schemas.py` — `ExecuteRemediationRequest` / `ExecuteRemediationResponse`
- [x] `services/api-tools/app/schemas.py` — `ErrorResponse`, shared `CorrelationId` field

### Database Layer
- [x] `services/api-tools/app/db.py` — Connection pool with dual-auth (`DB_AUTH_MODE`: password/token)
- [x] `services/api-tools/app/db.py` — `get_ticket_context(ticket_id)` — parameterized JOIN
- [x] `services/api-tools/app/db.py` — `create_approval_request(...)` — insert PENDING row
- [x] `services/api-tools/app/db.py` — `get_approval(remediation_id)` / `decide_approval(...)`
- [x] `services/api-tools/app/db.py` — `execute_remediation(...)` — write log, update ticket status
- [x] `services/api-tools/app/db.py` — Token refresh logic for managed identity

### Observability
- [x] `services/api-tools/app/logging_config.py` — `configure_azure_monitor` setup
- [x] `services/api-tools/app/logging_config.py` — JSON structured logging middleware
- [x] `services/api-tools/app/logging_config.py` — `correlation_id` extraction/generation middleware

### API Endpoints
- [x] `services/api-tools/app/main.py` — `POST /tools/query-ticket-context`
- [x] `services/api-tools/app/main.py` — `POST /tools/request-approval`
- [x] `services/api-tools/app/main.py` — `POST /tools/execute-remediation`
- [x] `services/api-tools/app/main.py` — `GET /admin/approvals` (list pending)
- [x] `services/api-tools/app/main.py` — `POST /admin/approvals/{remediation_id}/decide`
- [x] `services/api-tools/app/main.py` — `GET /health`

### Packaging
- [x] `services/api-tools/requirements.txt` — all dependencies pinned
- [x] `services/api-tools/Dockerfile` — Python 3.11-slim, ODBC 18, port 8000, linux/amd64

### Tests
- [x] `services/api-tools/tests/test_endpoints.py` — happy path for all 3 tool endpoints
- [x] `services/api-tools/tests/test_endpoints.py` — approval flow (request → decide → execute)
- [x] `services/api-tools/tests/test_endpoints.py` — invalid ticket returns 404
- [x] `services/api-tools/tests/test_endpoints.py` — unapproved execution returns 403

### Foundry Definitions
- [x] `foundry/tools.openapi.json` — OpenAPI 3.0 spec for all tool endpoints
- [x] `foundry/prompts/system.md` — system prompt (ops style, 3-bullet triage, cite fields)
- [x] `foundry/agent.yaml` — agent definition (kind: hosted, protocols, tool refs, env vars)

## Acceptance Criteria
- `uvicorn app.main:app` starts locally, `GET /health` returns 200
- `/tools/query-ticket-context` returns structured data for a known `ticket_id`
- Approval flow works: request → admin decide → execute → verify remediation log row
- `pytest` passes with mocked DB
- `agent.yaml` name is alphanumeric+hyphens, protocols declared
- OpenAPI spec validates (no `spectral` errors)

## Dependencies
- Phase 1 complete (schema deployed, seed data loaded, docker-compose working)
