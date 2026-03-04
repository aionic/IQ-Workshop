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

### Cognitive Services soft-delete blocks redeployment

**Symptom:** Bicep deployment fails with `FlagMustBeSetForRestore` — "An existing resource
has been soft-deleted. To restore the resource, you must specify 'restore' to be 'true'."

**Cause:** Azure soft-deletes Cognitive Services accounts for 48 hours after resource group
deletion. Re-deploying the same Bicep template within that window sees the
soft-deleted resource and refuses to create a new one.

**Solutions:**
- **Automated (recommended):** Re-run `.\scripts\deploy.ps1` — it automatically detects
  soft-deleted accounts matching the resource group and prompts you to purge them
- **Manual purge:**
  ```powershell
  # List soft-deleted accounts
  az cognitiveservices account list-deleted --output table
  # Purge a specific account
  az cognitiveservices account purge --name ai-iq-lab-dev --resource-group rg-iq-lab-dev --location westus3
  ```
- **Wait it out:** Soft-deleted accounts are auto-purged after 48 hours
- See: https://learn.microsoft.com/azure/ai-services/recover-purge-resources

### SQL firewall blocks seeding from local machine

**Symptom:** `Invoke-Sqlcmd` fails with "Client with IP address X.X.X.X is not allowed
to access the server" when running `seed-database.ps1`.

**Cause:** Azure SQL Server firewall doesn't include your current public IP.

**Solutions:**
- **Automated (recommended):** Use `.\scripts\deploy.ps1 -SeedDatabase` or
  `.\scripts\seed-database.ps1` — both auto-detect your public IP, create a temporary
  firewall rule, and clean it up after seeding completes
- **Manual:** Add your IP in Azure Portal → SQL Server → Networking → Firewall rules
- **Using `az` CLI:**
  ```powershell
  $ip = (Invoke-RestMethod https://api.ipify.org).Trim()
  az sql server firewall-rule create -g rg-iq-lab-dev -s sql-iq-lab-dev -n my-ip --start-ip-address $ip --end-ip-address $ip
  ```

### SQL connectivity from Container App

**Symptom:** Tool service returns 503 / "Database unavailable" on all DB endpoints.

**Solutions:**
- **Public mode:** Verify the Container App's outbound IPs are in the SQL Server firewall rules (Bicep creates these automatically)
- **Private mode:** Confirm private endpoint is created and DNS resolves: `nslookup <server>.database.windows.net` should return a private IP (10.x.x.x)
- Check the Container App env vars: `AZURE_SQL_SERVER_FQDN`, `DB_NAME`, `DB_AUTH_MODE=token`
- Verify the managed identity `id-iq-tools-iq-lab-dev` has been created as a user in Azure SQL (run `grant-permissions.sql` as Entra admin)

### Token auth fails (Managed Identity)

**Symptom:** `azure.identity.CredentialUnavailableError` or "Login failed for user '<token-identified principal>'"

**Solutions:**
- Confirm `AZURE_CLIENT_ID` env var is set on the Container App to the `id-iq-tools-iq-lab-dev` managed identity client ID
- Verify the Entra user was created in Azure SQL:
  ```sql
  CREATE USER [id-iq-tools-iq-lab-dev] FROM EXTERNAL PROVIDER;
  ```
- Check the token scope is correct: `https://database.windows.net/.default`
- If using `DefaultAzureCredential` locally, ensure you're logged in: `az login`
- Tokens are cached for 5 minutes; after granting permissions, wait or restart the service

### Cannot connect to SQL from local machine

**Symptom:** Cannot run SQL scripts against the Azure SQL database.

**Solutions:**
- **Automated:** `seed-database.ps1` and `deploy.ps1 -SeedDatabase` auto-create a temporary SQL firewall rule for your IP (and remove it after). Just re-run the script.
- **Public mode:** Add your IP to the SQL Server firewall (Azure Portal → SQL Server → Networking), or use the `az sql server firewall-rule create` command shown above
- **Private mode:** You must connect from inside the VNet — use Azure Cloud Shell, a jumpbox VM, or VPN
- Use Azure Data Studio or `sqlcmd` with Entra auth: `sqlcmd -S <server>.database.windows.net -d sqldb-iq --authentication-method=ActiveDirectoryDefault`

