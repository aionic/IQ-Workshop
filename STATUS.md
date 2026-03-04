# IQ Foundry Agent Lab — Session Status & Handoff

> **Last updated:** 2026-03-04 (Agent registered as Prompt Agent, MCP 421 fixed, v3 deployed)
> **Author:** Project Maintainer + Copilot

---

## Quick Resume Checklist

```powershell
# 1. Log in and set subscription
az login
az account set --subscription "99d726d6-ee81-44f8-959f-4c4d59fddd82"

# 2. Verify the tool service is running
curl https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io/health

# 3. Register agent as new-style Prompt Agent (NOT classic/Assistants)
$env:AZURE_AI_PROJECT_ENDPOINT = "https://ai-iq-lab-dev.services.ai.azure.com/api/projects/iq-lab-project"
$env:TOOL_SERVICE_URL = "https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io"
uv run scripts/create_agent.py
# → Creates a PromptAgentDefinition + MCPTool agent; saves agent_name/version to .agent-state.json

# 4. Test agent interactively
uv run scripts/chat_agent.py
# → Or use env vars / --resource-group rg-iq-lab-dev
```

---

## Current Session Progress (Burn-Down & Redeploy)

| Step | Status | Summary |
|------|--------|---------|
| Burn down RG | ✅ Done | Deleted `rg-iq-lab-dev`, started clean |
| WSL auth | ✅ Done | Browser-based `az login` (device code disabled in tenant) |
| Phase 1: Bicep deploy | ✅ Done | Fixed ICU crash (`DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`), purged AI Services soft-delete, updated Entra admin SID |
| Phase 2: Seed database | ✅ Done | Go sqlcmd in WSL, SQL firewall rule added, 30/80/50/3 rows |
| Phase 3: Build & deploy image | ✅ Done | `acriqlabdev.azurecr.io/iq-tools:v1` via `az acr build`, Container App updated |
| Grant MI SQL permissions | ✅ Done | Via `Invoke-Sqlcmd -AccessToken` on Windows PowerShell |
| Health check | ✅ Done | `db=connected` confirmed |
| Phase 4: Smoke test | ✅ Done | 7/7 endpoints passed via `bash scripts/smoke-test.sh` |
| Phase 5: Register agent (legacy) | ✅ Done | `asst_Ik1XT1EP9vgreUblrycESny4` created in legacy FunctionTool mode |
| SDK MCP research | ✅ Done | Found correct imports — see SDK Reference below |
| Fix `create_agent.py` (round 1) | ✅ Done | Switched broken import to `azure.ai.agents.models.McpTool` (still classic agent) |
| Fix `chat_agent.py` (round 1) | ✅ Done | Switched to `AgentsClient` w/ threads/runs (still classic agent) |
| Phase 5G: Docs & cleanup | ✅ Done | architecture.md, agent.yaml, CONVENTIONS.md, lab docs, smoke tests updated for MCP |
| **Classic → Prompt Agent** | ✅ Done | Rewrote both scripts: `AIProjectClient.agents.create_version()` + Responses API |
| **create_agent.py rewrite** | ✅ Done | Uses `PromptAgentDefinition` + `MCPTool` from `azure.ai.projects.models` |
| **chat_agent.py rewrite** | ✅ Done | Uses `responses.create()` / `conversations.create()` + MCP approval flow |
| **scripts/README.md update** | ✅ Done | 7 replacements: Prompt Agent, MCPTool, Responses API, architecture diagram |
| **Register agent (Prompt Agent)** | ✅ Done | `iq-triage-agent:1` — visible in new Foundry portal (not classic) |
| **Fix MCP 421 (trailing slash)** | ✅ Done | Middleware rewrites `/mcp` → `/mcp/` to avoid Mount's 307 redirect |
| **Fix MCP 421 (host validation)** | ✅ Done | MCP 1.26 transport security rejects Host header; disabled DNS rebinding protection |
| **Deploy v3** | ✅ Done | `acriqlabdev.azurecr.io/iq-tools:v3` — revision `ca-tools-iq-lab-dev--0000003` |
| **Verify MCP endpoint** | ✅ Done | `POST /mcp/` returns 200 with initialize + tools/list (4 tools) |
| **Test in Foundry Playground** | 🔄 Testing | User testing interactively |
| **Commit all fixes** | ⬜ Not started | Multiple files modified (see below) |

