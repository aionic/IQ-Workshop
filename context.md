# CODING_CONTEXT.md
## Comcast Business IQ Workshop — Day 2 Lab Build (Foundry-hosted Agent + Realistic Sim Data)

### Goal
Build a **hosted agent** that runs in **Foundry Agent Service** and is testable via the **Agents playground**. [7](https://microsofteur.sharepoint.com/teams/WECMO/_layouts/15/Doc.aspx?sourcedoc=%7B4224F5F3-1A72-4842-9EAB-E391875A8912%7D&file=BRK149%20-%20Azure%20AI%20Foundry%20Agent%20Service%20Transform%20agentic%20workflows.pptx&action=edit&mobileredirect=true&DefaultItemOpen=1)  
The lab must prove:
1) Safe tool invocation (allowlist + schema + human approval)
2) Structured data grounding (simulated but realistic)
3) Governance & safety controls (Entra/RBAC + audit + safe fallback)
4) Optional publish to Teams/M365

This aligns with IQ’s documented patterns:
- Observability, deterministic guardrails layered on ML/LLM behavior, safe fallback if model/service unavailable. [2](https://microsoft-my.sharepoint.com/personal/anevico_microsoft_com/_layouts/15/Doc.aspx?action=edit&mobileredirect=true&wdorigin=Sharepoint&DefaultItemOpen=1&sourcedoc={34bc7a14-ab07-4613-bffc-cbd909820439}&wd=target(/Accounts/Comcast/Comcast.one/)&wdpartid={b0b493d3-db98-4cb1-bfd3-0512cafeb713}{1}&wdsectionfileid={dcdb8c28-5c5d-4914-ba43-895cceeabef9})  
- “No data sprawl” (avoid shadow copies; prefer governed access). [2](https://microsoft-my.sharepoint.com/personal/anevico_microsoft_com/_layouts/15/Doc.aspx?action=edit&mobileredirect=true&wdorigin=Sharepoint&DefaultItemOpen=1&sourcedoc={34bc7a14-ab07-4613-bffc-cbd909820439}&wd=target(/Accounts/Comcast/Comcast.one/)&wdpartid={b0b493d3-db98-4cb1-bfd3-0512cafeb713}{1}&wdsectionfileid={dcdb8c28-5c5d-4914-ba43-895cceeabef9})  
- Workshop framing (IQ Today baseline → expansion vision). [1](https://loop.cloud.microsoft/p/eyJ1IjoiaHR0cHM6Ly9taWNyb3NvZnQtbXkuc2hhcmVwb2ludC5jb20vcGVyc29uYWwvcmljaGFyZGpfbWljcm9zb2Z0X2NvbT9uYXY9Y3owbE1rWndaWEp6YjI1aGJDVXlSbkpwWTJoaGNtUnFKVFZHYldsamNtOXpiMlowSlRWR1kyOXRKbVE5WWlVeU1XSktWVFZ1ZDA1RFRVVkhXR29sTlVaT1l6Sm9ZbVpsU0hseFpVSkVSbkZaZUU1MVl6SXlOME5PTlRkNGFqQnhTeVV5UkRKaGFrMHpVa2x1TTJRMVduVmxlR0owSm1ZOU1ERllTakpYVVVwYVJrcFJWMFJHVDBoWk4wNUdURlJDV1ZaQk5FMVdVRUZGV1NaalBTVXlSZyJ9)  

---

## A) Why Foundry-hosted (vs local CLI)
We want something the Comcast team can interact with **in the Foundry playground** (and later publish into M365/Teams).
- Foundry Agent Service provides a managed runtime for agents: orchestrates tool calls, integrates with Entra identity and RBAC, and supports governance/trust features. [3](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)  
- The Foundry Agent Service API is built around **agents, threads, messages, runs, tools**, with Entra auth + RBAC. [4](https://learn.microsoft.com/en-us/rest/api/aifoundry/aiagents/)  
- Hosted agents can be deployed and then interacted with via the Foundry playground. [5](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/quickstart-hosted-agent)  

---

## B) Lab storyline (single narrative, multiple checkpoints)
**Scenario:** A network/service anomaly is detected (simulated). The agent:
1) reads structured IQ tables (tickets/anomalies/devices)
2) produces a terse triage summary grounded in specific fields
3) proposes a safe action (non-destructive “remediation”)
4) requires approval (human in the loop)
5) executes via allowlisted tool
6) logs every decision + inputs + outputs (correlation id)
7) optionally posts summary to Teams

