# Lab 3 — Governance & Safety Controls

> **Estimated time:** 20 minutes
>
> **Objective:** Prove identity boundary (read-only vs writer separation), complete audit trail
> with correlation_id, and safe fallback when dependencies are unavailable.
>
> **Prerequisites:** Labs 0–2 complete

## Steps

### Part A: Identity Boundary

#### Step 1: Verify agent identity cannot write

Connect to Azure SQL as the agent identity (`id-iq-agent`) or simulate by checking permissions:

```sql
-- As Entra admin, check id-iq-agent permissions:
EXECUTE AS USER = 'id-iq-agent';
INSERT INTO dbo.iq_remediation_log (ticket_id, proposed_action, rationale, status, correlation_id)
VALUES ('TKT-TEST', 'test', 'test', 'PENDING', 'test-id');
-- Expected: permission denied error
REVERT;
```

#### Step 2: Verify tool service identity can write

```sql
-- As Entra admin, check id-iq-tools permissions:
EXECUTE AS USER = 'id-iq-tools';
INSERT INTO dbo.iq_remediation_log (ticket_id, proposed_action, rationale, status, correlation_id)
VALUES ('TKT-TEST', 'Identity test', 'Verifying write access', 'PENDING', 'identity-test-001');
-- Expected: success (1 row affected)

-- Clean up
DELETE FROM dbo.iq_remediation_log WHERE correlation_id = 'identity-test-001';
REVERT;
```

### Part B: Audit Trail

#### Step 3: Run a full triage cycle

In the Foundry playground, run the full flow:

1. "Summarize ticket TKT-0042"
2. "Recommend a remediation for TKT-0042"
3. (Approve via admin endpoint)
4. "Execute the approved remediation"

Note the `correlation_id` from the agent's responses.

#### Step 4: Query the remediation log

```sql
SELECT remediation_id, ticket_id, proposed_action, rationale,
       status, approved_by, approved_utc, outcome, executed_utc, correlation_id
FROM dbo.iq_remediation_log
WHERE ticket_id = 'TKT-0042'
ORDER BY created_utc DESC;
```

**Verify:**
- `approved_by` is populated (the operator who approved)
- `approved_utc` and `executed_utc` are set
- `correlation_id` matches what the agent used
- `status` progressed: PENDING → APPROVED → EXECUTED

#### Step 5: Trace in Application Insights

Open Application Insights → Logs, run this KQL query:

```kql
traces
| where customDimensions.correlation_id == "<your-correlation-id>"
| project timestamp, message, customDimensions
| order by timestamp asc
```

**Verify:** You see the full chain — query, request-approval, decide, execute-remediation — all linked by the same `correlation_id`.

### Part C: Safe Fallback

#### Step 6: Simulate dependency failure

Stop the tool service (or disconnect DB):

```bash
# Local: stop the api-tools container
docker compose stop api-tools

# Azure: scale container app to 0
az containerapp update --name <app> -g <rg> --min-replicas 0 --max-replicas 0
```

#### Step 7: Test agent response under failure

In the playground, ask:
```
Summarize ticket TKT-0042
```

**What to observe:**
- The tool call fails (timeout or error)
- The agent follows safe fallback: reports what happened, does not hallucinate data
- If the agent previously queried data in this session, it may report what it had

#### Step 8: Test API safe fallback directly

```bash
# With DB down, call the endpoint directly:
curl -X POST http://localhost:8000/tools/query-ticket-context \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "TKT-0042"}'
```

**Expected:** HTTP 503 with:
```json
{"detail": "Database unavailable — safe fallback", "fallback": true}
```

#### Step 9: Restore and verify recovery

```bash
# Local:
docker compose start api-tools

# Azure:
az containerapp update --name <app> -g <rg> --min-replicas 1 --max-replicas 3
```

Verify `GET /health` returns `{"status": "ok", "db": "connected"}` again.

### Part D: Network Verification (Private Mode Only)

#### Step 10: Confirm public access is disabled

```bash
az sql server show --resource-group <rg> --name <sql-server> \
  --query "publicNetworkAccess"
# Expected: "Disabled"
```

#### Step 11: Verify private DNS resolution

From inside the VNet (Cloud Shell or jumpbox):
```bash
nslookup <server>.database.windows.net
# Expected: resolves to private IP (10.x.x.x)
```

#### Step 12: Verify public access fails

From outside the VNet (your local machine):
```bash
sqlcmd -S <server>.database.windows.net -d sqldb-iq
# Expected: connection timeout or refused
```

## Checkpoints

- [ ] Agent identity cannot write to remediation log (permission denied)
- [ ] Tool service identity can write to remediation log (INSERT succeeds)
- [ ] Full audit trail in `iq_remediation_log` with all fields populated
- [ ] `correlation_id` traceable through Application Insights
- [ ] Safe fallback returns structured response (503 + `fallback: true`), not 500
- [ ] (Private mode) Public access is disabled, private endpoint resolves

## Expected Output

**Remediation log row:**
```
remediation_id | ticket_id | proposed_action           | status   | approved_by              | correlation_id
1              | TKT-0042  | Escalate to Investigate   | EXECUTED | operator@contoso.com     | 550e8400-...
```

**App Insights KQL result:**
```
timestamp                | message                                          | correlation_id
2026-03-01T10:00:01Z     | query-ticket-context ticket_id=TKT-0042         | 550e8400-...
2026-03-01T10:00:15Z     | request-approval ticket_id=TKT-0042             | 550e8400-...
2026-03-01T10:01:02Z     | decide-approval remediation_id=1 decision=APPROVED | 550e8400-...
2026-03-01T10:01:10Z     | execute-remediation ticket_id=TKT-0042          | 550e8400-...
```

## What You Proved

- Identity separation (read-only agent vs authorized tool service)
- Complete audit trail (every decision logged with correlation_id)
- Observability (correlation_id links all events in App Insights)
- Resilience (safe fallback when dependencies fail)