### ACR push fails

**Symptom:** `docker push` fails with authentication or network error.

**Solutions:**
- **Public mode:** `az acr login --name <acr-name>` then `docker push`
- **Private mode:** Use `az acr build` from Azure Cloud Shell (builds directly in ACR, no local push needed):
  ```bash
  az acr build --registry <acr-name> --image iq-tools:latest --platform linux/amd64 -f services/api-tools/Dockerfile services/api-tools/
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

## MCP Server Issues

### 421 "Misdirected Request" or "Invalid Host header"

**Symptom:** Foundry Agent Service reports "Error retrieving tool list from MCP server" with HTTP 421.

**Root cause #1 — Trailing slash redirect:**
Starlette's `Mount("/mcp", ...)` issues a 307 redirect from `/mcp` → `/mcp/`. The `Location` header uses `http://` (not `https://`) because Container Apps terminates TLS at the load balancer. Foundry doesn't follow redirects, and the HTTP scheme causes a protocol mismatch.

**Fix:** The middleware `_rewrite_mcp_trailing_slash` in `app/main.py` rewrites `/mcp` → `/mcp/` internally before the Mount handler. This is already applied.

**Root cause #2 — MCP transport security DNS rebinding protection:**
MCP library ≥1.26.0 added `TransportSecurityMiddleware` (`mcp/server/transport_security.py`) that validates the `Host` header against an `allowed_hosts` list. When running behind a reverse proxy (Container Apps), the external FQDN isn't in the default list, so every request is rejected with 421.

**Fix:** Pass `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to the `FastMCP()` constructor in `app/mcp_server.py`. This is already applied.

**Solutions if it reoccurs:**
- Verify the image is `v3` or later: `az containerapp show -n ca-tools-iq-lab-dev -g rg-iq-lab-dev --query "properties.template.containers[0].image"`
- Check MCP library version in the container: should be `mcp>=1.26.0` in `requirements.txt`
- Test directly: `curl -s -X POST https://<fqdn>/mcp/ -H "Content-Type: application/json" -H "Accept: application/json" -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'`
- Expected: HTTP 200 with JSON-RPC response containing `serverInfo.name: "IQ Tool Service"`

### 406 "Not Acceptable" from MCP endpoint

**Symptom:** `POST /mcp/` returns 406 with `"Client must accept application/json"`.

**Cause:** The MCP server is configured with `json_response=True`, which requires clients to send `Accept: application/json`.

**Fix:** This is expected behavior — Foundry Agent Service sends the correct header. If testing with curl, add `-H "Accept: application/json"`.

### MCP tools not discovered by agent

**Symptom:** Agent loads but reports "no tools available" or doesn't call any tools.

**Solutions:**
- Verify the MCP URL in agent registration matches the deployed endpoint: `https://<fqdn>/mcp`
- Test tool listing: `curl -s -X POST https://<fqdn>/mcp/ -H "Content-Type: application/json" -H "Accept: application/json" -d '{"jsonrpc":"2.0","method":"tools/list","id":2,"params":{}}'`
- Should return 4 tools: `query_ticket_context`, `request_approval`, `execute_remediation`, `post_teams_summary`
- Check `.agent-state.json` has `mcp_server_url` pointing to the correct FQDN
- If the agent was registered with the wrong MCP URL, re-run `uv run scripts/create_agent.py`

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

## Unit Test Issues

### Common test failures

**Symptom:** `uv run pytest` fails on one or more tests.

**Solutions:**
- Ensure you're in the correct directory: `cd services/api-tools`
- Install dev dependencies: `uv sync --extra dev`
- All 56 tests mock the DB layer — no database connection needed
- If import errors occur, verify `tests/conftest.py` exists (it adds the parent directory to `sys.path`)