---

## SDK Reference — New Agent API (Prompt Agent + Responses)

**Required packages:** `azure-ai-projects>=2.0.0b2` (installed: 2.0.0b4), `azure-identity>=1.15.0`, `openai>=1.68.0`

> **Note:** The old `azure-ai-agents` package (`AgentsClient`) creates **classic Assistants-based agents** that show under "Classic Agents" in the Foundry portal. The new API uses `AIProjectClient.agents.create_version()` with `PromptAgentDefinition` to create agents visible in the new portal experience.

### Agent Registration (create_agent.py)

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    MCPTool,                  # capital-M (not McpTool from azure.ai.agents)
    PromptAgentDefinition,    # kind='prompt' → new-style agent
    FunctionTool,             # for legacy mode only
)
from azure.identity import DefaultAzureCredential

project_client = AIProjectClient(endpoint=project_endpoint, credential=DefaultAzureCredential())

# MCP mode: agent calls MCP server directly; client handles approval flow
mcp_tool = MCPTool(server_label="iq-tools", server_url="https://.../mcp", require_approval="always")

agent = project_client.agents.create_version(
    agent_name="iq-triage-agent",
    description="IQ network triage agent",
    definition=PromptAgentDefinition(
        model="gpt-4.1-mini",
        instructions=system_prompt,
        tools=[mcp_tool],
        temperature=0.3,
    ),
)
# agent.name → "iq-triage-agent", agent.version → "1"
```

### Chat via Responses API (chat_agent.py)

```python
openai_client = project_client.get_openai_client()
conversation = openai_client.conversations.create()  # replaces threads

# Reference agent by name (NOT by ID)
agent_ref = {"agent": {"name": agent_name, "type": "agent_reference"}}

# Send message (blocks until response or approval needed)
response = openai_client.responses.create(
    conversation=conversation.id,
    input="Triage TKT-0042.",
    extra_body=agent_ref,
)

# MCP approval flow: check for mcp_approval_request items
from openai.types.responses.response_input_param import McpApprovalResponse

for item in response.output:
    if item.type == "mcp_approval_request":
        # Approve or reject, then chain with previous_response_id
        response = openai_client.responses.create(
            input=[McpApprovalResponse(type="mcp_approval_response", approve=True, approval_request_id=item.id)],
            previous_response_id=response.id,
            extra_body=agent_ref,
        )

print(response.output_text)  # final agent reply
```

### Key Difference: Classic (old) vs Prompt Agent (new)

| Aspect | Classic (`AgentsClient`) | Prompt Agent (`AIProjectClient`) |
|--------|--------------------------|----------------------------------|
| Package | `azure-ai-agents` | `azure-ai-projects` |
| Agent creation | `create_agent()` → `asst_...` ID | `agents.create_version()` → name + version |
| Chat pattern | threads → messages → runs → poll | `conversations.create()` → `responses.create()` |
| MCP tool class | `McpTool` (lowercase) | `MCPTool` (uppercase) |
| Portal visibility | "Classic Agents" section | New Agents experience |
| Tool execution | `submit_tool_outputs()` | `previous_response_id` chaining |

---

## Azure Resources — Live Environment

| Resource | Value |
|----------|-------|
| **Subscription** | `ME-MngEnvMCAP669594-anevico-1` |
| **Subscription ID** | `99d726d6-ee81-44f8-959f-4c4d59fddd82` |
| **Resource Group** | `rg-iq-lab-dev` |
| **Region** | `westus3` |
| **Entra Admin OID** | `98e79176-ff79-441d-ae4e-2bfc5ccf1a06` (Anthony Nevico) |

### Deployed Resources

| Resource | Name / FQDN |
|----------|-------------|
| **Container App** | `ca-tools-iq-lab-dev` |
| **Tool Service URL** | `https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io` |
| **MCP Server URL** | `https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io/mcp` |
| **Current Image** | `acriqlabdev.azurecr.io/iq-tools:v3` |
| **ACR** | `acriqlabdev` |
| **SQL Server** | `sql-iq-lab-dev.database.windows.net` |
| **SQL Database** | `sqldb-iq` |
| **AI Services** | `ai-iq-lab-dev` |
| **Foundry Project** | `iq-lab-project` |
| **Project Endpoint** | `https://ai-iq-lab-dev.services.ai.azure.com/api/projects/iq-lab-project` |
| **Model Deployment** | `gpt-4.1-mini` (GlobalStandard, 30K TPM) |

