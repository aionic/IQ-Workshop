# IQ Foundry Agent Lab — Session Status & Handoff

> **Last updated:** 2026-03-03 (Architecture refactor — Prompt Agent + clean redeploy)
> **Author:** Anthony Nevico + Copilot

---

## Quick Resume Checklist

```bash
# 1. Set the right subscription
az account set --subscription 99d726d6-ee81-44f8-959f-4c4d59fddd82

# 2. Verify the tool service is running
curl https://ca-tools-iq-lab-dev.jollydune-6d767ca5.westus3.azurecontainerapps.io/health

# 3. Check container app status
az containerapp show -n ca-tools-iq-lab-dev -g rg-iq-lab-dev --query "properties.runningStatus" -o tsv
```

---

## What's Done (Phases 1–4 + Deployment)

| Phase | Status | Summary |
|-------|--------|---------|
| **Phase 1** — Infra & Data | ✅ Complete | Bicep IaC, SQL schema, seed data, docker-compose |
| **Phase 2** — API & Agent | ✅ Complete | FastAPI service (7 endpoints), schemas, db layer, agent.yaml, OpenAPI, 8 tests |
| **Phase 3** — Governance & Observability | ✅ Complete | CI/CD (GitHub Actions), safe fallback, docs, labs, samples |
| **Phase 4** — Polish & Harden | ✅ Complete | pyproject.toml, pre-commit, 43 tests green, ruff clean, pyright clean |
| **Deployment** — Azure Live | ✅ Complete | All resources provisioned, image v3 running, all 7 endpoints verified E2E |
| **Refactor** — Prompt Agent | ✅ Complete | Switched from hosted→prompt agent, added Foundry project to Bicep, cleaned deps |

### Test Summary
- **43 tests** across 5 files, all passing
- `test_endpoints.py` (8), `test_fallback.py` (6), `test_validation.py` (11), `test_openapi_spec.py` (8), `test_edge_cases.py` (10)

---

## Azure Resources — Live Environment

| Resource | Value |
|----------|-------|
| **Subscription** | `ME-MngEnvMCAP669594-anevico-1` |
| **Subscription ID** | `99d726d6-ee81-44f8-959f-4c4d59fddd82` |
| **Resource Group** | `rg-iq-lab-dev` |
| **Region** | `westus3` |
| **Entra Admin OID** | `98e79176-ff79-441d-ae4e-2bfc5ccf1a06` |

### Deployed Resources

| Resource | Name / FQDN |
|----------|-------------|
| **Container App** | `ca-tools-iq-lab-dev` |
| **Tool Service URL** | `https://ca-tools-iq-lab-dev.jollydune-6d767ca5.westus3.azurecontainerapps.io` |
| **CA Environment** | `cae-iq-lab-dev` |
| **Current Image** | `acriqlabdev.azurecr.io/iq-tools:v4` |
| **Active Revision** | `ca-tools-iq-lab-dev--0000004` |
| **ACR** | `acriqlabdev.azurecr.io` |
| **SQL Server** | `sql-iq-lab-dev.database.windows.net` |
| **SQL Database** | `sqldb-iq` |
| **AI Services** | `ai-iq-lab-dev` (`https://ai-iq-lab-dev.cognitiveservices.azure.com/`) |
| **Foundry Project** | `iq-lab-project` (standalone project under AI Services) |
| **Project Endpoint** | `https://ai-iq-lab-dev.services.ai.azure.com/api/projects/iq-lab-project` |
| **Model Deployment** | `gpt-4.1-mini` (GlobalStandard, 30K TPM, version 2025-08-07) |
| **App Insights** | `InstrumentationKey=48e447dd-cbce-4d84-8375-7e704f28d31e` |

### Managed Identities

| Identity | Client ID | Principal ID |
|----------|-----------|--------------|
| **id-iq-tools-iq-lab-dev** (Tool Service) | `83254f15-4947-4671-9a2c-ce6b566af546` | `2f46d82c-54c4-4a0f-a661-809e3fa6ecdb` |
| **id-iq-agent-iq-lab-dev** (Agent) | `c76f40f0-fa0d-4f32-938b-7bd50f5f4808` | `61640bea-4acf-4bd8-bf27-a5ccd1986de2` |

Both MIs have `db_datareader` + `db_datawriter` roles on `sqldb-iq`.
Both MIs have `Cognitive Services OpenAI User` role on `ai-iq-lab-dev`.

### Database Contents

| Table | Row Count | Notes |
|-------|-----------|-------|
| `iq_devices` | 30 | Network devices across 6 sites |
| `iq_anomalies` | 80 | Anomaly records linked to devices |
| `iq_tickets` | 50 | Support tickets (Open/InProgress/Resolved) |
| `iq_remediation_log` | 3+ | Grows as execute-remediation is called |

---

## E2E Endpoint Verification (All ✅)

