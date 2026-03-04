# Phase 6 — Feature Enhancements (Planning)

> **Status:** Planning only — no implementation started.
> These are future enhancements to explore after the core workshop is stable.

---

## A. Agent Memory (Conversation History)

Foundry Agent Service supports **memory** — persistent conversation history
across sessions so the agent can recall prior triage decisions.

### Why

- Avoid re-triaging the same ticket in every conversation
- Let the agent reference prior decisions ("Last time we restarted BGP for TKT-0042…")
- Build continuity for multi-session NOC workflows

### What to Explore

- [ ] Enable Foundry agent memory store (conversation threads persisted server-side)
- [ ] Test multi-turn memory retention with the playground
- [ ] Evaluate memory window size vs. token budget for gpt-4.1-mini
- [ ] Add eval cases for memory recall (e.g., "What did we decide for TKT-0042 last time?")
- [ ] Consider per-user vs. per-team memory scoping

### References

- [Foundry Agent Memory](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/agents-memory)
- Agent threads already provide per-conversation history; this extends to cross-conversation persistence

---

## B. Agent Knowledge (File / Index Grounding)

Foundry supports **knowledge sources** — file uploads, Azure AI Search indexes,
or Bing grounding that the agent can reference alongside tool outputs.

### Why

- Ground the agent in runbook documents, escalation procedures, SLA definitions
- Let the agent answer "What's the SLA for P1 tickets?" without a tool call
- Reduce hallucination risk for operational context that doesn't change per-query

### What to Explore

- [ ] Upload `docs/guardrails.md` and `docs/runbook.md` as knowledge files
- [ ] Create an Azure AI Search index over the IQ documentation corpus
- [ ] Test hybrid grounding: knowledge (static docs) + tools (live IQ data)
- [ ] Evaluate whether knowledge grounding improves task_adherence scores
- [ ] Add eval cases that mix knowledge questions with tool queries
- [ ] Consider vector search vs. keyword search for the doc index

### References

- [Foundry Agent Knowledge](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/agents-knowledge)
- [Azure AI Search Integration](https://learn.microsoft.com/azure/ai-foundry/agents/how-to/tools/azure-ai-search)

---

## C. Foundry Portal Evaluations

Foundry's built-in evaluation framework can score the agent using LLM-judged
evaluators in addition to our custom scorers.

### Why

- Standardised metrics visible in the Foundry portal
- LLM-judged evaluators (coherence, groundedness, task adherence) complement our rule-based scorers
- Enables comparison across agent versions in the portal dashboard

### What to Explore

- [x] Create `upload_to_foundry.py` script (done — `evals/upload_to_foundry.py`)
- [ ] Run first Foundry evaluation and verify portal dashboard
- [ ] Create custom code-based evaluator for our `score_safety` logic
- [ ] Create custom prompt-based evaluator for IQ-specific triage quality
- [ ] Set up scheduled eval runs in CI (upload results on each deployment)
- [ ] Compare Foundry evaluator scores vs. local scorer outcomes

### References

- [Foundry Evaluations](https://learn.microsoft.com/azure/ai-foundry/evaluation/)
- Script: `evals/upload_to_foundry.py`

---

## D. Migrate Eval Runner to Responses API

The eval runner (`evals/run_evals.py`) uses the classic Assistants threads/runs API
(`project_client.agents.threads.create()`, `.runs.create(agent_id=...)`) while the
agent is now registered as a new-style Prompt Agent using the Responses API
(`openai_client.responses.create()` / `openai_client.conversations.create()`).

### Current State

- `chat_agent.py` — already migrated to Responses API with `agent_reference` in `extra_body`
- `run_evals.py` — still uses classic Assistants API; state-loading falls back to `agent_name`
  but the threads/runs dispatch may fail with new-style agents
- `upload_to_foundry.py` — may need the same migration

### What to Do

- [ ] Migrate `run_agent_turn()` (legacy) to use `openai_client.responses.create()` with `agent_reference`
- [ ] Migrate `run_agent_turn_mcp()` to use `openai_client.responses.create()` with MCP approval flow
- [ ] Replace `project_client.agents.threads.create()` with `openai_client.conversations.create()`
- [ ] Replace `agent_id` parameter with `agent_name` throughout
- [ ] Update `upload_to_foundry.py` if it uses the same threads/runs API
- [ ] Test all 12 eval cases end-to-end
- [ ] Update `evals/README.md` metadata example

---

## E. Bump Python Base Image

Dependabot PR #4 suggests bumping `python:3.12-slim` → `python:3.14-slim` in the
Dockerfile. This is low-risk but requires testing.

- [ ] Verify all dependencies build on Python 3.14
- [ ] Test ODBC driver compatibility with Debian trixie (3.14-slim base)
- [ ] Run full test suite against 3.14-based container
- [ ] Update `Dockerfile` and rebuild

---

## F. Private Networking Mode

The infrastructure supports `networkMode=private` but it hasn't been exercised
end-to-end yet.

- [ ] Deploy with `parameters.private.json`
- [ ] Verify VNet integration, private endpoints, AMPLS for App Insights
- [ ] Test MCP connectivity over private endpoint
- [ ] Run full 8/8 smoke test (`smoke-test.ps1`) from inside the VNet (Cloud Shell / jumpbox)
- [ ] Verify `seed-database.ps1 -GrantPermissions` works via private endpoint (no firewall rule needed)
- [ ] Confirm Foundry Agent → MCP over private endpoint (agent registration with internal FQDN)
- [ ] Document private mode setup in Lab 0

---

## G. Local Development Smoke Test

The `smoke-test.ps1` targets the Azure deployment. A local equivalent confirming
`docker compose up` works end-to-end hasn't been validated with the full 8/8 test suite.

- [ ] Run `smoke-test.ps1 -BaseUrl http://localhost:8000` against `docker compose up`
- [ ] Verify health returns `db: connected` (local SQL container + SA password auth)
- [ ] Verify all DB-dependent endpoints (query, approval, execute) work over local SQL
- [ ] Verify MCP endpoint (`POST /mcp`) responds with tool list over localhost
- [ ] Add local smoke test step to Lab 0 "Local Development Track"
- [ ] Consider adding `docker compose up` health-wait before running smoke test in CI

---

## H. Teams Integration (Real Webhook)

The `post_teams_summary` tool currently uses a stub. Replace with a real
Teams webhook or Graph API integration.

- [ ] Create an Incoming Webhook in a Teams channel
- [ ] Replace stub in `db.py` / `mcp_server.py` with real HTTP POST
- [ ] Add Adaptive Card formatting for triage summaries
- [ ] Update Lab 4 with real webhook setup instructions
