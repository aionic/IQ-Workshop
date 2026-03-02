You are an expert Azure engineer building a production-shaped workshop demo.
Create a repository scaffold named: iq-foundry-iq-lab

Objective:
Build a Microsoft Foundry / Azure AI Foundry hosted agent that can be tested in the Foundry Agents playground. The agent must:
1) Prove safe tool invocation (allowlist + schema validation + approvals)
2) Use realistic structured data (simulated) via parameterized queries
3) Apply governance/safety controls (identity boundary, audit logging, safe fallback)
4) Optionally publish a final summary message to Teams (allow a stub if not configured)

High-level requirements:
- Use simulated data only. Include SQL schema + seed scripts.
- Implement “no data sprawl”: do not copy full datasets into prompts; only pass minimal structured fields and ids.
- Implement deterministic + LLM blend: essential fields are extracted deterministically and used to ground summaries.
- Observability is mandatory: every run logs correlation_id and captures:
  - fields used (names + ids)
  - proposed action
  - approval decision
  - tool execution result
- Safe fallback: if model/tool unavailable, return a rules-only response (raw structured fields) and log fallback path.

Architecture constraints:
- Agent runtime itself MUST NOT have write access to main data tables.
- Only the tool execution service can write to iq_remediation_log (and optionally update a ticket status field).
- All tool calls must be allowlisted and validated against JSON schema or OpenAPI request validation.
- Approval is required before executing remediation.

Repository structure to generate:
iq-foundry-iq-lab/
  README.md
  docs/architecture.md
  docs/runbook.md
  docs/guardrails.md
  docs/troubleshooting.md
  foundry/agent.yaml
  foundry/prompts/system.md
  foundry/tools.openapi.json
  infra/bicep/main.bicep
  infra/bicep/parameters.dev.json
  services/api-tools/ (Python FastAPI)
    app/main.py
    app/schemas.py
    app/db.py
    app/logging.py
    requirements.txt
    Dockerfile
  data/schema.sql
  data/seed.sql
  data/generator/generate_seed.py (optional)
  .github/workflows/ci.yml
  .github/workflows/deploy-dev.yml

Foundry specifics:
- Include a foundry/agent.yaml that defines:
  - agent name/description
  - instructions (concise ops style)
  - tool definitions referencing the OpenAPI in foundry/tools.openapi.json
- Keep Foundry elements generic (do not hardcode tenant IDs). Use placeholders and TODO markers.
- Include a docs/runbook section: “How to test in Agents playground” (high level; do NOT assume secret portal URLs).

Tool endpoints (FastAPI):
Expose three endpoints:
1) POST /tools/query_ticket_context
   - input: ticket_id
   - output: minimal context (ticket fields + anomaly fields + device/site fields)
2) POST /tools/request_approval
   - input: ticket_id, proposed_action, rationale, correlation_id
   - output: approval_token + status (APPROVED/REJECTED/PENDING)
   - For workshop: implement a simple in-memory or sqlite approval store with an admin endpoint to approve/reject.
3) POST /tools/execute_remediation
   - input: ticket_id, action, approved_by, approval_token, correlation_id
   - behavior:
     - validate approval_token is approved
     - write a row into iq_remediation_log
     - optionally update iq_tickets.status to “Investigate” or “Monitor”
     - return outcome + timestamps

Data layer:
- Use Azure SQL (or local SQL Server in container for dev). Provide an easy local option (e.g., sqlite) ONLY if Azure SQL is unavailable, but default to Azure SQL.
- Provide parameterized queries only.

Infrastructure (Bicep):
Provision:
- Azure SQL server + database
- App Insights
- Container App or App Service for the FastAPI tool service (pick ONE; recommend Azure Container Apps)
- Managed identity for the tool service and role assignment notes.
- Output: tool service URL, app insights instrumentation key/connection string (as output placeholders)

CI/CD:
- ci.yml runs lint + unit tests
- deploy-dev.yml provisions Bicep and deploys container image; use placeholders for secrets.

Documentation:
- README explains: architecture, local run, deployment, and how to use Foundry playground to chat with the agent.
- docs/guardrails.md explicitly lists:
  - what agent can do
  - what agent cannot do
  - when approval is required
  - data minimization rules
- docs/runbook.md includes a 15-minute demo script aligned to:
  - propose action → approve → execute → audit → optional Teams post

Output instructions:
- Generate ALL files with full contents.
- Keep code minimal but real, with comments and TODO markers.
- Do not invent APIs that require credentials not defined in the repo.
- Include a sample set of playground prompts in samples/ (create this folder if needed).
``