### Specific test troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` | Not in `services/api-tools/` | `cd services/api-tools` then retry |
| `pytest-asyncio` fixture error | Wrong fixture decorator | Use `@pytest_asyncio.fixture` for async fixtures |
| `ASGITransport` import error | Old httpx version | `uv sync --extra dev` to update httpx |
| 8 `test_openapi_spec` failures | `tools.openapi.json` schema mismatch | Regenerate spec from running app: `curl http://localhost:8000/openapi.json > foundry/tools.openapi.json` then update by hand |

### Running tests against a live database

By default, tests mock the DB layer. To run against a local SQL container:

```bash
# Start database
docker compose up -d sqlserver
# Wait ~20 seconds for SQL to start

# Run with live DB
TEST_USE_DB=true uv run pytest -v
```

## Agent Evaluation Issues

### Eval runner fails to start

**Symptom:** `uv run evals/run_evals.py` fails immediately.

**Solutions:**
- The eval runner uses PEP 723 inline dependencies — `uv run` installs them automatically
- Ensure `uv` is installed: `uv --version` (need ≥ 0.5)
- Verify Azure CLI is signed in: `az account show`
- Check `.agent-state.json` exists with a valid `agent_id` (run `uv run scripts/create_agent.py` first)

### Eval cases fail due to LLM non-determinism

**Symptom:** A case passes sometimes but fails other times with the same prompt.

**Understanding:** LLM responses are inherently non-deterministic. A passing score of
**10–12 out of 12** is normal. Common non-deterministic failures include:

| Case | Common failure mode | Why |
|---|---|---|
| `safety-refusal-001` | Agent rephrases refusal differently | LLM may say "I'm unable to" vs "I cannot" — both valid |
| `safety-hallucination-001` | Agent mentions owner email from tool data | Owner field has an email; agent may cite it when asked about "email" |
| `grounding-format-001` | Agent uses 4 bullets instead of 3 | LLM may add context the scorer counts as an extra bullet |

**Solutions:**
- Run individual failures with `-v` to see exactly what the agent said:
  ```bash
  uv run evals/run_evals.py -g rg-iq-lab-dev --case <case-id> -v
  ```
- If the response is reasonable but fails assertions, widen the assertions in `dataset.json`:
  - `must_contain_any`: add more synonyms
  - `must_not_contain`: remove overly strict terms
- Run the failing case 3 times — if it passes at least once, it's non-determinism

### Tool service unreachable during eval

**Symptom:** Eval cases fail with connection errors or timeouts.

**Solutions:**
- Verify the tool service is running: `curl https://<your-ca-fqdn>/health`
- The eval runner reads the Container App FQDN from Bicep outputs — ensure the deployment is current
- If running locally, the eval runner talks to the Azure-deployed tool service, not localhost
- Check that the Container App has at least 1 active replica:
  ```bash
  az containerapp show -n ca-tools-iq-lab-dev -g rg-iq-lab-dev --query "properties.runningStatus"
  ```

### Understanding eval results

Results are saved to `evals/results/eval-<timestamp>.json`. Key fields:

| Field | Meaning |
|---|---|
| `summary.aggregate_score` | Weighted pass rate (0.0–1.0). Target: ≥ 0.90 |
| `results[].scores[].scorer` | Which scorer evaluated this case |
| `results[].scores[].passed` | Whether this specific check passed |
| `results[].scores[].detail` | Human-readable explanation of pass/fail |
| `results[].tool_calls` | Exact tool calls the agent made (function name + arguments) |

### Adding new eval cases

If you add a case to `dataset.json` and it fails:

1. Run with `-v` to see the agent's actual response
2. Check that `expected_tools` matches what the agent actually calls (snake_case names)
3. Check that `must_contain` terms actually appear in the response (case-insensitive)
4. Verify the assertion types are correct:
   - `must_contain`: ALL terms must appear
   - `must_contain_any`: at least ONE must appear
   - `must_not_contain`: NONE may appear
