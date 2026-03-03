# IQ Foundry Agent Lab — Deployment & Setup Guide

> **Turnkey deployment guide** for workshop proctors and lab participants.
> Takes you from a fresh Azure subscription to a fully operational Foundry agent
> with live tool endpoints in ~15 minutes.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Azure CLI** | 2.60+ | [Install](https://aka.ms/installazurecli) |
| **PowerShell** | 7.0+ | [Install](https://aka.ms/powershell) |
| **uv** | latest | [Install](https://docs.astral.sh/uv/getting-started/installation/) |
| **Git** | any | [Install](https://git-scm.com) |
| **SqlServer module** (PS) | auto-installed | `Install-Module SqlServer -Scope CurrentUser` |

**Azure requirements:**
- Active subscription with **Contributor** or **Owner** role
- `Microsoft.CognitiveServices` provider registered (script checks this)
- Sufficient quota for `gpt-5-mini` GlobalStandard (30K TPM) in your target region

---

## Quick Start

```powershell
# 1. Clone and navigate
git clone https://github.com/your-org/IQ-Workshop.git
cd IQ-Workshop

# 2. Log into Azure
az login
az account set --subscription "<your-subscription-id>"

# 3. Deploy everything (infra + image + DB seed)
.\scripts\deploy.ps1 -SeedDatabase

# 4. Grant managed identity DB access
.\scripts\seed-database.ps1 -GrantPermissions

# 5. Register the Foundry agent
.\scripts\register-agent.ps1
```

That's it. Your agent is ready to test in the [AI Foundry playground](https://ai.azure.com).

---

## What Gets Deployed

The `deploy.ps1` script provisions these resources via Bicep in a single resource group:

```
rg-iq-lab-dev (westus3)
├── ai-iq-lab-dev              Azure AI Services (S0) + gpt-5-mini deployment
├── sql-iq-lab-dev             Azure SQL Server (Entra-only auth)
│   └── sqldb-iq               Database with schema + seed data
├── acriqlabdev                Azure Container Registry
├── cae-iq-lab-dev             Container Apps Environment
│   └── ca-tools-iq-lab-dev    Tool Service (FastAPI, port 8000)
├── id-iq-tools-iq-lab-dev     Managed Identity (tool service)
├── id-iq-agent-iq-lab-dev     Managed Identity (Foundry agent)
├── appi-iq-lab-dev            Application Insights
└── law-iq-lab-dev             Log Analytics Workspace
```

---

## Step-by-Step Walkthrough

### Phase 1: Infrastructure Deployment

```powershell
# Deploy Bicep (creates all Azure resources)
.\scripts\deploy.ps1 -SkipImage
```

This runs `az deployment group create` with `infra/bicep/main.bicep`, creating:
- SQL Server + database (Entra-only auth, no passwords)
- Container Registry + Container Apps environment
- AI Services with gpt-5-mini model deployment (30K TPM)
- Managed identities with RBAC roles
- Application Insights + Log Analytics

**Duration:** ~5 minutes

### Phase 2: Seed the Database

```powershell
# Apply schema + sample data + managed identity permissions
.\scripts\seed-database.ps1 -GrantPermissions
```

This connects via your Entra identity and runs:
1. `data/schema.sql` — creates 4 tables
2. `data/seed.sql` — inserts 30 devices, 80 anomalies, 50 tickets
3. `data/grant-permissions.sql` — grants MI access (with `-GrantPermissions`)

**Duration:** ~30 seconds

### Phase 3: Build & Deploy the Tool Service

```powershell
# Build container image and update the Container App
.\scripts\deploy.ps1 -SkipBicep -ImageTag v4
```

This:
1. Runs `az acr build` to build the Docker image in ACR
2. Updates the Container App to use the new image
3. Runs the smoke test automatically

**Duration:** ~3 minutes

### Phase 4: Verify Everything Works

```powershell
# Run the full E2E smoke test
.\scripts\smoke-test.ps1
```

Tests all 7 endpoints:
```
1. GET  /health                       → status=ok, db=connected
2. POST /tools/query-ticket-context   → Returns ticket + device + anomaly data
3. POST /tools/query-ticket-context   → 404 for non-existent ticket
4. POST /tools/request-approval       → Creates PENDING remediation
5. POST /admin/approvals/{id}/decide  → Approves remediation
6. POST /tools/execute-remediation    → Executes approved remediation
7. POST /tools/post-teams-summary     → Logs summary
```

### Phase 5: Register the Foundry Agent

```powershell
.\scripts\register-agent.ps1
```

This creates a gpt-5-mini prompt agent with **Responses API compatible function tools**.
Tool calls are handled client-side by `chat_agent.py`.

**Option A — Python SDK (recommended, automated via `uv run`):**
```powershell
# uv auto-installs deps via PEP 723 inline metadata — no manual install needed
uv run scripts/create_agent.py --resource-group rg-iq-lab-dev
```

**Option B — Portal (for manual/interactive setup):**
1. Go to [ai.azure.com](https://ai.azure.com)
2. Create or select a project in `westus3`
3. Navigate to **Agents** → **+ New Agent**
4. Set model to `gpt-5-mini`
5. Paste system prompt from `foundry/prompts/system.md`
6. Add function tools matching the definitions in `scripts/create_agent.py`
7. Test via `uv run scripts/chat_agent.py --resource-group rg-iq-lab-dev`

### Phase 6: Test the Agent Interactively

```powershell
# Start a chat session with the agent — handles tool calls automatically
uv run scripts/chat_agent.py --resource-group rg-iq-lab-dev
```

Try: `Summarize ticket TKT-0042`

---

## Script Reference

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `deploy.ps1` | Full infrastructure + image deployment | `-SeedDatabase`, `-SkipBicep`, `-SkipImage`, `-ImageTag` |
| `seed-database.ps1` | Schema + seed data to Azure SQL | `-GrantPermissions`, `-ServerName`, `-DatabaseName` |
| `register-agent.ps1` | Foundry agent registration + SDK creation | `-AgentName`, `-ManualOnly` |
| `smoke-test.ps1` | E2E endpoint verification | `-BaseUrl` (auto-detected from Bicep outputs) |
| `create_agent.py` | Python SDK agent creation (PEP 723 deps) | `--resource-group` or env vars |
| `chat_agent.py` | Interactive agent chat with client-side tool execution | `--resource-group`, `--agent-id`, `--single` |

---

## Testing Locally (Docker Compose)

For local development without Azure:

```powershell
# Start SQL Server + tool service
cp .env.example .env
docker compose up

# Run smoke test against localhost
.\scripts\smoke-test.ps1 -BaseUrl http://localhost:8000

# Run unit tests
cd services/api-tools
uv sync --extra dev
uv run pytest
```

---

## Troubleshooting

### "db: unavailable" in health check
- **SQL public access disabled:** `az sql server update -n <sql-name> -g <rg> --set publicNetworkAccess=Enabled`
- **MI not granted access:** Run `.\scripts\seed-database.ps1 -GrantPermissions`
- **Database not seeded:** Run `.\scripts\seed-database.ps1`

### Container App not starting
```powershell
# Check logs (replace names or look up from Bicep outputs)
az containerapp logs show -n <ca-name> -g <rg> --tail 50 --type console

# Check revision status
az containerapp revision list -n <ca-name> -g <rg> -o table
```

### "QuotaExceeded" on AI Services
- Check quota: `az cognitiveservices usage list --location westus3 -o table`
- Reduce capacity in `parameters.dev.json`: set `aiModelCapacity` to 10

### Tests fail with "connection refused"
- Ensure Docker is running: `docker compose up -d`
- Wait for SQL health check: `docker compose ps`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Foundry Portal                         │
│                   ┌──────────────────────────┐                   │
│                   │   Foundry Prompt Agent    │                   │
│                   │   (gpt-5-mini)            │                   │
│                   │   + system prompt          │                   │
│                   │   + function tools          │                   │
│                   └──────────┬───────────────┘                   │
│                              │ requires_action                   │
│                              ▼                                   │
│   ┌──────────────────────────────────────────────────────┐       │
│   │   chat_agent.py (client-side tool loop)              │       │
│   │   Intercepts requires_action, calls tool service     │       │
│   └──────────────────────────┬───────────────────────────┘       │
│                              │ HTTP calls                        │
│                              ▼                                   │
│   ┌──────────────────────────────────────────────────────┐       │
│   │        Container App: ca-tools-iq-lab-dev             │       │
│   │        FastAPI Tool Service (:8000)                    │       │
│   │                                                        │       │
│   │   /health                    → liveness + DB check     │       │
│   │   /tools/query-ticket-context → 3-table JOIN           │       │
│   │   /tools/request-approval     → INSERT remediation_log │       │
│   │   /tools/execute-remediation  → validate + execute     │       │
│   │   /tools/post-teams-summary   → log or webhook         │       │
│   │   /admin/approvals           → list pending            │       │
│   │   /admin/approvals/{id}/decide → approve/reject        │       │
│   └──────────────────────┬───────────────────────────────┘       │
│                          │ token auth (MI)                        │
│                          ▼                                       │
│   ┌──────────────────────────────────────────────────────┐       │
│   │        Azure SQL: sqldb-iq                            │       │
│   │   iq_devices (30)  │  iq_anomalies (80)               │       │
│   │   iq_tickets (50)  │  iq_remediation_log (audit)       │       │
│   └──────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Conventions

- **uv only** — never pip (in scripts, Dockerfiles, CI, docs). `create_agent.py` uses PEP 723 inline deps so `uv run` auto-installs them.
- **Bicep naming:** `{type}-iq-lab-{env}` (e.g., `ca-tools-iq-lab-dev`)
- **Managed identity** for all Azure auth — no passwords
- **Parameterized SQL** only — no string concatenation
- See [CONVENTIONS.md](../CONVENTIONS.md) for full details