```
1. GET  /health                        → status=ok, db=connected
2. POST /tools/query-ticket-context    → Returns ticket + device + anomalies
3. POST /tools/request-approval        → Creates PENDING remediation
4. POST /admin/approvals/{id}/decide   → Approves/rejects remediation
5. POST /tools/execute-remediation     → Executes approved remediation
6. POST /tools/post-teams-summary      → Logs summary (httpbin mock)
7. GET  /admin/approvals               → Lists pending approvals
```

---

## Bugs Fixed During Deployment

### Bug 1: ODBC Driver .so Missing at Runtime (v1 → v2)
- **Symptom:** `/health` returned `db: unavailable`; logs showed `Can't open lib 'libmsodbcsql-18.6.so.1.1'`
- **Root Cause:** `apt-get purge -y --auto-remove` removed kerberos/TLS shared libs ODBC depends on
- **Fix:** `services/api-tools/Dockerfile` — removed `--auto-remove` flag from purge command
- **Also:** Added `AllowAzureServices` SQL firewall rule (0.0.0.0 – 0.0.0.0) for Container Apps access

### Bug 2: cursor.description Wiped in execute_remediation (v2 → v3)
- **Symptom:** `TypeError: 'NoneType' object is not iterable` in `_row_to_dict`
- **Root Cause:** After `UPDATE...OUTPUT` fetched the result row, the subsequent `UPDATE iq_tickets` reset `cursor.description` to `None`
- **Fix:** `services/api-tools/app/db.py` — call `_row_to_dict(cursor, result)` immediately after `fetchone()`, **before** the ticket-status UPDATE; store in `result_dict`

---

## Files Modified During Deployment (vs. Phase 4)

| File | Change |
|------|--------|
| `infra/bicep/parameters.dev.json` | Real Entra admin values, `location` → `westus3` |
| `infra/bicep/main.bicep` | `principalType: 'Group'` → `'User'` |
| `services/api-tools/Dockerfile` | Removed `--auto-remove` from apt-get purge |
| `services/api-tools/app/db.py` | Fixed cursor.description bug in `execute_remediation()` |

---

## Turnkey Deployment Scripts

All deployment is automated via PowerShell scripts in `scripts/`. See [scripts/README.md](scripts/README.md) for the full walkthrough.

```powershell
# Full deployment from scratch (~15 min)
az login
az account set --subscription 99d726d6-ee81-44f8-959f-4c4d59fddd82
.\scripts\deploy.ps1 -SeedDatabase
.\scripts\seed-database.ps1 -GrantPermissions
.\scripts\register-agent.ps1
```

| Script | Purpose |
|--------|--------|
| `scripts/deploy.ps1` | Bicep infra + ACR image build + Container App update |
| `scripts/seed-database.ps1` | Schema + seed data + MI permissions via Entra token |
| `scripts/register-agent.ps1` | Foundry agent config output + Python SDK helper |
| `scripts/smoke-test.ps1` | E2E verification of all 7 endpoints |
| `scripts/create_agent.py` | Python SDK agent registration (generated) |

---

## Useful Commands

### Rebuild & Redeploy the Tool Service
```powershell
# One-liner rebuild + redeploy
.\scripts\deploy.ps1 -SkipBicep -ImageTag v5

# Or manually:
az acr build --registry acriqlabdev --image iq-tools:v5 --platform linux/amd64 .
az containerapp update -n ca-tools-iq-lab-dev -g rg-iq-lab-dev --image acriqlabdev.azurecr.io/iq-tools:v5

# Tail logs
az containerapp logs show -n ca-tools-iq-lab-dev -g rg-iq-lab-dev --follow
```

### Database Access (PowerShell — Entra token auth)
```powershell
$token = (az account get-access-token --resource https://database.windows.net --query accessToken -o tsv)
Invoke-Sqlcmd -ServerInstance "sql-iq-lab-dev.database.windows.net" `
  -Database "sqldb-iq" -AccessToken $token `
  -Query "SELECT COUNT(*) AS n FROM iq_devices"
```

### Full Bicep Redeploy
```bash
az deployment group create \
  --resource-group rg-iq-lab-dev \
  --template-file infra/bicep/main.bicep \
  --parameters infra/bicep/parameters.dev.json
```

---

## Potential Next Steps

| Priority | Task | Notes |
|----------|------|-------|
| 🔴 High | **Create prompt agent in Foundry** | Run `uv run scripts/create_agent.py -g rg-iq-lab-dev` or `register-agent.ps1` |
| 🔴 High | **Test agent E2E** | Invoke via AI Foundry playground at https://ai.azure.com |
| 🟡 Medium | **Private networking** | Set `networkMode=private` in params, redeploy — tests VNet integration |
| 🟡 Medium | **CI/CD pipeline** | `.github/workflows/` exist — configure secrets and enable |
| 🟢 Low | **Load testing** | Validate concurrency / cold-start behavior |

---

## Conventions Reminder
- **uv only** — never pip
- **ruff** for lint/format, **pyright** for type checks
- All tests via `uv run pytest`
- Bicep naming: `{type}-iq-lab-{env}` (e.g., `ca-tools-iq-lab-dev`)
