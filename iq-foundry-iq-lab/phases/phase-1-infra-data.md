# Phase 1 — Infrastructure + Data Foundation

**Goal:** Deployable Azure infrastructure (dual-mode networking) + populated database + local Docker dev environment.

## Checklist

### Infrastructure (Bicep)
- [x] `infra/bicep/main.bicep` — Azure SQL Server + database (AAD-only auth)
- [x] `infra/bicep/main.bicep` — Log Analytics Workspace + Application Insights (linked)
- [x] `infra/bicep/main.bicep` — Container Apps Environment + Container App (port 8000, placeholder image)
- [x] `infra/bicep/main.bicep` — Two User-Assigned Managed Identities (`id-iq-agent`, `id-iq-tools`)
- [x] `infra/bicep/main.bicep` — ACR for container image hosting
- [x] `infra/bicep/main.bicep` — `networkMode` conditional: VNet, subnets, private endpoints, DNS zones (when `private`)
- [x] `infra/bicep/main.bicep` — `networkMode` conditional: public access + firewall rules (when `public`)
- [x] `infra/bicep/main.bicep` — AMPLS for App Insights (when `private`)
- [x] `infra/bicep/main.bicep` — Outputs: tool service URL, App Insights connection string, SQL FQDN, MI principal IDs
- [x] `infra/bicep/parameters.dev.json` — public mode defaults, TODO placeholders
- [x] `infra/bicep/parameters.private.json` — private mode overrides, VNet address space

### Data Layer
- [x] `data/schema.sql` — 4 tables: `iq_devices`, `iq_anomalies`, `iq_tickets`, `iq_remediation_log` with PKs, FKs, indexes
- [x] `data/seed.sql` — 30 devices, 80 anomalies, 50 tickets, 3 remediation log entries
- [x] `data/grant-permissions.sql` — MI role grants (run post-deploy as Entra admin)
- [x] `data/generator/generate_seed.py` — CLI seed generator with `--devices`, `--anomalies`, `--tickets` flags

### Local Dev
- [x] `docker-compose.yml` — SQL Server 2022 Developer + FastAPI service
- [x] `.env.example` — all env vars documented
- [x] `data/local-init.sh` — auto-run schema + seed on SQL container startup

## Acceptance Criteria
- `az deployment group create --what-if` validates with both `parameters.dev.json` and `parameters.private.json`
- `schema.sql` runs clean against Azure SQL and local SQL Server container
- `seed.sql` populates all four tables with no FK violations
- `docker compose up` starts SQL + seeds data in under 60 seconds
- `grant-permissions.sql` documents are clear and executable post-deploy
- Generator produces valid SQL matching the schema

## Dependencies
- None (this is the first phase)
