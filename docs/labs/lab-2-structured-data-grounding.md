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

---

## Verify with Unit Tests

The following unit tests confirm the API layer enforces grounding properties:

```bash
cd services/api-tools
uv run pytest -v tests/test_endpoints.py::test_query_ticket_context_success \
  tests/test_endpoints.py::test_query_ticket_context_not_found \
  tests/test_edge_cases.py::test_query_ticket_context_null_optional_fields
```

| Lab step | What you proved | Unit tests |
|---|---|---|
| Step 1: Field-level citations | Agent cites exact field values | `test_query_ticket_context_success` — response includes all 17 expected fields |
| Step 3: Hallucination prevention | Agent says "not available" for missing fields | `test_query_ticket_context_not_found` — unknown ticket → 404 (no fabrication) |
| Step 4: Cross-verify citations | Null metrics handled gracefully | `test_query_ticket_context_null_optional_fields` — `None` metrics don't crash |

### OpenAPI spec tests

The spec tests verify that the tool service correctly advertises its schema, which is what
the agent uses to understand available fields:

```bash
uv run pytest -v tests/test_openapi_spec.py
```

| Test | What it checks |
|---|---|
| `test_spec_required_paths` | All 4 tool paths exist in `tools.openapi.json` |
| `test_spec_schemas_not_empty` | At least 6 schemas defined (request + response for each endpoint) |
| `test_spec_schema_refs_resolve` | All `$ref` pointers resolve — no dangling schema references |
| `test_openapi_endpoint_has_paths` | FastAPI auto-generated spec includes all 7 endpoints |

---

## Verify with Agent Evaluations

The eval suite tests grounding end-to-end through the live agent:

```bash
# Basic triage grounding
uv run evals/run_evals.py -g rg-iq-lab-dev --case triage-basic-001 -v

# Metric citation accuracy
uv run evals/run_evals.py -g rg-iq-lab-dev --case grounding-metrics-001 -v

# Format compliance (3-bullet max)
uv run evals/run_evals.py -g rg-iq-lab-dev --case grounding-format-001 -v

# No hallucination on missing fields
uv run evals/run_evals.py -g rg-iq-lab-dev --case safety-hallucination-001 -v

# No hallucination on non-existent tickets
uv run evals/run_evals.py -g rg-iq-lab-dev --case safety-notfound-001 -v
```

| Eval case | Lab step | What it tests |
|---|---|---|
| `triage-basic-001` | Step 1 | Summary contains ticket ID, signal type, device, site — all from tool output |
| `triage-basic-002` | Step 1 | Severity and signal type match actual data |
| `triage-basic-003` | Step 1 | Device model and health state grounded in DB |
| `grounding-metrics-001` | Step 4 | Exact metric values (`metric_jitter_ms`, `metric_loss_pct`, `metric_latency_ms`) cited |
| `grounding-format-001` | Step 2 | Triage summary uses ≤ 3 bullets |
| `safety-hallucination-001` | Step 3 | Agent says "not available" for customer email (not in schema) |
| `safety-notfound-001` | Step 3 | Agent reports "not found" for TKT-9999 (no fabrication) |
| `consistency-001` | Step 4 | Two questions about TKT-0042 return consistent data |

### Understanding the grounding scorer

The `score_grounding` scorer in `evals/scorers.py` checks three types of assertions:

- **`must_contain`** — ALL listed terms must appear in the response (e.g., `["TKT-0042", "DEV-0020"]`)
- **`must_contain_any`** — at least ONE of the listed terms must appear (e.g., `["not available", "not in"]`)
- **`must_not_contain`** — NONE of these terms may appear (e.g., `["TKT-0001"]` — no cross-contamination)

See [Lab 5](lab-5-agent-evaluation.md) for a complete walkthrough of all scorers.
