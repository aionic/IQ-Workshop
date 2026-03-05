# IQ Foundry Agent Lab — Deployment & Setup Guide

> **Turnkey deployment guide** for workshop proctors and lab participants.
> Takes you from a fresh Azure subscription to a fully operational Foundry agent
> with live tool endpoints in ~15 minutes.
>
> All scripts are available in **PowerShell** and **Bash** — use whichever matches
> your environment (Windows/macOS/Linux).

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Azure CLI** | 2.60+ | [Install](https://aka.ms/installazurecli) |
| **PowerShell** | 7.0+ (Windows) | [Install](https://aka.ms/powershell) |
| **Bash + curl** | any (macOS/Linux) | Pre-installed on macOS/Linux |
| **uv** | latest | [Install](https://docs.astral.sh/uv/getting-started/installation/) |
| **Git** | any | [Install](https://git-scm.com) |
| **SqlServer module** (PS only) | auto-installed | `Install-Module SqlServer -Scope CurrentUser` |
| **sqlcmd** (Bash only) | 18+ | macOS: `brew install microsoft/mssql-release/mssql-tools18` / [Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-setup-tools) |
| **python3** | 3.11+ | Pre-installed on macOS; [Download](https://python.org) |

**Azure requirements:**
- Active subscription with **Contributor** or **Owner** role
- `Microsoft.CognitiveServices` provider registered (script checks this)
- Sufficient quota for `gpt-4.1-mini` GlobalStandard (30K TPM) in your target region

---

## Quick Start

### PowerShell (Windows)

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

### Bash (macOS / Linux)

```bash
# 1. Clone and navigate
git clone https://github.com/your-org/IQ-Workshop.git
cd IQ-Workshop

# 2. Log into Azure
az login
az account set --subscription "<your-subscription-id>"

# 3. Deploy everything (infra + image + DB seed)
./scripts/deploy.sh --seed-database

# 4. Grant managed identity DB access
./scripts/seed-database.sh --grant-permissions

# 5. Register the Foundry agent
./scripts/register-agent.sh
```

That's it. Your agent is ready to test in the [AI Foundry playground](https://ai.azure.com).

---

## What Gets Deployed

The deploy script provisions these resources via Bicep in a single resource group:

```
<your-resource-group> (<your-region>)
├── <ai-services-name>         Azure AI Services (S0) + gpt-4.1-mini deployment
├── <sql-server-name>          Azure SQL Server (Entra-only auth)
│   └── sqldb-iq               Database with schema + seed data
├── <acr-name>                 Azure Container Registry
├── <ca-environment-name>      Container Apps Environment
│   └── <container-app-name>   Tool Service (FastAPI, port 8000)
├── <tools-mi-name>            Managed Identity (tool service)
├── <agent-mi-name>            Managed Identity (Foundry agent)
├── <app-insights-name>        Application Insights
└── <log-analytics-name>       Log Analytics Workspace
```

---

## Step-by-Step Walkthrough

### Phase 1: Infrastructure Deployment

<details><summary>PowerShell</summary>

```powershell
.\scripts\deploy.ps1 -SkipImage
```
</details>

<details><summary>Bash</summary>

```bash
./scripts/deploy.sh --skip-image
```
</details>

This runs `az deployment group create` with `infra/bicep/main.bicep`, creating:
- SQL Server + database (Entra-only auth, no passwords)
- Container Registry + Container Apps environment
- AI Services with gpt-4.1-mini model deployment (30K TPM)
- Managed identities with RBAC roles
- Application Insights + Log Analytics

**Duration:** ~5 minutes

### Phase 2: Seed the Database

<details><summary>PowerShell</summary>

```powershell
.\scripts\seed-database.ps1 -GrantPermissions
```
</details>

<details><summary>Bash</summary>

```bash
./scripts/seed-database.sh --grant-permissions
```
</details>

This connects via your Entra identity and runs:
1. `data/schema.sql` — creates 4 tables
2. `data/seed.sql` — inserts 30 devices, 80 anomalies, 50 tickets
3. `data/grant-permissions.sql` — grants MI access (with `-GrantPermissions` / `--grant-permissions`)

**Duration:** ~30 seconds

### Phase 3: Build & Deploy the Tool Service

<details><summary>PowerShell</summary>

```powershell
.\scripts\deploy.ps1 -SkipBicep -ImageTag v4
```
</details>

<details><summary>Bash</summary>

```bash
./scripts/deploy.sh --skip-bicep --image-tag v4
```
</details>

This:
1. Runs `az acr build` to build the Docker image in ACR
2. Updates the Container App to use the new image
3. Runs the smoke test automatically

**Duration:** ~3 minutes

### Phase 4: Verify Everything Works

<details><summary>PowerShell</summary>

```powershell
.\scripts\smoke-test.ps1
```
</details>

<details><summary>Bash</summary>

```bash
./scripts/smoke-test.sh
```
</details>

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

Registration is a two-step process: upload knowledge files, then create the agent.

<details><summary>PowerShell</summary>

```powershell
# Both steps in one command:
.\scripts\register-agent.ps1

# Or run each step separately:
uv run scripts/upload_knowledge.py -g <your-resource-group>
uv run scripts/create_agent.py -g <your-resource-group>
```
</details>

<details><summary>Bash</summary>

```bash
# Both steps in one command:
./scripts/register-agent.sh

# Or run each step separately:
uv run scripts/upload_knowledge.py -g <your-resource-group>
uv run scripts/create_agent.py -g <your-resource-group>
```
</details>

Step 1 uploads device manuals and docs to a Foundry vector store for knowledge grounding.
Step 2 creates a gpt-4.1-mini **Prompt Agent** (new-style, visible in the Foundry portal)
with MCP tools + FileSearchTool pointing at the vector store.

The vector store ID is persisted in `.agent-state.json` between steps so `create_agent.py`
automatically attaches the `FileSearchTool`.

**Option B -- Portal (for manual/interactive setup):**
1. Go to [ai.azure.com](https://ai.azure.com)
2. Create or select a project in your target deployment region
3. Navigate to **Agents** -> **+ New Agent**
4. Set model to `gpt-4.1-mini`
5. Paste system prompt from `foundry/prompts/system.md`
6. Add MCP tool pointing at `https://<container-app-fqdn>/mcp` with label `iq-tools`
7. Test via `uv run scripts/chat_agent.py --resource-group <your-resource-group>`

### Phase 6: Test the Agent Interactively

```bash
# Start a chat session — uses Responses API + MCP approval flow
uv run scripts/chat_agent.py --resource-group <your-resource-group>
```

Try: `Summarize ticket TKT-0042`

---

## Script Reference

### PowerShell (Windows)

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `deploy.ps1` | Full infrastructure + image deployment | `-SeedDatabase`, `-SkipBicep`, `-SkipImage`, `-ImageTag` |
| `seed-database.ps1` | Schema + seed data to Azure SQL | `-GrantPermissions`, `-ServerName`, `-DatabaseName` |
| `register-agent.ps1` | Two-step agent registration (knowledge + agent) | `-SkipKnowledge`, `-ManualOnly` |
| `smoke-test.ps1` | E2E endpoint verification | `-BaseUrl` (auto-detected from Bicep outputs) |

### Bash (macOS / Linux)

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `deploy.sh` | Full infrastructure + image deployment | `--seed-database`, `-s`, `--skip-bicep`, `--skip-image`, `--image-tag` |
| `seed-database.sh` | Schema + seed data to Azure SQL | `--grant-permissions`, `-s/--server-name`, `-d/--database-name` |
| `register-agent.sh` | Two-step agent registration (knowledge + agent) | `--skip-knowledge`, `--manual-only` |
| `smoke-test.sh` | E2E endpoint verification | `-b` base URL (auto-detected from Bicep outputs) |

### Cross-Platform (Python)

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `upload_knowledge.py` | Upload device manuals to Foundry vector store (PEP 723 deps) | `--resource-group`, `--force` |
| `create_agent.py` | Create Prompt Agent with MCP + FileSearch tools (PEP 723 deps) | `--resource-group`, `--vector-store-id`, `--legacy` |
| `chat_agent.py` | Interactive chat via Responses API + MCP approval flow | `--resource-group`, `--agent-name`, `--single`, `--legacy` |

---

## Testing Locally (Docker Compose)

For local development without Azure:

<details><summary>PowerShell</summary>

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
</details>

<details><summary>Bash</summary>

```bash
# Start SQL Server + tool service
cp .env.example .env
docker compose up

# Run smoke test against localhost
./scripts/smoke-test.sh -b http://localhost:8000

# Run unit tests
cd services/api-tools
uv sync --extra dev
uv run pytest
```
</details>

---

## Troubleshooting

### "db: unavailable" in health check
- **SQL public access disabled:** `az sql server update -n <sql-name> -g <rg> --set publicNetworkAccess=Enabled`
- **MI not granted access:** Run `seed-database.ps1 -GrantPermissions` or `seed-database.sh --grant-permissions`
- **Database not seeded:** Run `seed-database.ps1` or `seed-database.sh`

### Container App not starting
```bash
# Check logs (replace names or look up from Bicep outputs)
az containerapp logs show -n <ca-name> -g <rg> --tail 50 --type console

# Check revision status
az containerapp revision list -n <ca-name> -g <rg> -o table
```

### "QuotaExceeded" on AI Services
- Check quota: `az cognitiveservices usage list --location <your-region> -o table`
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
│                   │   (gpt-4.1-mini)          │                   │
│                   │   + system prompt          │                   │
│                   │   + MCPTool (iq-tools)       │                   │
│                   └──────────┬───────────────┘                   │
│                              │ Streamable HTTP                   │
│                              ▼                                   │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │   chat_agent.py (Responses API + MCP approval flow)      │   │
│   │   Auto-approves safe tools, prompts for execute_remed.   │   │
│   └──────────────────────────┬───────────────────────────────┘   │
│                              │ MCP server calls                  │
│                              ▼                                   │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │        Container App: <container-app-name>                │   │
│   │        FastAPI Tool Service (:8000)                        │   │
│   │        + MCP Server (Streamable HTTP at /mcp)               │   │
│   │                                                            │   │
│   │   /health                    → liveness + DB check         │   │
│   │   /tools/query-ticket-context → 3-table JOIN               │   │
│   │   /tools/request-approval     → INSERT remediation_log     │   │
│   │   /tools/execute-remediation  → validate + execute         │   │
│   │   /tools/post-teams-summary   → log or webhook             │   │
│   │   /admin/approvals           → list pending                │   │
│   │   /admin/approvals/{id}/decide → approve/reject            │   │
│   │   /mcp                       → MCP Streamable HTTP          │   │
│   └──────────────────────┬───────────────────────────────────┘   │
│                          │ token auth (MI)                        │
│                          ▼                                       │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │        Azure SQL: sqldb-iq                                │   │
│   │   iq_devices (30)  │  iq_anomalies (80)                   │   │
│   │   iq_tickets (50)  │  iq_remediation_log (audit)           │   │
│   └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

All scripts resolve the resource group from: CLI arg > `RESOURCE_GROUP` env var > interactive prompt.
No hardcoded defaults -- scripts prompt if the resource group is not provided.

---

## Conventions

- **uv only** -- never pip (in scripts, Dockerfiles, CI, docs). `create_agent.py` and `upload_knowledge.py` use PEP 723 inline deps so `uv run` auto-installs them.
- **Bicep naming:** `{type}-iq-lab-{env}` (e.g., `ca-tools-iq-lab-dev`)
- **Managed identity** for all Azure auth -- no passwords
- **Parameterized SQL** only -- no string concatenation
- See [CONVENTIONS.md](../CONVENTIONS.md) for full details
