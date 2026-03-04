# Phase 3 — Governance + Observability + CI/CD + Docs

**Goal:** Production-shaped guardrails, full documentation, CI/CD pipelines, lab guides, and sample content.

## Checklist

### Governance & Safety
- [x] `services/api-tools/app/main.py` — Safe fallback: try/except around DB calls, return `ErrorResponse` with `fallback: true` on failure
- [x] `services/api-tools/app/main.py` — Teams stub: `POST /tools/post-teams-summary` (log payload; POST to webhook if `TEAMS_WEBHOOK_URL` set)
- [x] `foundry/tools.openapi.json` — Add Teams endpoint to OpenAPI spec
- [x] `services/api-tools/app/schemas.py` — `PostTeamsSummaryRequest` / `PostTeamsSummaryResponse`

### CI/CD
- [x] `.github/workflows/ci.yml` — ruff lint, pyright type check, pytest, OpenAPI lint (spectral)
- [x] `.github/workflows/deploy-dev.yml` — Bicep deploy, ACR build+push (timestamp tag), Container App update, OIDC auth

### Documentation
- [x] `docs/architecture.md` — Mermaid diagrams (both network modes), component table, identity boundaries, data flow
- [x] `docs/guardrails.md` — Agent CAN/CANNOT lists, approval rules, data minimization, output constraints
- [x] `docs/runbook.md` — 15-minute demo script, playground testing instructions
- [x] `docs/troubleshooting.md` — Common issues: SQL connectivity, ODBC in container, App Insights, token auth, private endpoints
- [x] `README.md` — Architecture, prerequisites, local run, deployment, lab overview, playground usage

### Labs
- [x] `docs/labs/lab-0-environment-setup.md` — Track A (public) + Track B (private) + local dev track
- [x] `docs/labs/lab-1-safe-tool-invocation.md` — Allowlist, schema validation, approval gate
- [x] `docs/labs/lab-2-structured-data-grounding.md` — Field-level grounding, no hallucination, iteration hook
- [x] `docs/labs/lab-3-governance-safety.md` — Identity boundary, audit trail, safe fallback
- [x] `docs/labs/lab-4-teams-publish.md` — Stub validation, optional real Teams post

### Samples
- [x] `samples/playground-prompts.md` — 10 sample prompts (happy path, edge cases, iteration)
- [x] `samples/sample-outputs/triage-example.json` — Example agent response

## Acceptance Criteria
- CI workflow passes on push (lint, type check, tests, OpenAPI validation)
- Deploy workflow validates in dry-run mode
- All docs render correctly in GitHub markdown
- Safe fallback returns structured error, not 500
- Teams stub logs payload and returns success (without webhook configured)
- All 5 lab guides are complete with checkpoints and expected outputs
- Labs 1-4 pass when run against a deployed environment

## Dependencies
- Phase 1 + Phase 2 complete (all infrastructure, data, endpoints, and Foundry definitions working)
