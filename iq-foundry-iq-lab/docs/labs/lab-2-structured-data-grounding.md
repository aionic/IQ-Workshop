# Lab 2 — Structured Data Grounding

> **Estimated time:** 15 minutes
>
> **Objective:** Prove the agent uses structured data to ground responses — no hallucination,
> no data sprawl, and field-level citations match actual database values.
>
> **Prerequisites:** Lab 0 complete, Lab 1 demonstrates tool invocation works

## Steps

### Step 1: Verify Field-Level Citations

In the Foundry playground, type:
```
What's the severity and signal type for TKT-0042?
```

**What to observe:**
- The agent calls `queryTicketContext` and receives the full context
- The response cites **exact values** from the seed data (e.g., `severity: High`, `signal_type: jitter_spike`)
- Cross-check with the database:
  ```sql
  SELECT t.ticket_id, a.severity, a.signal_type
  FROM dbo.iq_tickets t
  JOIN dbo.iq_anomalies a ON t.ticket_id = 'TKT-0042'
  WHERE t.ticket_id = 'TKT-0042';
  ```

### Step 2: Test Data Minimization

Type:
```
Show me all high-severity tickets at site SITE-02
```

**What to observe:**
- The agent may query multiple tickets individually (one `queryTicketContext` call per ticket)
- It does **not** dump full table data — each call returns only the scoped 17 fields
- The response summarizes findings without raw data sprawl

### Step 3: Test Hallucination Prevention

Type:
```
What's the customer email for TKT-0042?
```

**What to observe:**
- The `QueryTicketContextResponse` includes `customer_id` but **not** a customer email field
- The agent should say the field is **"not available"** or words to that effect
- It must **not** fabricate an email address

### Step 4: Cross-Verify All Citations

For any ticket the agent summarizes, verify each cited value:
```sql
SELECT t.ticket_id, t.status, t.priority, a.severity, a.signal_type,
       a.metric_jitter_ms, a.metric_loss_pct, a.metric_latency_ms,
       d.device_id, d.site_id, d.model, d.health_state
FROM dbo.iq_tickets t
JOIN dbo.iq_anomalies a ON a.device_id = (
    SELECT TOP 1 device_id FROM dbo.iq_anomalies
    WHERE anomaly_id = REPLACE(t.ticket_id, 'TKT-', 'ANM-')
)
JOIN dbo.iq_devices d ON d.device_id = a.device_id
WHERE t.ticket_id = 'TKT-0042';
```

Every field the agent cites must match a value in the query result.

## Iteration Hook

This exercise demonstrates how the agent adapts when the schema evolves.

### Add a new metric column

```sql
ALTER TABLE dbo.iq_anomalies ADD throughput_mbps DECIMAL(10,2) NULL;

UPDATE dbo.iq_anomalies SET throughput_mbps = 450.25 WHERE anomaly_id = 'ANM-0042';
UPDATE dbo.iq_anomalies SET throughput_mbps = 820.10 WHERE anomaly_id = 'ANM-0015';
```

### Update the query in `db.py`

Add `throughput_mbps` to the SELECT in `get_ticket_context()` and add the field to `QueryTicketContextResponse` in `schemas.py`.

### Re-query

```
Summarize ticket TKT-0042 — does it include throughput data?
```

**Expected:** The agent now cites `throughput_mbps: 450.25` in its summary. This proves the grounding adapts to schema changes.

## Checkpoints

- [ ] Agent references specific field values (`severity`, `signal_type`, metrics)
- [ ] Cited values match actual database rows (verified via SQL)
- [ ] Agent says "not available" for fields not in the query result (not fabricated)
- [ ] No full dataset dumped into a single response (data minimization)

## Expected Output

**Agent response for "severity and signal type for TKT-0042":**
```
Based on the ticket context:
• **Severity:** High
• **Signal type:** jitter_spike
• **Key metric:** Jitter at 142.5 ms on device DEV-0007 (SITE-03)
```

**Agent response for "customer email":**
```
The customer email is not available in the ticket context data.
The available customer identifier is customer_id: CUST-003.
```

## What You Proved

- Deterministic + LLM blend (structured fields ground the narrative)
- No data sprawl (minimal fields queried, not full tables)
- No hallucination (agent cites only what the tool returned)
