# Guardrails — IQ Foundry Agent Lab

## What the Agent CAN Do

- **Query ticket/anomaly/device context** via the `query-ticket-context` allowlisted tool
- **Produce concise triage summaries** (up to 6 bullets or a short paragraph) citing specific field values from tool responses
- **Consult device operations manuals** (knowledge sources) for model-specific thresholds, CLI commands, and remediation guidance
- **Propose remediation actions** with rationale grounded in retrieved data
- **Request approval** for proposed actions via the `request-approval` tool
- **Execute approved remediations** using a valid `approval_token` (writes to `iq_remediation_log`, updates `iq_tickets.status`)
- **Post summary to Teams** via the `post-teams-summary` tool (when webhook is configured)
- **Generate and propagate `correlation_id`** across all tool calls in a single interaction

## What the Agent CANNOT Do

- **Execute any action without prior human approval** — the approval gate is mandatory
- **Access data outside the scoped tables** — only `iq_tickets`, `iq_anomalies`, `iq_devices` are queryable
- **Directly write to core data tables** (`iq_devices`, `iq_anomalies`, `iq_tickets` data columns) — only `iq_tickets.status` and `iq_remediation_log` are writable
- **Invoke tools not in the allowlist** — no arbitrary SQL, no shell commands, no file access
- **Speculate or fabricate data** not present in tool responses — must say "not available"
- **Return raw stack traces or internal errors** to users — safe fallback returns structured `ErrorResponse`
- **Retry failed tool calls more than once** — report what data is available and stop
- **Output sensitive-like fields** — even in simulated data, keep responses clean

## When Approval Is Required

Approval is **always required** before any write operation. The enforced flow is:

1. **Query** — agent retrieves ticket context (read-only)
2. **Summarize** — agent produces a triage summary for the operator
3. **Propose** — agent calls `request-approval` with the proposed action and rationale
4. **Await approval** — a human operator reviews via `GET /admin/approvals` and decides via `POST /admin/approvals/{id}/decide`
5. **Execute** — only after `status: APPROVED`, the agent calls `execute-remediation` with the `approval_token`

If the approval token is not `APPROVED`, the execute endpoint returns **403 Forbidden**.

## Data Minimization Rules

- **No `SELECT *`** — all queries explicitly list required columns
- **No bulk data dumps** — the agent queries one ticket at a time via `ticket_id`
- **Minimal fields in responses** — only the fields needed for triage are returned (17 scoped fields)
- **No shadow copies** — data stays in Azure SQL; the agent works with transient tool responses only
- **No conversation persistence** — agent context is per-session; no long-term data retention outside the DB
- **Remediation log is append-only** — past entries are never modified or deleted

## Output Constraints

- **Triage summaries:** Maximum 6 bullet points (or a short paragraph), each citing specific field names and values. Include only bullets relevant to the situation.
- **Field citations required:** Every claim must reference the field it came from (e.g., `severity: Critical`, `metric_jitter_ms: 142.5`)
- **No narrative embellishment:** Summaries are factual, not creative
- **Standard format enforced:** Triage and remediation proposals follow the templates in `prompts/system.md`
- **correlation_id in every response:** All tool call responses include the `correlation_id` for traceability
- **Structured errors only:** Failures return `{"detail": "...", "fallback": true}` — never raw exceptions

---

## Guardrail Verification — Tests & Evaluations

Every guardrail above is validated by unit tests (API layer) and/or agent evaluations (end-to-end).

### Unit test coverage

| Guardrail | Unit tests | File |
|---|---|---|
| Schema validation on tool inputs | 11 tests — missing fields, wrong types → 422 | `test_validation.py` |
| Approval gate enforcement | `test_execute_remediation_unapproved` → 403 | `test_endpoints.py` |
| Full approval flow | `test_approval_flow_end_to_end` | `test_endpoints.py` |
| Safe fallback on DB failure | 6 tests — every endpoint → 503 + `{"fallback": true}` | `test_fallback.py` |
| Health degrades gracefully | `test_health_db_down_still_200` → `db: "unavailable"` | `test_fallback.py` |
| Unknown routes rejected | `test_nonexistent_endpoint` → 404 | `test_edge_cases.py` |
| Wrong HTTP method rejected | `test_health_method_not_allowed` → 405 | `test_edge_cases.py` |
| OpenAPI spec correctness | 8 tests — paths, schemas, `$ref` resolution | `test_openapi_spec.py` |
| Null field handling | `test_query_ticket_context_null_optional_fields` | `test_edge_cases.py` |
| Teams stub without webhook | `test_teams_summary_stub_no_webhook` → `teams_posted: false` | `test_endpoints.py` |

Run all: `cd services/api-tools && uv run pytest -v`

### Agent evaluation coverage

| Guardrail | Eval case(s) | Category |
|---|---|---|
| No arbitrary SQL execution | `safety-refusal-001` — agent refuses SQL injection | `safety` |
| No data deletion | `safety-refusal-002` — agent refuses "delete all tickets" | `safety` |
| No hallucination on missing fields | `safety-hallucination-001` — agent says "not available" for customer email | `safety` |
| No hallucination on unknown tickets | `safety-notfound-001` — agent reports "not found" for TKT-9999 | `safety` |
| Approval required before execution | `governance-approval-001` — agent mentions approval/permission | `governance` |
| Field-level grounding | `grounding-metrics-001` — agent cites metric values from tool output | `grounding` |
| Triage format compliance (≤ 6 bullets) | `grounding-format-001` — bullet count ≤ 6 | `grounding` |
| Correct tool arguments | `tooluse-remediation-001` — `request_approval` called with `ticket_id: TKT-0042` | `tool_use` |
| Consistent data across queries | `consistency-001` — same ticket, same data from two questions | `consistency` |
| Grounded triage summary | `triage-basic-001`, `triage-basic-002`, `triage-basic-003` | `triage` |
| Knowledge-grounded thresholds | `knowledge-threshold-001` — agent cites manual thresholds in triage | `knowledge` |
| Knowledge-grounded CLI commands | `knowledge-cli-001` — agent provides vendor-specific CLI from manual | `knowledge` |
| Hybrid grounding (tools + knowledge) | `knowledge-hybrid-001` — triage blends live data + manual procedures | `knowledge` |
| Unknown model knowledge boundary | `knowledge-unknown-001` — agent says "not available" for unknown model | `knowledge` |
| SLA response times from knowledge | `knowledge-sla-001` — agent answers P1 SLA from device manuals | `knowledge` |

Run all: `uv run evals/run_evals.py --resource-group rg-iq-lab-dev`

### Verification quick reference

```bash
# API-layer guardrails (56 tests, no Azure needed)
cd services/api-tools && uv run pytest -v

# Agent-level guardrails (17 eval cases, requires live deployment)
uv run evals/run_evals.py -g rg-iq-lab-dev -v
```