### Agent State (`.agent-state.json`)

```json
{
  "agent_name": "iq-triage-agent",
  "agent_version": "1",
  "tool_service_url": "https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io",
  "tool_mode": "mcp",
  "mcp_server_url": "https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io/mcp"
}
```

> **Note:** State file is rewritten by `create_agent.py`.  Previous sessions stored `agent_id: "asst_..."` — that was the classic agent. New schema uses `agent_name` + `agent_version`.

### Database Contents

| Table | Row Count | Notes |
|-------|-----------|-------|
| `iq_devices` | 30 | Network devices across 6 sites |
| `iq_anomalies` | 80 | Anomaly records linked to devices |
| `iq_tickets` | 50 | Support tickets (Open/InProgress/Resolved) |
| `iq_remediation_log` | 3 | Grows as execute-remediation is called |

---

## E2E Smoke Test (All 7/7 ✅ — now 8 with MCP)

```
1. GET  /health                        → status=ok, db=connected
2. POST /tools/query-ticket-context    → Returns ticket + device + anomalies
3. POST /tools/query-ticket-context    → 404 for non-existent ticket
4. POST /tools/request-approval        → Creates PENDING remediation
5. POST /admin/approvals/{id}/decide   → Approves/rejects remediation
6. POST /tools/execute-remediation     → Executes approved remediation
7. POST /tools/post-teams-summary      → Logs summary (httpbin mock)
8. POST /mcp                           → MCP server responds to initialize
```

---

## Bugs Fixed During Deployment (Historical)

### Bug 1: ODBC Driver .so Missing at Runtime (v1 → v2)
- **Symptom:** `/health` returned `db: unavailable`; logs showed `Can't open lib 'libmsodbcsql-18.6.so.1.1'`
- **Root Cause:** `apt-get purge -y --auto-remove` removed kerberos/TLS shared libs ODBC depends on
- **Fix:** `services/api-tools/Dockerfile` — removed `--auto-remove` flag from purge command

### Bug 2: cursor.description Wiped in execute_remediation (v2 → v3)
- **Symptom:** `TypeError: 'NoneType' object is not iterable` in `_row_to_dict`
- **Root Cause:** After `UPDATE...OUTPUT` fetched the result row, the subsequent `UPDATE iq_tickets` reset `cursor.description` to `None`
- **Fix:** `services/api-tools/app/db.py` — call `_row_to_dict(cursor, result)` immediately after `fetchone()`, **before** the ticket-status UPDATE

### Bug 3: MCP 421 — Starlette Mount 307 Redirect (v1 image → v2)
- **Symptom:** Foundry Agent Service got 421 "Misdirected Request" when calling `/mcp`
- **Root Cause:** `Mount("/mcp", ...)` issues a 307 redirect from `/mcp` → `/mcp/`. The `Location` header uses `http://` (not `https://`) because Container Apps terminates TLS at the load balancer. Foundry doesn't follow redirects, and the HTTP scheme causes a misdirect.
- **Fix:** `app/main.py` — added `@app.middleware("http")` that rewrites `/mcp` → `/mcp/` internally before the Mount handler sees it

