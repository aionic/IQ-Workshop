# Guardrails — IQ Foundry Agent Lab

## What the Agent CAN Do

- **Query ticket/anomaly/device context** via the `query-ticket-context` allowlisted tool
- **Produce terse triage summaries** (3 bullets max) citing specific field values from tool responses
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

- **Triage summaries:** Maximum 3 bullet points, each citing specific field names and values
- **Field citations required:** Every claim must reference the field it came from (e.g., `severity: Critical`, `metric_jitter_ms: 142.5`)
- **No narrative embellishment:** Summaries are factual, not creative
- **Standard format enforced:** Triage and remediation proposals follow the templates in `prompts/system.md`
- **correlation_id in every response:** All tool call responses include the `correlation_id` for traceability
- **Structured errors only:** Failures return `{"detail": "...", "fallback": true}` — never raw exceptions
