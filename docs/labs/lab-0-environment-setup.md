# Lab 0 — Environment Setup

> **Estimated time:** 20 min (public mode) / 35 min (private mode) / 2 min (local only)
>
> **Objective:** Deploy all infrastructure, seed the database, and verify the tool service
> is running. Choose your deployment track below.

## Prerequisites

Before starting, ensure you have:

- **Azure CLI** v2.60+ — `az --version`
- **PowerShell 7+** (for deployment scripts) — `pwsh --version` (install: `winget install Microsoft.PowerShell`)
- **Docker Desktop** (for local dev) — `docker --version`
- **Python 3.11+** — `python --version`
- **uv** (Python package manager) — `uv --version` (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Azure subscription** with required permissions (see [Required Azure Permissions](#required-azure-permissions) below)
- **Git** — `git --version`

---

## Required Azure Permissions

The deploying user (your Azure CLI identity) needs the following permissions on the target subscription or resource group:

| Permission / Role | Why it's needed | Scope |
|---|---|---|
| **Contributor** | Create resource groups, deploy Bicep resources (SQL, ACR, Container Apps, AI Services, managed identities, VNet) | Subscription or Resource Group |
| **User Access Administrator** _or_ **Role Based Access Control Administrator** | The Bicep template assigns RBAC roles (AcrPull for managed identity, Cognitive Services OpenAI User for MI) | Resource Group |
| **Cognitive Services Contributor** | Purge soft-deleted Cognitive Services accounts if redeploying within 48 hours | Subscription (for `az cognitiveservices account purge`) |
| **SQL Server Entra Admin** | Seed the database and grant managed identity permissions (`CREATE USER ... FROM EXTERNAL PROVIDER`) | Configured in Bicep parameters (`entraAdminObjectId`) |

> **Minimum combined role:** **Owner** on the resource group covers Contributor + User Access Administrator.
> For least-privilege setups, assign **Contributor** + **Role Based Access Control Administrator** at the resource group scope.

### Resource Providers Required

The following Azure resource providers must be registered on your subscription. Most are registered by default, but verify with `az provider list --query "[?registrationState=='Registered'].namespace" -o tsv`:

| Provider | Resources |
|---|---|
| `Microsoft.Sql` | Azure SQL Server + Database |
| `Microsoft.ContainerRegistry` | Azure Container Registry |
| `Microsoft.App` | Container Apps + Managed Environment |
| `Microsoft.ManagedIdentity` | User-assigned Managed Identities |
| `Microsoft.CognitiveServices` | Azure AI Services + Foundry Project + Model Deployment |
| `Microsoft.OperationalInsights` | Log Analytics Workspace |
| `Microsoft.Insights` | Application Insights (+ AMPLS in private mode) |
| `Microsoft.Authorization` | Role assignments (AcrPull, Cognitive Services OpenAI User) |
| `Microsoft.Network` | VNet, private endpoints, DNS zones (private mode only) |

Register any missing providers:
```bash
az provider register --namespace Microsoft.CognitiveServices
az provider register --namespace Microsoft.App
```

---

## Variables You Must Customize

The Bicep parameter files contain placeholder values that **must** be updated before deployment. The table below lists every variable you need to set — nothing else needs changing for a default workshop deployment.

### Bicep Parameters (`infra/bicep/parameters.dev.json`)

| Parameter | Current Value | What to Set | Required |
|---|---|---|---|
| `entraAdminObjectId` | `98e79176-ff79-441d-ae4e-2bfc5ccf1a06` | Your Entra ID user or group Object ID (find with `az ad signed-in-user show --query id -o tsv`) | **Yes** |
| `entraAdminDisplayName` | `Anthony Nevico` | Your name or group name matching the Object ID | **Yes** |
| `location` | `westus3` | Azure region — change only if `westus3` doesn't have gpt-4.1-mini capacity | Optional |
| `environmentName` | `dev` | Suffix for all resource names (e.g., `sql-iq-lab-dev`) | Optional |
| `aiModelName` | `gpt-4.1-mini` | Model to deploy — must be available in your region | Optional |
| `aiModelVersion` | `2025-04-14` | Model version — update if a newer version is available | Optional |
| `aiModelCapacity` | `30` | TPM capacity in 1K units (30 = 30K TPM) — increase if you hit quota limits | Optional |
| `toolServiceImage` | `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` | Leave as-is — `deploy.ps1` replaces this after ACR build | Do not change |

### Bicep Parameters — Private Mode (`infra/bicep/parameters.private.json`)

Same as above, **plus** these additional parameters:

| Parameter | Current Value | What to Set | Required |
|---|---|---|---|
| `entraAdminObjectId` | `TODO: your-entra-user-or-group-object-id` | Your Entra ID Object ID | **Yes** |
| `entraAdminDisplayName` | `TODO: Your Name or Group Name` | Your display name | **Yes** |
| `location` | `west3` | **Fix to** `westus3` (or your preferred region) — the default has a typo | **Yes** |
| `vnetAddressPrefix` | `10.0.0.0/16` | VNet CIDR — change only if it conflicts with existing networks | Optional |
| `snetContainerAppsPrefix` | `10.0.1.0/24` | Container Apps subnet CIDR | Optional |
| `snetPrivateEndpointsPrefix` | `10.0.2.0/24` | Private endpoints subnet CIDR | Optional |

### Script Defaults

The deployment scripts have sensible defaults but accept overrides:

| Script | Parameter | Default | What to change |
|---|---|---|---|
| `deploy.ps1` | `-ResourceGroup` | `rg-iq-lab-dev` | Your preferred resource group name |
| `deploy.ps1` | `-Location` | `westus3` | Azure region |
| `deploy.ps1` | `-ParameterFile` | `infra/bicep/parameters.dev.json` | Use `parameters.private.json` for private mode |
| `register-agent.ps1` | `-ResourceGroup` | `rg-iq-lab-dev` | Must match what you used for deployment |
| `seed-database.ps1` | `-ResourceGroup` | `rg-iq-lab-dev` | Must match what you used for deployment |
| `smoke-test.ps1` | `-ResourceGroup` | `rg-iq-lab-dev` | Must match what you used for deployment |

### Local Development (`.env`)

| Variable | Default in `.env.example` | What to change |
|---|---|---|
| `SA_PASSWORD` | `YourStr0ngP@ssword!` | Set a strong password (local SQL container only) |
| `DB_AUTH_MODE` | `password` | Leave as `password` for local; `deploy.ps1` sets `token` for Azure |
| `AZURE_SQL_SERVER_FQDN` | `localhost` | Leave as `localhost` for local; Azure uses Bicep output |
| `AZURE_SQL_DATABASE_NAME` | `sqldb-iq` | Leave as-is (matches Bicep) |

### How to Find Your Entra Admin Object ID

```powershell
# Your own Object ID (signed-in user)
az ad signed-in-user show --query id -o tsv

# A specific user
az ad user show --id user@contoso.com --query id -o tsv

# A group
az ad group show --group "IQ Lab Admins" --query id -o tsv
```

## Track A: Public Mode (Workshop Default)

Use this track for workshops and demos where simplicity matters.

### One-Command Deploy (Recommended)

The `deploy.ps1` script handles the full deployment lifecycle and is **idempotent** —
safe to re-run at any point. It will:

- Create the resource group if it doesn't exist
- Detect and prompt to purge soft-deleted Cognitive Services accounts (common after tearing down a previous deployment)
- Deploy all Bicep infrastructure (SQL, ACR, Container Apps, AI Services + gpt-4.1-mini)
- Build the tool service container image in ACR
- Update the Container App with the new image
- Seed the database (with `-SeedDatabase`) — including auto-creating a temporary SQL firewall rule for your IP
- Run a smoke test against all endpoints

```powershell
# From the repo root in PowerShell 7+:
.\scripts\deploy.ps1 -SeedDatabase
```

> **Re-running after errors:** The script is designed to be re-run. If a step fails
> (e.g., quota limits, network timeout), fix the issue and run the same command again.
> Schema and seed SQL scripts are idempotent — they clean up existing data before inserting.

> **Tearing down and rebuilding:** If you delete the resource group and redeploy within
> 48 hours, Azure's soft-delete policy on Cognitive Services accounts will block the Bicep
> deployment. The script automatically detects this and prompts you to purge the
> soft-deleted account before proceeding.

### Manual Step-by-Step (Alternative)

If you prefer to run each step individually, follow the steps below.

### Step 1: Clone and configure

```bash
git clone <repo-url> && cd iq-foundry-iq-lab
```

### Step 2: Create the resource group

```bash
az group create --name rg-iq-lab-dev --location westus3
```

### Step 3: Deploy infrastructure

```bash
az deployment group create \
  --resource-group rg-iq-lab-dev \
  --template-file infra/bicep/main.bicep \
  --parameters infra/bicep/parameters.dev.json
```

Wait for the deployment to complete (~5 min). Note the output values.

### Step 4: Seed the database

Connect to Azure SQL as Entra admin (Azure Data Studio, SSMS, or `sqlcmd`):

```bash
sqlcmd -S <server>.database.windows.net -d sqldb-iq \
  --authentication-method=ActiveDirectoryDefault
```

Run in order:
```sql
:r data/schema.sql
:r data/seed.sql        -- or run: python data/generator/generate_seed.py > data/seed.sql
```

### Step 5: Grant managed identity permissions

Still connected as Entra admin:
```sql
:r data/grant-permissions.sql
```

This creates the `id-iq-tools-iq-lab-dev` database user (the tools managed identity)
and grants scoped read/write permissions.

### Step 6: Build and push the container

```bash
ACR_NAME=<your-acr-name>
az acr login --name $ACR_NAME
docker build -t $ACR_NAME.azurecr.io/iq-tools:latest \
  --platform linux/amd64 services/api-tools/
docker push $ACR_NAME.azurecr.io/iq-tools:latest
```

### Step 7: Verify the tool service

```bash
curl https://<your-container-app>.azurecontainerapps.io/health
# → {"status": "ok", "db": "connected"}
```

### Step 8: Register the Foundry agent

The `register-agent.ps1` script auto-resolves all values from Bicep outputs and creates
the Foundry Prompt Agent with MCP tool integration:

```powershell
.\scripts\register-agent.ps1
```

This creates a Foundry Prompt Agent registered with `McpTool` pointing at the Container
App's `/mcp` endpoint (Streamable HTTP). Agent state is saved to `.agent-state.json`.

Alternatively, configure manually in [Azure AI Foundry](https://ai.azure.com):
1. Open your project → **Agents**
2. Create a new agent using the config from `foundry/agent.yaml`
3. Set the system prompt from `foundry/prompts/system.md`
4. Add an MCP tool with server URL: `https://<your-container-app>.azurecontainerapps.io/mcp`
5. Test with: "Summarize ticket TKT-0042"

---

## Track B: Private Mode (Enterprise)

Use this track for production-like deployments with private endpoints.

### Step 1: Clone and configure

```bash
git clone <repo-url> && cd iq-foundry-iq-lab
```

### Step 2: Create resource group and deploy

```bash
az group create --name rg-iq-lab-dev --location westus3

az deployment group create \
  --resource-group rg-iq-lab-dev \
  --template-file infra/bicep/main.bicep \
  --parameters infra/bicep/parameters.private.json
```

Deployment takes ~10 min (VNet, private endpoints, DNS zones).

### Step 3: Seed the database (from Cloud Shell or jumpbox)

Since public access is disabled, connect from within the VNet:

```bash
# From Azure Cloud Shell or a jumpbox VM in the VNet:
sqlcmd -S <server>.database.windows.net -d sqldb-iq \
  --authentication-method=ActiveDirectoryDefault
```

Run `data/schema.sql`, `data/seed.sql`, and `data/grant-permissions.sql`.

### Step 4: Build the container in ACR

Private ACR requires building inside Azure (no local push):

```bash
az acr build \
  --registry <acr-name> \
  --image iq-tools:latest \
  --platform linux/amd64 \
  --file services/api-tools/Dockerfile \
  services/api-tools/
```

### Step 5: Verify health (from within VNet)

```bash
# From Cloud Shell or jumpbox:
curl https://<container-app-internal-fqdn>/health
```

### Step 6: Register Foundry agent

Same as Track A, Step 8. Use the internal Container App URL as `TOOL_SERVICE_URL`.

---

## Local Development Track (Both Modes)

Use this to develop and test locally without Azure.

### Step 1: Start the environment

```bash
cp .env.example .env
# Edit .env: set SA_PASSWORD to a complex password
docker compose up -d
```

The `local-init.sh` script automatically runs `schema.sql` and `seed.sql`.

### Step 2: Verify

```bash
curl http://localhost:8000/health
# → {"status": "ok", "db": "connected"}
```

### Step 3: Run the test suite

The project includes **56 unit tests** across 6 test files. Run them with:

```bash
cd services/api-tools
uv sync --extra dev
uv run pytest -v
```

**Expected output:**

```
tests/test_endpoints.py::test_health_returns_ok PASSED
tests/test_endpoints.py::test_query_ticket_context_success PASSED
tests/test_endpoints.py::test_query_ticket_context_not_found PASSED
tests/test_endpoints.py::test_request_approval_success PASSED
tests/test_endpoints.py::test_execute_remediation_approved PASSED
tests/test_endpoints.py::test_execute_remediation_unapproved PASSED
tests/test_endpoints.py::test_approval_flow_end_to_end PASSED
tests/test_endpoints.py::test_teams_summary_stub_no_webhook PASSED
tests/test_fallback.py::test_query_ticket_context_db_error PASSED
...
======================== 56 passed in 2.xx s ========================
```

#### What the tests cover

| Test file | Tests | What it validates |
|---|---|---|
| `test_endpoints.py` | 8 | Core endpoint behavior — query, approval, execution, Teams stub |
| `test_fallback.py` | 6 | Safe fallback — every DB-dependent endpoint returns 503 + `{"fallback": true}` on DB failure |
| `test_validation.py` | 11 | Schema validation — missing/wrong fields produce 422 Unprocessable Entity |
| `test_openapi_spec.py` | 8 | OpenAPI spec validity — JSON parseable, paths exist, `$ref` pointers resolve |
| `test_mcp_server.py` | 13 | MCP server — tool discovery, initialization, streaming HTTP transport |
| `test_edge_cases.py` | 10 | Edge cases — empty ticket ID, null fields, wrong HTTP method, nonexistent routes |

All tests mock the DB layer by default, so they run without a database connection.

### Step 4: Run agent evaluations (Azure deployment only)

If you've deployed to Azure and registered an agent, run the automated eval suite:

```bash
# From the repo root:
uv run evals/run_evals.py --resource-group rg-iq-lab-dev
```

This sends 12 test prompts through the live agent and scores responses for grounding,
safety, governance, and format compliance. See [Lab 5](lab-5-agent-evaluation.md) for a
full walkthrough of the eval framework.

---

## Checkpoint

- [ ] All Azure resources created (or docker compose running locally)
- [ ] Database seeded with schema + seed data (`SELECT COUNT(*) FROM dbo.iq_tickets` returns rows)
- [ ] Managed identity permissions granted (Azure only)
- [ ] `GET /health` returns `{"status": "ok", "db": "connected"}`
- [ ] 56 unit tests pass (`uv run pytest -v` shows all green)
- [ ] Agent loaded in Foundry playground (Azure only)
- [ ] (Optional) Agent eval suite runs successfully (`uv run evals/run_evals.py`)
