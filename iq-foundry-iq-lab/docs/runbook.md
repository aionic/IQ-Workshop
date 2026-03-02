# Runbook — IQ Foundry Agent Lab

## 15-Minute Demo Script

> **Audience:** Workshop attendees with a deployed environment (Lab 0 complete).
> This script walks through the full triage → approve → execute → observe cycle.

### 1. Open the Foundry Playground (1 min)

1. Navigate to the [Azure AI Foundry portal](https://ai.azure.com)
2. Open the **Agents playground**
3. Select the `iq-foundry-iq-lab` agent
4. Confirm the agent loads with the system prompt and tool definitions

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
2. Select the `iq-foundry-iq-lab` agent from the list
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
