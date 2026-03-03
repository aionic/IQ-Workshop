# Lab 0 — Environment Setup

> **Estimated time:** 20 min (public mode) / 35 min (private mode) / 2 min (local only)
>
> **Objective:** Deploy all infrastructure, seed the database, and verify the tool service
> is running. Choose your deployment track below.

## Prerequisites

Before starting, ensure you have:

- **Azure CLI** v2.60+ — `az --version`
- **Docker Desktop** (for local dev) — `docker --version`
- **Python 3.11+** — `python --version`
- **uv** (Python package manager) — `uv --version` (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Azure subscription** with Contributor access (for Azure deployment tracks)
- **Git** — `git --version`

## Track A: Public Mode (Workshop Default)

Use this track for workshops and demos where simplicity matters.

### Step 1: Clone and configure

```bash
git clone <repo-url> && cd iq-foundry-iq-lab
```

### Step 2: Create the resource group

```bash
az group create --name rg-iq-agent-lab-dev --location eastus2
```

### Step 3: Deploy infrastructure

```bash
az deployment group create \
  --resource-group rg-iq-agent-lab-dev \
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

This creates the `id-iq-tools` database user and grants scoped read/write permissions.

### Step 6: Build and push the container

```bash
ACR_NAME=<your-acr-name>
az acr login --name $ACR_NAME
docker build -t $ACR_NAME.azurecr.io/iq-lab-tools:latest \
  --platform linux/amd64 services/api-tools/
docker push $ACR_NAME.azurecr.io/iq-lab-tools:latest
```

### Step 7: Verify the tool service

```bash
curl https://<your-container-app>.azurecontainerapps.io/health
# → {"status": "ok", "db": "connected"}
```

### Step 8: Configure the Foundry agent

1. Open [Azure AI Foundry](https://ai.azure.com) → your project → **Agents**
2. Create a new agent using the config from `foundry/agent.yaml`
3. Upload `foundry/tools.openapi.json` as the tool definition
4. Set the system prompt from `foundry/prompts/system.md`
5. Set the tool service URL to your Container App FQDN
6. Test with: "Summarize ticket TKT-0042"

---

## Track B: Private Mode (Enterprise)

Use this track for production-like deployments with private endpoints.

### Step 1: Clone and configure

```bash
git clone <repo-url> && cd iq-foundry-iq-lab
```

### Step 2: Create resource group and deploy

```bash
az group create --name rg-iq-agent-lab-dev --location eastus2

az deployment group create \
  --resource-group rg-iq-agent-lab-dev \
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
  --image iq-lab-tools:latest \
  --platform linux/amd64 \
  --file services/api-tools/Dockerfile \
  services/api-tools/
```

### Step 5: Verify health (from within VNet)

```bash
# From Cloud Shell or jumpbox:
curl https://<container-app-internal-fqdn>/health
```

### Step 6: Configure Foundry agent

Same as Track A, Step 8. Use the internal Container App URL for the tool service.

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

### Step 3: Run tests

```bash
cd services/api-tools
uv venv && uv pip install -r requirements.txt
uv run pytest -v
```

---

## Checkpoint

- [ ] All Azure resources created (or docker compose running locally)
- [ ] Database seeded with schema + seed data (`SELECT COUNT(*) FROM dbo.iq_tickets` returns rows)
- [ ] Managed identity permissions granted (Azure only)
- [ ] `GET /health` returns `{"status": "ok", "db": "connected"}`
- [ ] Agent loaded in Foundry playground (Azure only)