### Bug 4: MCP 421 — Transport Security Host Validation (v2 → v3)
- **Symptom:** After fixing the redirect, `POST /mcp/` still returned 421 with body `Invalid Host header`
- **Root Cause:** MCP library v1.26.0 added `TransportSecurityMiddleware` (in `mcp/server/transport_security.py`) with DNS rebinding protection. When `enable_dns_rebinding_protection=True`, it validates the `Host` header against an `allowed_hosts` list. The Container App FQDN wasn't in the list, so every request was rejected.
- **Fix:** `app/mcp_server.py` — explicitly pass `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to the `FastMCP` constructor
- **Also:** `Dockerfile` — added `--proxy-headers --forwarded-allow-ips *` to the uvicorn CMD for correct `X-Forwarded-*` handling

---

## Uncommitted File Changes (This Session)

| File | Change |
|------|--------|
| `infra/bicep/parameters.dev.json` | Updated with real Entra OID + display name |
| `scripts/seed-database.sh` | Major rewrite for Go sqlcmd compatibility |
| `scripts/deploy.sh` | Added `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` for ICU fix |
| `scripts/create_agent.py` | **REWRITTEN**: Uses `AIProjectClient.agents.create_version()` + `PromptAgentDefinition` + `MCPTool` (new-style Prompt Agent) |
| `scripts/chat_agent.py` | **REWRITTEN**: Uses `responses.create()` / `conversations.create()` + MCP approval flow + legacy function call support |
| `scripts/README.md` | Updated: 7 replacements (Prompt Agent, MCPTool, Responses API, Streamable HTTP, architecture) |
| `scripts/smoke-test.sh` | Added MCP endpoint test (8/8) |
| `scripts/smoke-test.ps1` | Added MCP endpoint test (8/8) |
| `foundry/agent.yaml` | Rewritten for MCP: tool definitions, dual-mode docs, deployment_context |
| `docs/architecture.md` | MCP primary flow diagrams, updated component table, legacy flow preserved |
| `docs/labs/lab-0-environment-setup.md` | Agent registration via SDK (MCP mode), updated Track B ref |
| `docs/labs/lab-1-safe-tool-invocation.md` | MCP tool names, checkpoints reference `mcp_server.py` |
| `docs/labs/lab-2-structured-data-grounding.md` | snake_case tool names, OpenAPI section marked legacy |
| `docs/labs/lab-3-governance-safety.md` | Note about REST being deprecated for fallback test |
| `docs/labs/lab-4-teams-publish.md` | snake_case `post_teams_summary` tool name |
| `CONVENTIONS.md` | MCP transport updated to Streamable HTTP, primary integration note |
| `.github/copilot-instructions.md` | Architecture overview updated for MCP, Phase 4+5 listed, MCP file routing |
| `phases/phase-5-mcp.md` | All items marked complete |
| `services/api-tools/app/mcp_server.py` | Added `TransportSecuritySettings(enable_dns_rebinding_protection=False)` import + kwarg |
| `services/api-tools/app/main.py` | Added `_rewrite_mcp_trailing_slash` middleware to avoid Mount 307 redirect |
| `services/api-tools/Dockerfile` | Added `--proxy-headers --forwarded-allow-ips *` to uvicorn CMD |
| `services/api-tools/tests/test_mcp_server.py` | `test_mcp_endpoint_mounted` wraps RuntimeError (session manager not initialized) |
| `.agent-state.json` | Updated by create_agent.py: `agent_name=iq-triage-agent`, `agent_version=1`, `tool_mode=mcp` |

---

## Known Issues / Gotchas

### WSL `az login` Expires
- `DefaultAzureCredential` in WSL calls `az account get-access-token` as a subprocess — hangs if token expired
- **Workaround:** Run Python scripts from **Windows PowerShell** (not WSL), or re-run `az login` in WSL (browser flow)

### WSL `az` CLI is Slow
- `az deployment group show` subprocess hangs or is very slow in WSL
- **Workaround:** Use env vars (`$env:AZURE_AI_PROJECT_ENDPOINT`, `$env:TOOL_SERVICE_URL`) to bypass Bicep output resolution

### Go sqlcmd vs Classic sqlcmd
- WSL has Go-based `sqlcmd` which uses different auth flags than classic sqlcmd
- Windows PowerShell `Invoke-Sqlcmd -AccessToken` works reliably for token auth

---

## Useful Commands

### Register Agent (Prompt Agent via new API — from Windows PowerShell)
```powershell
$env:AZURE_AI_PROJECT_ENDPOINT = "https://ai-iq-lab-dev.services.ai.azure.com/api/projects/iq-lab-project"
$env:TOOL_SERVICE_URL = "https://ca-tools-iq-lab-dev.blackcliff-65f5258a.westus3.azurecontainerapps.io"
uv run scripts/create_agent.py
# → Uses AIProjectClient.agents.create_version() with PromptAgentDefinition + MCPTool
# → Saves agent_name + agent_version to .agent-state.json
```

### Test Agent Interactively
```powershell
uv run scripts/chat_agent.py
# Or with resource group auto-discovery:
uv run scripts/chat_agent.py --resource-group rg-iq-lab-dev
# → Uses Responses API (conversations.create + responses.create) with MCP approval flow
```

### Rebuild & Redeploy the Tool Service
```powershell
# Bump tag (currently v3)
az acr build --registry acriqlabdev --image iq-tools:v4 --platform linux/amd64 -f services/api-tools/Dockerfile services/api-tools
az containerapp update -n ca-tools-iq-lab-dev -g rg-iq-lab-dev --image acriqlabdev.azurecr.io/iq-tools:v4
```

### Database Access (PowerShell — Entra token auth)
```powershell
$token = (az account get-access-token --resource https://database.windows.net --query accessToken -o tsv)
Invoke-Sqlcmd -ServerInstance "sql-iq-lab-dev.database.windows.net" `
  -Database "sqldb-iq" -AccessToken $token `
  -Query "SELECT COUNT(*) AS n FROM iq_devices"
```

### Agent Evaluations
```bash
uv run evals/run_evals.py --resource-group rg-iq-lab-dev
uv run evals/run_evals.py -g rg-iq-lab-dev --case triage-basic-001 -v
```

---

## Potential Next Steps

| Priority | Task | Notes |
|----------|------|-------|
| 🔴 **Next** | **Test agent in Foundry Playground** | MCP endpoint verified (200 + 4 tools); test full triage → approve → execute cycle |
| 🔴 High | **Test with chat_agent.py** | `uv run scripts/chat_agent.py` — test MCP approval flow with Responses API |
| 🟡 Medium | **Run agent evals** | `uv run evals/run_evals.py --resource-group rg-iq-lab-dev` |
| 🟡 Medium | **Commit all fixes** | SDK migration, script rewrites, 421 fixes, doc updates, STATUS.md |
| 🟡 Medium | **Delete classic agent** | `asst_Ik1XT1EP9vgreUblrycESny4` still exists in Foundry — delete via portal or SDK |
| 🟢 Low | **Private networking** | Set `networkMode=private` in params, redeploy |
| 🟢 Low | **Agent memory & knowledge** | Foundry agent memory (conversation history) + knowledge (file/index grounding) — see `phases/phase-6-enhancements.md` |
| 🟢 Low | **Bump Python base image** | Dependabot PR #4: `python:3.12-slim` → `python:3.14-slim` in Dockerfile |

---

## Conventions Reminder
- **uv only** — never pip
- **ruff** for lint/format, **pyright** for type checks
- All tests via `cd services/api-tools && uv run pytest`
- Bicep naming: `{type}-iq-lab-{env}` (e.g., `ca-tools-iq-lab-dev`)