This maps to the IQ PDF’s production patterns:
- deterministic rules + human oversight build trust; observability; safe fallback if model unavailable. [2](https://microsoft-my.sharepoint.com/personal/anevico_microsoft_com/_layouts/15/Doc.aspx?action=edit&mobileredirect=true&wdorigin=Sharepoint&DefaultItemOpen=1&sourcedoc={34bc7a14-ab07-4613-bffc-cbd909820439}&wd=target(/Accounts/Comcast/Comcast.one/)&wdpartid={b0b493d3-db98-4cb1-bfd3-0512cafeb713}{1}&wdsectionfileid={dcdb8c28-5c5d-4914-ba43-895cceeabef9})  

---

## C) Architecture (Foundry agent + tools + mocks)

### Components
- **Foundry Hosted Agent**: instructions + tool wiring, tested in Agents playground. [7](https://microsofteur.sharepoint.com/teams/WECMO/_layouts/15/Doc.aspx?sourcedoc=%7B4224F5F3-1A72-4842-9EAB-E391875A8912%7D&file=BRK149%20-%20Azure%20AI%20Foundry%20Agent%20Service%20Transform%20agentic%20workflows.pptx&action=edit&mobileredirect=true&DefaultItemOpen=1)  
- **Structured data store** (simulated): Azure SQL (recommended) with seed data
- **Approval service**: lightweight “approval API” (can be mocked) OR Logic App/Teams approval
- **Tool execution service**: HTTPS tool endpoint(s) for:
  - query structured data (read-only)
  - execute remediation (writes only to remediation log / safe status field)
- **Observability**: App Insights + structured logs + correlation_id

### Mermaid (paste into README)
```mermaid
flowchart LR
  U[User in Foundry Playground] --> A[Foundry Hosted Agent]
  A -->|tool call: query| Q[Query Tool API (read-only)]
  Q --> D[(Azure SQL: iq_* tables)]
  A -->|tool call: request approval| P[Approval Tool API]
  P -->|approved| X[Execute Tool API]
  X --> L[(Azure SQL: iq_remediation_log)]
  X --> O[App Insights (correlation_id)]
  X --> T[Optional Teams Post]

### Repo Scaffold

iq-foundry-iq-lab/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── runbook.md
│   ├── guardrails.md
│   └── troubleshooting.md
├── infra/
│   ├── bicep/
│   ├── parameters/
│   └── azd/                 # optional, if you use Azure Developer CLI scaffolding
├── foundry/
│   ├── agent.yaml           # agent definition (instructions/tools)
│   ├── tools.openapi.json   # OpenAPI tool contract (query/approve/execute)
│   └── prompts/
│       └── system.md
├── services/
│   ├── api-tools/           # FastAPI (Python) or equivalent service exposing tool endpoints
│   └── data/                # data access layer
├── data/
│   ├── schema.sql
│   ├── seed.sql
│   └── generator/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy-dev.yml
└── samples/
    ├── playground-prompts.md
    └── sample-outputs/


 Tenant prep (Azure) — “minimum viable but credible”

Note: The specifics below are recommended implementation choices to match the workshop goals; they’re not claims about Comcast’s environment.

1) Resource group + naming (recommended)

rg-iq-agent-lab-dev
law-iq-agent-lab (Log Analytics) (optional if you prefer App Insights only)
appi-iq-agent-lab (Application Insights)
sql-iq-agent-lab + sqldb-iq (Azure SQL)
func-iq-tooling (Function App)
logic-iq-approval (Logic App)

2) Identity boundary (recommended)

Use Managed Identity for:

Function App
Agent runtime (if hosted)


Grant:

SQL db_datareader (agent)
SQL db_datawriter only to tool function (for remediation logs)



This expresses the same “bounded access” intent as the PDF’s emphasis on controlled behavior and traceability. [comcast_bu...211_223139 | PDF]
3) Observability baseline (recommended)
Implement what IQ already values in production:

track processing times, error rates, queue lengths (if you include a queue),
log each “AI decision” with the data it saw and the output it produced,
define a safe fallback when AI is unavailable. [comcast_bu...211_223139 | PDF]


E. Simulated data plan (so you can demo end-to-end)
The goal is to simulate realistic structured rows without touching customer data.
1) Minimal schema (example)
Create 3 tables:

iq_devices(device_id, site_id, model, last_seen_utc, health_state)
iq_anomalies(anomaly_id, device_id, detected_utc, severity, signal_type, metric_jitter_ms, metric_loss_pct, metric_latency_ms)
iq_tickets(ticket_id, anomaly_id, status, owner, created_utc, summary, customer_id, priority)

And 1 log table:

iq_remediation_log(remediation_id, ticket_id, proposed_action, approved_by, approved_utc, executed_utc, outcome, correlation_id)

2) Seed strategy

20–50 devices across 3–5 sites
40–100 anomalies across last 7–14 days
30–60 tickets with statuses like New, Investigate, Monitor, Closed

3) “Iteration hook” for the workshop
Include a seed.sql and a lightweight generator so the Comcast team can:

add a new “signal_type”
add new columns (e.g., throughput)
re-run lab and watch the agent adapt

This directly supports your goal: “simulate data so we can run end-to-end and have them iterate.”

F. Day 2 labs — technical acceptance criteria
Lab 1 — Prove safe tool invocation
Acceptance criteria

Agent can only invoke tools described in tools.json (allowlist).
Tool calls require a fixed JSON schema.
Agent must request approval before execution.

This reflects the “guardrails + human oversight” pattern used to prevent automation of errors. [comcast_bu...211_223139 | PDF]
Lab 2 — Use real structured data via agents
Acceptance criteria

Agent reads only via parameterized query or API (no raw string concatenation).
Agent summary references known fields (ticket_id, severity, site_id, timestamps) to reduce hallucinations.

The PDF explicitly recommends combining deterministic/structured extraction with LLM narrative to improve reliability. [comcast_bu...211_223139 | PDF]
Lab 3 — Apply governance & safety controls
Acceptance criteria

Identity boundary demonstrated (read-only vs writer separation).
Audit log shows who approved, what ran, when, outcome.
Safe fallback mode exists if LLM/tool dependency fails. [comcast_bu...211_223139 | PDF]

Lab 4 — Optional publish to Teams
Acceptance criteria

One message posted to Teams summarizing:

what happened
what data was used
what action ran
who approved
correlation_id to trace in logs


### Starter Tool Registry


{
  "tools": [
    {
      "name": "propose_remediation",
      "description": "Propose a safe remediation action for a ticket (no execution).",
      "input_schema": {
        "type": "object",
        "properties": {
          "ticket_id": { "type": "string" },
          "recommended_action": { "type": "string" },
          "rationale": { "type": "string" }
        },
        "required": ["ticket_id", "recommended_action", "rationale"]
      }
    },
    {
      "name": "execute_remediation",
      "description": "Executes an allowlisted remediation action after approval.",
      "input_schema": {
        "type": "object",
        "properties": {
          "ticket_id": { "type": "string" },
          "action": { "type": "string" },
          "approved_by": { "type": "string" },
          "correlation_id": { "type": "string" }
        },
        "required": ["ticket_id", "action", "approved_by", "correlation_id"]
      }
    }
  ]
}

E) “No Data Sprawl” design choices (lab constraints)

No copying full datasets into prompts.
Pass only identifiers + minimal structured fields into the model.
Keep an audit table for every tool call + approval + outcome.

This mirrors the “no shadow copies” principle in the IQ expansion plan. [Comcast | OneNote]

F) Simulated dataset (credible + safe)
Tables

iq_devices(device_id, site_id, model, last_seen_utc, health_state)
iq_anomalies(anomaly_id, device_id, detected_utc, severity, signal_type, jitter_ms, loss_pct, latency_ms)
iq_tickets(ticket_id, anomaly_id, status, owner, created_utc, priority, customer_id, short_summary)
iq_remediation_log(remediation_id, ticket_id, proposed_action, approved_by, approved_utc, executed_utc, outcome, correlation_id)

Seed strategy

20–50 devices across 3–5 sites
50–120 anomalies over last 14 days
40–80 tickets with realistic statuses: New / Monitor / Investigate / Closed
Ensure a few “high severity” cases for the demo


G) Guardrails (write these explicitly in docs/guardrails.md)
These are directly motivated by IQ’s production approach: deterministic filters + safe fallback + observability. [Comcast | OneNote]
Agent must:

be concise (3 bullets max for triage)
never speculate beyond provided fields
propose actions but require approval before executing
log every decision with correlation_id

Agent must not:

perform unapproved actions
use data outside the scoped ticket/anomaly
output sensitive-like fields in the demo (even if simulated, keep it “clean”)


H) Foundry compatibility notes (keep this accurate)

Agent Service REST API concepts include agents/threads/messages/runs/tools. [learn.microsoft.com]
Foundry supports identity via Entra + RBAC and governance/trust features. [What is Fo...soft Learn | Learn.Microsoft.com]
Hosted agents can be deployed and interacted with in the Foundry playground. [learn.microsoft.com]
Publishing to M365/Teams creates an agent application with a stable endpoint. [learn.microsoft.com]


I) Your “iteration mode” (what they can change live)
Pick 1–2 during the workshop:

Add a column to anomalies (e.g., throughput_mbps) + update triage summary
Add a new tool endpoint (stub) to show allowlist expansion
Tighten guardrails (“max 2 bullets” / “must cite fields used”)

This is consistent with the PDF’s guidance on prompt constraints and operational reliability.
