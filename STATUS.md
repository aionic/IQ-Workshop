# IQ Foundry Agent Lab — Session Status & Handoff

> **Last updated:** 2026-03-03 (Agent Framework v2 SDK + gpt-4.1-mini + evals)
> **Author:** Project Maintainer + Copilot

---

## Quick Resume Checklist

```bash
# 1. Set the right subscription
az account set --subscription <your-subscription-id>

# 2. Verify the tool service is running
curl https://<your-container-app-fqdn>/health

# 3. Check container app status
az containerapp show -n <your-container-app-name> -g <your-resource-group> --query "properties.runningStatus" -o tsv
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
| **Subscription** | `<your-subscription-name>` |
| **Subscription ID** | `<your-subscription-id>` |
| **Resource Group** | `<your-resource-group>` |
| **Region** | `<your-region>` |
| **Entra Admin OID** | `<your-entra-admin-object-id>` |

### Deployed Resources

| Resource | Name / FQDN |
|----------|-------------|
| **Container App** | `<your-container-app-name>` |
| **Tool Service URL** | `https://<your-container-app-fqdn>` |
| **CA Environment** | `<your-container-app-environment>` |
| **Current Image** | `<your-acr-login-server>/iq-tools:<tag>` |
| **Active Revision** | `<active-revision-name>` |
| **ACR** | `<your-acr-login-server>` |
| **SQL Server** | `<your-sql-server>.database.windows.net` |
| **SQL Database** | `sqldb-iq` |
| **AI Services** | `<your-ai-services-name>` (`https://<your-ai-services-name>.cognitiveservices.azure.com/`) |
| **Foundry Project** | `<your-foundry-project-name>` (standalone project under AI Services) |
| **Project Endpoint** | `https://<your-ai-services-name>.services.ai.azure.com/api/projects/<your-foundry-project-name>` |
| **Model Deployment** | `gpt-4.1-mini` (GlobalStandard, 30K TPM, version 2025-04-14) |
| **App Insights** | `<redacted>` |

### Managed Identities

| Identity | Client ID | Principal ID |
|----------|-----------|--------------|
| **id-iq-tools-iq-lab-dev** (Tool Service) | `<redacted-client-id>` | `<redacted-principal-id>` |
| **id-iq-agent-iq-lab-dev** (Agent) | `<redacted-client-id>` | `<redacted-principal-id>` |

Both MIs have `db_datareader` + `db_datawriter` roles on `sqldb-iq`.
Both MIs have `Cognitive Services OpenAI User` role on `<your-ai-services-name>`.

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
| `infra/bicep/parameters.dev.json` | Entra admin values and target region updated for deployment |
| `infra/bicep/main.bicep` | `principalType: 'Group'` → `'User'` |
| `services/api-tools/Dockerfile` | Removed `--auto-remove` from apt-get purge |
| `services/api-tools/app/db.py` | Fixed cursor.description bug in `execute_remediation()` |

---

## Turnkey Deployment Scripts

All deployment is automated via PowerShell scripts in `scripts/`. See [scripts/README.md](scripts/README.md) for the full walkthrough.

```powershell
# Full deployment from scratch (~15 min)
az login
az account set --subscription <your-subscription-id>
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

### Agent Evaluations

```bash
# Run the full eval suite
uv run evals/run_evals.py --resource-group <your-resource-group>

# Run a single case with verbose output
uv run evals/run_evals.py -g <your-resource-group> --case triage-basic-001 -v
```

| File | Purpose |
|------|---------|
| `evals/dataset.json` | 12 eval cases (triage, safety, governance, grounding) |
| `evals/scorers.py` | 5 independent scorers (tool calls, grounding, format, safety, args) |
| `evals/run_evals.py` | PEP 723 runner — sends prompts, scores responses, writes JSON report |
| `evals/results/` | Timestamped JSON reports (gitignored) |

---

## Useful Commands

### Rebuild & Redeploy the Tool Service
```powershell
# One-liner rebuild + redeploy
.\scripts\deploy.ps1 -SkipBicep -ImageTag v5

# Or manually:
az acr build --registry <your-acr-name> --image iq-tools:v5 --platform linux/amd64 .
az containerapp update -n <your-container-app-name> -g <your-resource-group> --image <your-acr-login-server>/iq-tools:v5

# Tail logs
az containerapp logs show -n <your-container-app-name> -g <your-resource-group> --follow
```

### Database Access (PowerShell — Entra token auth)
```powershell
$token = (az account get-access-token --resource https://database.windows.net --query accessToken -o tsv)
Invoke-Sqlcmd -ServerInstance "<your-sql-server>.database.windows.net" `
  -Database "sqldb-iq" -AccessToken $token `
  -Query "SELECT COUNT(*) AS n FROM iq_devices"
```

### Full Bicep Redeploy
```bash
az deployment group create \
  --resource-group <your-resource-group> \
  --template-file infra/bicep/main.bicep \
  --parameters infra/bicep/parameters.dev.json
```

---

## Potential Next Steps

| Priority | Task | Notes |
|----------|------|-------|
| 🔴 High | **Create prompt agent in Foundry** | Run `uv run scripts/create_agent.py -g <your-resource-group>` or `register-agent.ps1` |
| 🔴 High | **Test agent E2E** | Invoke via AI Foundry playground at https://ai.azure.com |
| 🟡 Medium | **Private networking** | Set `networkMode=private` in params, redeploy — tests VNet integration |
| 🟡 Medium | **CI/CD pipeline** | `.github/workflows/` exist — configure secrets and enable |
| 🟢 Low | **Load testing** | Validate concurrency / cold-start behavior |
| ✅ Done | **Agent evals** | 12-case eval suite: grounding, safety, governance, format |

---

## Conventions Reminder
- **uv only** — never pip
- **ruff** for lint/format, **pyright** for type checks
- All tests via `uv run pytest`
- Bicep naming: `{type}-iq-lab-{env}` (e.g., `ca-tools-iq-lab-dev`)
