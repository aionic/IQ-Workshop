# Phase 4 — Polish & Harden

> Status: **Complete**

## Tooling & Config

- [x] Add `pyproject.toml` with project metadata + ruff/pyright/pytest configs
- [x] Add `.pre-commit-config.yaml` (trailing whitespace, YAML/JSON check, ruff lint+format, pyright)
- [x] Configure `asyncio_mode = "auto"` to remove boilerplate `@pytest.mark.asyncio` need

## Lint — Ruff

- [x] Run `ruff check` — resolve all issues (14 found, all fixed)
- [x] Import ordering (`I001`) auto-fixed across 4 files
- [x] Removed unused imports (`F401` — `datetime` in schemas.py)
- [x] Removed unused variables (`F841` — `cid` in query-ticket-context)
- [x] Removed stale `# noqa` directives (`RUF100` — 3 instances)
- [x] Added `strict=True` to `zip()` call (`B905`)
- [x] Upgraded `timezone.utc` → `datetime.UTC` (`UP017`)
- [x] Suppressed false positives: `S105` (token scope), `SIM108` (readability)
- [x] Run `ruff format` — all files formatted consistently
- [x] Clean run: `All checks passed!`

## Type Checking — Pyright

- [x] Run `pyright app/` in basic mode
- [x] Fix `Row | None` type narrowing in `create_approval_request` — added explicit None guard
- [x] Clean run: `0 errors, 0 warnings, 0 informations`

## Tests — Safe Fallback (test_fallback.py)

- [x] `query-ticket-context` → DB error returns 503 + `{"fallback": true}`
- [x] `request-approval` → DB error returns 503 + `{"fallback": true}`
- [x] `execute-remediation` → DB error returns 503 + `{"fallback": true}`
- [x] `list-approvals` → DB error returns 503 + `{"fallback": true}`
- [x] `decide-approval` → DB error returns 503 + `{"fallback": true}`
- [x] `health` → DB down returns 200 + `{"db": "unavailable"}`

## Tests — Schema Validation (test_validation.py)

- [x] `query-ticket-context` — missing body → 422
- [x] `query-ticket-context` — wrong field name → 422
- [x] `query-ticket-context` — invalid JSON → 422
- [x] `request-approval` — missing required fields → 422
- [x] `request-approval` — empty body → 422
- [x] `execute-remediation` — missing fields → 422
- [x] `execute-remediation` — extra fields accepted (Pydantic default)
- [x] `decide-approval` — invalid decision literal → 422
- [x] `decide-approval` — missing approver → 422
- [x] `post-teams-summary` — missing fields → 422
- [x] `post-teams-summary` — empty body → 422

## Tests — OpenAPI Spec (test_openapi_spec.py)

- [x] Static spec: valid JSON
- [x] Static spec: declares OpenAPI 3.x
- [x] Static spec: all 4 tool paths present
- [x] Static spec: ≥6 schemas defined
- [x] Static spec: all `$ref` pointers resolve
- [x] FastAPI-generated spec: `/openapi.json` returns 200
- [x] FastAPI-generated spec: all 7 endpoint paths present
- [x] FastAPI-generated spec: title matches app config

## Tests — Edge Cases (test_edge_cases.py)

- [x] Health: DB connected → `{"db": "connected"}`
- [x] Health: POST method → 405
- [x] Query: empty ticket_id → 404
- [x] Query: null optional fields handled gracefully
- [x] Execute: unapproved token → 403 with detail
- [x] Approvals: empty list → `[]`
- [x] Decide: non-existent ID → 404
- [x] Teams: webhook success → `teams_posted=True`
- [x] Correlation ID header propagated
- [x] Nonexistent endpoint → 404

## Summary

| Metric | Before | After |
|---|---|---|
| Tests | 8 | **43** |
| Ruff errors | 14 | **0** |
| Pyright errors | 1 | **0** |
| Test files | 1 | **4** |
| pyproject.toml | none | **configured** |
| Pre-commit hooks | none | **6 hooks** |
