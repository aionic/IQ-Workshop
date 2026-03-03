# Troubleshooting — IQ Foundry Agent Lab

## Local Development Issues

### Docker Compose fails to start

**Symptom:** `docker compose up` exits or SQL Server container restarts in a loop.

**Solutions:**
- Ensure Docker Desktop is running with at least **2 GB RAM** allocated to containers
- SQL Server 2022 requires `ACCEPT_EULA=Y` and `MSSQL_SA_PASSWORD` with complexity (8+ chars, upper/lower/digit/symbol)
- Check port 1433 is not already in use: `netstat -an | findstr 1433` (Windows) or `lsof -i :1433` (macOS/Linux)
- If `local-init.sh` fails, ensure the file has LF line endings (not CRLF): `git config core.autocrlf input`
- Wait 15–20 seconds after SQL container starts before the init script runs

### Cannot connect to local SQL Server

**Symptom:** `pyodbc.OperationalError` or connection timeout when running locally.

**Solutions:**
- Verify the container is running: `docker ps | grep sqlserver`
- Ensure `.env` has `DB_AUTH_MODE=password`, `DB_HOST=localhost`, `DB_PORT=1433`, `SA_PASSWORD=<your-password>`
- Check ODBC driver is installed: `odbcinst -j` (Linux) or check "ODBC Data Sources" in Windows
- The Dockerfile installs ODBC Driver 18; locally you may need to install it separately
- If using Docker Desktop on Windows with WSL2, use `localhost` not `host.docker.internal`

### pytest fails

**Symptom:** Import errors or fixture setup failures when running `uv run pytest`.

**Solutions:**
- Ensure you're in `services/api-tools/`: `cd services/api-tools`
- Create venv and install deps: `uv venv && uv pip install -r requirements.txt`
- Check `tests/conftest.py` exists (adds parent dir to `sys.path`)
- If `pytest-asyncio` errors about "async fixture", ensure async fixtures use `@pytest_asyncio.fixture` (not `@pytest.fixture`)
- Verify `pytest.ini` or `pyproject.toml` has `asyncio_mode = "strict"` if using strict mode

## Azure Deployment Issues

### SQL connectivity from Container App

**Symptom:** Tool service returns 503 / "Database unavailable" on all DB endpoints.

**Solutions:**
- **Public mode:** Verify the Container App's outbound IPs are in the SQL Server firewall rules (Bicep creates these automatically)
- **Private mode:** Confirm private endpoint is created and DNS resolves: `nslookup <server>.database.windows.net` should return a private IP (10.x.x.x)
- Check the Container App env vars: `AZURE_SQL_SERVER_FQDN`, `DB_NAME`, `DB_AUTH_MODE=token`
- Verify the managed identity `id-iq-tools` has been created as a user in Azure SQL (run `grant-permissions.sql` as Entra admin)

### Token auth fails (Managed Identity)

**Symptom:** `azure.identity.CredentialUnavailableError` or "Login failed for user '<token-identified principal>'"

**Solutions:**
- Confirm `AZURE_CLIENT_ID` env var is set on the Container App to the `id-iq-tools` managed identity client ID
- Verify the Entra user was created in Azure SQL:
  ```sql
  CREATE USER [id-iq-tools] FROM EXTERNAL PROVIDER;
  ```
- Check the token scope is correct: `https://database.windows.net/.default`
- If using `DefaultAzureCredential` locally, ensure you're logged in: `az login`
- Tokens are cached for 5 minutes; after granting permissions, wait or restart the service

### Cannot connect to SQL from local machine

**Symptom:** Cannot run SQL scripts against the Azure SQL database.

**Solutions:**
- **Public mode:** Add your IP to the SQL Server firewall (Azure Portal → SQL Server → Networking)
- **Private mode:** You must connect from inside the VNet — use Azure Cloud Shell, a jumpbox VM, or VPN
- Use Azure Data Studio or `sqlcmd` with Entra auth: `sqlcmd -S <server>.database.windows.net -d sqldb-iq --authentication-method=ActiveDirectoryDefault`

### ACR push fails

**Symptom:** `docker push` fails with authentication or network error.

**Solutions:**
- **Public mode:** `az acr login --name <acr-name>` then `docker push`
- **Private mode:** Use `az acr build` from Azure Cloud Shell (builds directly in ACR, no local push needed):
  ```bash
  az acr build --registry <acr-name> --image iq-lab-tools:latest --platform linux/amd64 -f services/api-tools/Dockerfile services/api-tools/
  ```
- Ensure the deploying identity has `AcrPush` role on the registry

### App Insights not showing logs

**Symptom:** No traces or requests visible in Application Insights.

**Solutions:**
- Verify `APPLICATIONINSIGHTS_CONNECTION_STRING` is set on the Container App
- Check the tool service logs: `az containerapp logs show --name <app> -g <rg>`
- In private mode, confirm the AMPLS (Azure Monitor Private Link Scope) is configured and the private endpoint is healthy
- Data may take 2–5 minutes to appear; check Live Metrics for real-time confirmation
- Ensure `setup_observability()` runs at startup (check lifespan function in `main.py`)

### Container App not starting

**Symptom:** Container App revision is in "Failed" state or keeps restarting.

**Solutions:**
- Check container logs: `az containerapp logs show --name <app> -g <rg> --type system`
- **Image platform mismatch:** Build with `--platform linux/amd64` (Container Apps run AMD64)
- **ODBC driver missing:** The Dockerfile installs ODBC Driver 18; if you modified the Dockerfile, verify the install step
- **Missing env vars:** Compare required env vars in `agent.yaml` against what's configured on the Container App
- **Port mismatch:** Container App expects port 8000 (set in Bicep `targetPort: 8000`)

## Foundry Agent Issues

### Agent not finding tools

**Symptom:** Agent doesn't call any tools or says tools are unavailable.

**Solutions:**
- Verify the OpenAPI spec URL in the agent configuration points to the running tool service
- Check that `foundry/tools.openapi.json` is valid: `spectral lint foundry/tools.openapi.json`
- Ensure the tool service is reachable from the Foundry agent (check network connectivity)
- Verify all 4 tool operations are listed: `query_ticket_context`, `request_approval`, `execute_remediation`, `post_teams_summary`

### Agent produces hallucinated data

**Symptom:** Agent cites field values not present in the database.

**Solutions:**
- Verify the system prompt (`foundry/prompts/system.md`) is loaded in the agent configuration
- Check that the system prompt includes "Never speculate" and "If data is not in the query result, say 'not available'"
- Ensure tool responses contain the exact fields the agent references (check the trace view)
- If the agent references fields not in `QueryTicketContextResponse`, the grounding is broken — check schema alignment

### Approval flow not working

**Symptom:** Agent executes remediation without approval, or gets 403 on every attempt.

**Solutions:**
- Verify the agent calls `request-approval` before `execute-remediation` (check trace)
- The `approval_token` is the `remediation_id` as a string — ensure it's passed correctly
- 403 means the approval status is not `APPROVED` — check with `GET /admin/approvals`
- Admin must call `POST /admin/approvals/{id}/decide` with `{"decision": "APPROVED", ...}` between the request and execute steps
- Check system prompt instructs the agent to follow the query → approve → execute flow
