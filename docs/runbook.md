# Runbook — IQ Foundry Agent Lab

## 15-Minute Demo Script

> **Audience:** Workshop attendees with a deployed environment (Lab 0 complete).
> This script walks through the full triage → approve → execute → observe cycle.

### 1. Open the Foundry Playground (1 min)

1. Navigate to the [Azure AI Foundry portal](https://ai.azure.com)
2. Open the **Agents playground**
3. Select the `iq-triage-agent` agent (new-style Prompt Agent)
4. Confirm the agent loads with the system prompt and MCP tool definitions

### 2. Query a Ticket (2 min)

Type in the playground:
```
Summarize ticket TKT-0042
```

**Verify:**
- Agent calls `query-ticket-context` (visible in the trace panel)
- Response cites specific fields: `severity`, `signal_type`, `device_id`, `site_id`, metrics
- Summary uses ≤ 3 bullets
- No fabricated data — all values match the seed data

### 3. Review the Triage Summary (1 min)

Check the agent's response against the database:
- `severity: High`, `signal_type: jitter_spike`
- `metric_jitter_ms: 142.5`, `metric_loss_pct: 0.3`
- `device_id: DEV-0007`, `site_id: SITE-03`

### 4. Propose Remediation (2 min)

Ask the agent:
```
What remediation do you recommend for TKT-0042?
```

**Verify:**
- Agent proposes an action with rationale citing data
- Agent calls `request-approval` (not `execute-remediation` directly)
- Response includes `status: PENDING` and an `approval_token`

### 5. Approve via Admin Endpoint (2 min)

Check pending approvals:
```bash
curl https://<your-container-app>/admin/approvals
```

Approve the request:
```bash
curl -X POST https://<your-container-app>/admin/approvals/<remediation_id>/decide \
  -H "Content-Type: application/json" \
  -d '{"decision": "APPROVED", "approver": "operator@contoso.com"}'
```

### 6. Execute Remediation (2 min)

Tell the agent:
```
Execute the approved remediation for TKT-0042
```

**Verify:**
- Agent calls `execute-remediation` with the `approval_token`
- Response includes `outcome` and `executed_utc`
- `correlation_id` is consistent across all calls in this session

### 7. Verify Audit Trail (3 min)

Query the remediation log:
```sql
SELECT * FROM dbo.iq_remediation_log WHERE ticket_id = 'TKT-0042';
```

Check Application Insights (KQL):
```kql
traces
| where customDimensions.correlation_id == "<your-correlation-id>"
| project timestamp, message, customDimensions
| order by timestamp asc
```

### 8. Optional: Teams Post (2 min)

Ask the agent:
```
Post a summary of the TKT-0042 remediation to Teams
```

If `TEAMS_WEBHOOK_URL` is configured → message appears in Teams channel.
If not → response shows `teams_posted: false, logged: true`.

---

## How to Test in Agents Playground

1. Navigate to [Azure AI Foundry](https://ai.azure.com) → your project → **Agents**
2. Select the `iq-triage-agent` agent from the list
3. Click **Open in playground** (or use the built-in chat pane)
4. Start a conversation using prompts from [Playground Prompts](../samples/playground-prompts.md)
5. Use the **Trace** tab on the right to inspect tool calls, request/response payloads, and timing
6. The trace view shows each tool invocation with its OpenAPI `operationId`

## Pre-Demo Checklist

- [ ] Azure resources deployed and healthy (`az resource list -g <rg>`)
- [ ] Database seeded (`SELECT COUNT(*) FROM dbo.iq_tickets` returns ≥ 20 rows)
- [ ] Managed identity permissions granted (`grant-permissions.sql` executed)
- [ ] `GET /health` returns `{"status": "ok", "db": "connected"}`
- [ ] Agent loaded in Foundry playground (tools visible in agent config)
- [ ] Application Insights receiving telemetry (check Live Metrics)
- [ ] (Optional) `TEAMS_WEBHOOK_URL` set on the Container App if demoing Teams
- [ ] Sample prompts ready (open `samples/playground-prompts.md`)
- [ ] Unit tests pass (see "Running Tests" section below)

---

## Running Tests

### Unit Tests — API Layer (No Azure Required)

Run the full suite of **56 tests** to verify the tool service behavior:

```bash
cd services/api-tools
uv sync --extra dev
uv run pytest -v
```

**Expected:** All 56 tests pass in ~2 seconds.

#### Test file walkthrough

| File | Tests | What it covers |
|---|---|---|
| `test_endpoints.py` | 8 | Core functionality — health check, query tickets, approval flow, execution, Teams stub |
| `test_fallback.py` | 6 | Safe fallback — every DB endpoint returns 503 + `{"fallback": true}` on DB failure |
| `test_validation.py` | 11 | Schema validation — missing/wrong fields → 422 Unprocessable Entity |
| `test_openapi_spec.py` | 8 | OpenAPI spec — JSON valid, paths exist, `$ref` pointers resolve, auto-generated spec matches |
| `test_edge_cases.py` | 10 | Edge cases — empty IDs, null fields, wrong HTTP method, correlation ID headers |
| `test_mcp_server.py` | 13 | MCP server — tool listing, ticket query, approval flow, execution, Teams, error handling |

#### Running specific test categories

```bash
# Just endpoint tests
uv run pytest -v tests/test_endpoints.py

# Just safe fallback tests
uv run pytest -v tests/test_fallback.py

# Just schema validation tests
uv run pytest -v tests/test_validation.py

# A single specific test
uv run pytest -v tests/test_endpoints.py::test_approval_flow_end_to_end
```

#### Key tests for demo purposes

If time is limited, these 5 tests demonstrate the most important properties:

```bash
uv run pytest -v \
  tests/test_endpoints.py::test_query_ticket_context_success \
  tests/test_endpoints.py::test_execute_remediation_unapproved \
  tests/test_endpoints.py::test_approval_flow_end_to_end \
  tests/test_fallback.py::test_query_ticket_context_db_error \
  tests/test_validation.py::test_query_ticket_context_missing_body
```

| Test | What it demonstrates |
|---|---|
| `test_query_ticket_context_success` | Correct ticket query returns all 17 grounding fields |
| `test_execute_remediation_unapproved` | Unapproved token → 403 Forbidden (approval gate works) |
| `test_approval_flow_end_to_end` | Full request → decide → execute cycle completes |
| `test_query_ticket_context_db_error` | DB failure → 503 + fallback (not 500 crash) |
| `test_query_ticket_context_missing_body` | Missing `ticket_id` → 422 (schema validation) |

---

## Running Agent Evaluations (Azure Required)

### Full eval suite

Run all 12 evaluation cases against the live agent:

```bash
uv run evals/run_evals.py --resource-group rg-iq-lab-dev
```

**Expected:** 11–12/12 cases pass (LLM non-determinism may cause occasional failures).

### Verbose single-case run (for demo)

```bash
uv run evals/run_evals.py -g rg-iq-lab-dev --case triage-basic-001 -v
```

Verbose mode shows:
- Each tool call the agent made
- The full agent response text
- Per-scorer pass/fail (5 scorers: tool_calls, grounding, format, safety, tool_call_args)

### Demo-worthy eval cases

| Case | What it shows | Good for demo? |
|---|---|---|
| `triage-basic-001` | Agent queries TKT-0042, cites correct fields | Yes — shows grounding |
| `safety-refusal-001` | Agent refuses SQL injection attempt | Yes — shows safety |
| `safety-hallucination-001` | Agent says "not available" for missing field | Yes — shows no hallucination |
| `governance-approval-001` | Agent mentions approval before executing | Yes — shows governance |
| `tooluse-remediation-001` | Agent calls `request_approval` with correct args | Yes — shows tool use |

### Reviewing results

Results are saved as timestamped JSON in `evals/results/`:

```bash
# Show the latest report
Get-ChildItem evals/results/ | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content | ConvertFrom-Json

# Or open in VS Code
code evals/results/
```

Each report includes metadata (agent ID, model, timestamp), summary (pass/fail counts),
and per-case details (prompt, response, tool calls, scorer breakdown).

See [Lab 5 — Agent Evaluation](labs/lab-5-agent-evaluation.md) for a full guided walkthrough.
