# Lab 4 — Optional Teams Publish

> **Estimated time:** 10 minutes
>
> **Objective:** Post a triage/remediation summary to Microsoft Teams (or validate
> the stub behavior when no webhook is configured).
>
> **Prerequisites:** Labs 0–3 complete

## Steps

### Part A: Without Webhook (Stub Validation)

#### Step 1: Verify no webhook is configured

Check that `TEAMS_WEBHOOK_URL` is **not** set (or is empty):

```bash
# Local:
grep TEAMS_WEBHOOK_URL .env
# Should be empty or commented out

# Azure:
az containerapp show --name <app> -g <rg> --query "properties.template.containers[0].env[?name=='TEAMS_WEBHOOK_URL']"
```

#### Step 2: Ask the agent to post to Teams

In the Foundry playground:
```
Post a summary of the TKT-0042 remediation to Teams
```

**What to observe:**
- The agent calls `postTeamsSummary` with the ticket details
- The trace shows the tool was invoked successfully

#### Step 3: Check the response

**Expected response:**
```json
{
  "teams_posted": false,
  "logged": true,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

- `teams_posted: false` — no webhook configured, so nothing was sent
- `logged: true` — the payload was logged for audit

#### Step 4: Verify in Application Insights

```kql
traces
| where message contains "post-teams-summary"
| project timestamp, message, customDimensions
| order by timestamp desc
| take 5
```

Confirm the payload was logged even without a Teams webhook.

---

### Part B: With Webhook (Optional Real Post)

> Only do this section if you have a Microsoft Teams channel for testing.

#### Step 5: Create an Incoming Webhook

1. In Microsoft Teams, go to the target channel
2. Click **...** → **Connectors** (or **Manage channel** → **Connectors**)
3. Find **Incoming Webhook** and click **Configure**
4. Name it "IQ Lab Agent" and copy the webhook URL

#### Step 6: Set the webhook URL

```bash
# Local:
echo 'TEAMS_WEBHOOK_URL=https://your-org.webhook.office.com/...' >> .env
docker compose restart api-tools

# Azure:
az containerapp update --name <app> -g <rg> \
  --set-env-vars "TEAMS_WEBHOOK_URL=https://your-org.webhook.office.com/..."
```

#### Step 7: Post via the agent

In the playground:
```
Post a summary of the TKT-0042 remediation to Teams
```

#### Step 8: Verify in Teams

**Expected Teams message:**
```
**Remediation Summary**

- **Ticket:** TKT-0042
- **Action:** Escalate to Investigate
- **Approved by:** operator@contoso.com
- **Summary:** Jitter resolved after status escalation
- **Correlation:** 550e8400-e29b-41d4-a716-446655440000
```

#### Step 9: Verify API response

```json
{
  "teams_posted": true,
  "logged": true,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Step 10: Trace end-to-end

The `correlation_id` in the Teams message traces back through:
1. Application Insights logs (all tool calls in this session)
2. `iq_remediation_log` database entry
3. The Teams channel message itself

## Checkpoints

- [ ] Stub works without webhook: payload logged, `teams_posted: false`
- [ ] (Optional) Real webhook: message appears in Teams
- [ ] (Optional) Teams message contains full traceability info
- [ ] `correlation_id` links Teams post back to App Insights logs

## Expected Output

**Stub mode response:**
```json
{"teams_posted": false, "logged": true, "correlation_id": "550e8400-..."}
```

**Real webhook Teams payload:**
```json
{
  "text": "**Remediation Summary**\n\n- **Ticket:** TKT-0042\n- **Action:** Escalate to Investigate\n- **Approved by:** operator@contoso.com\n- **Summary:** Jitter resolved\n- **Correlation:** 550e8400-..."
}
```

## What You Proved

- Graceful degradation (stub works without configuration)
- Full traceability (correlation_id from triage through Teams post)
- Optional integration (Teams is additive, not required)

---

## Verify with Unit Tests

The following tests validate Teams stub behavior and webhook posting at the API layer:

```bash
cd services/api-tools
uv run pytest -v tests/test_endpoints.py::test_teams_summary_stub_no_webhook \
  tests/test_edge_cases.py::test_teams_summary_with_webhook_success \
  tests/test_validation.py::test_teams_summary_missing_fields \
  tests/test_validation.py::test_teams_summary_empty_body
```

| Test | Lab step | What it checks |
|---|---|---|
| `test_teams_summary_stub_no_webhook` | Part A: Steps 2–3 | No `TEAMS_WEBHOOK_URL` → `teams_posted: false`, `logged: true` |
| `test_teams_summary_with_webhook_success` | Part B: Steps 7–9 | With webhook URL + successful POST → `teams_posted: true` |
| `test_teams_summary_missing_fields` | — | Missing required fields → 422 |
| `test_teams_summary_empty_body` | — | Empty `{}` → 422 |

### How the stub test works

`test_teams_summary_stub_no_webhook` patches `os.environ` to set `TEAMS_WEBHOOK_URL` to
an empty string, then POSTs a valid summary payload. It verifies the response contains
`teams_posted: false` (nothing sent) and `logged: true` (payload recorded for audit).

### How the webhook test works

`test_teams_summary_with_webhook_success` patches both `os.environ` (with a fake webhook URL)
and `httpx.AsyncClient` (to simulate a successful HTTP POST). It verifies that when the
webhook is configured and the POST succeeds, the response returns `teams_posted: true`.
