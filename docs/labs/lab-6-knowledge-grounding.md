# Lab 6 — Knowledge Grounding with Device Manuals

> **Goal:** Upload device operations manuals as Foundry knowledge sources,
> test hybrid grounding (structured data from tools + unstructured knowledge
> from vector search), and observe how the agent cites manual-specific
> thresholds, CLI commands, and remediation steps in triage summaries.
>
> **Estimated time:** 20 min

## Prerequisites

| Requirement | Check |
|---|---|
| Agent registered | `cat .agent-state.json` shows `agent_name` |
| Tool service running | `curl https://<your-ca-fqdn>/health` returns `{"db":"connected"}` |
| Azure CLI signed in | `az account show` succeeds |
| `uv` installed | `uv --version` ≥ 0.5 |
| Labs 1–5 completed | Familiar with triage, approval, and eval workflows |

> **Tip:** If you haven't deployed yet, complete [Lab 0](lab-0-environment-setup.md) first,
> then run `.\scripts\register-agent.ps1` to register the agent.

---

## Background — What Is Knowledge Grounding?

The IQ agent already grounds responses in **structured data** returned by MCP tools
(ticket fields, anomaly metrics, device attributes). Knowledge grounding adds a second
source: **unstructured documents** (device operations manuals) indexed in a Foundry
vector store and retrieved via `file_search`.

This gives the agent access to vendor-specific information it cannot get from the
database — thresholds, CLI commands, escalation procedures, and SLA references.

```
┌───────────────────────────────────────────────────────┐
│                    Foundry Agent                      │
│                                                       │
│   MCP Tools (structured)      file_search (knowledge) │
│   ┌──────────────────┐        ┌─────────────────────┐ │
│   │ query_ticket_ctx │        │ Device manuals      │ │
│   │ request_approval │        │ Guardrails doc      │ │
│   │ execute_remed.   │        │ Runbook             │ │
│   └────────┬─────────┘        └────────┬────────────┘ │
│            │                           │              │
│            ▼                           ▼              │
│   ticket/anomaly/device       thresholds, CLI cmds,  │
│   fields from Azure SQL       remediation procedures  │
│            │                           │              │
│            └───────────┬───────────────┘              │
│                        ▼                              │
│              Grounded triage summary                  │
│       (cites both data fields AND manual guidance)    │
└───────────────────────────────────────────────────────┘
```

### Available Device Manuals

| Manual | Model | Vendor | CLI / OS |
|---|---|---|---|
| `cisco-asr-9000.md` | Cisco ASR-9000 | Cisco | IOS-XR |
| `cisco-catalyst-9300.md` | Cisco Catalyst 9300 | Cisco | IOS-XE |
| `juniper-mx960.md` | Juniper MX960 | Juniper | Junos |
| `juniper-qfx5120.md` | Juniper QFX5120 | Juniper | Junos |
| `arista-7280r3.md` | Arista 7280R3 | Arista | EOS |
| `nokia-7750-sr.md` | Nokia 7750 SR | Nokia | SR OS |
| `ciena-6500.md` | Ciena 6500 | Ciena | SAOS |

Each manual covers 6 signal types (jitter spike, packet loss, latency spike,
throughput drop, link flap, BGP instability) with thresholds, diagnostic CLI
commands, step-by-step remediation, and escalation criteria.

---

## Part 1 — Explore the Device Manuals

Before uploading, review what the manuals contain so you know what to expect
from the agent.

Open a manual and examine its structure:

```powershell
# View the Cisco ASR-9000 manual
code data/manuals/cisco-asr-9000.md
```

**Key sections to note:**

- **Thresholds table** — Warning and Critical levels for each signal type
- **Diagnostic CLI commands** — Vendor-specific commands to investigate the anomaly
- **Remediation steps** — Ordered actions, citing specific CLI syntax
- **Escalation criteria** — When to involve vendor TAC or network architecture team
- **Allowlisted actions** — Actions the agent is permitted to propose

**Question to consider:** When the agent triages a jitter spike on a Cisco ASR-9000,
what specific CLI command should it recommend? (Hint: check the jitter spike section.)

### Checkpoint 1

- [ ] Opened at least one manual and identified the threshold tables
- [ ] Found vendor-specific CLI commands for at least two signal types
- [ ] Understand the difference between Warning and Critical thresholds

---

## Part 2 — Register the Agent with Knowledge Sources

The `create_agent.py` script needs to be extended to upload manuals and create
a vector store. The `agent.yaml` already defines the knowledge configuration:

```yaml
knowledge:
  vector_store_label: iq-device-manuals
  files:
    - path: data/manuals/cisco-asr-9000.md
    - path: data/manuals/cisco-catalyst-9300.md
    - path: data/manuals/juniper-mx960.md
    # ... (7 manuals + 2 operational docs)
```

### Step 1: Review the Knowledge Configuration

```powershell
# See the full knowledge section
Select-String -Path foundry/agent.yaml -Pattern "knowledge:" -Context 0,25
```

### Step 2: Register the Agent with Knowledge

> **Note:** As of the current SDK (azure-ai-projects 2.0.0b2+), `FileSearchTool`
> and vector store creation require manual SDK calls. The `create_agent.py` script
> includes the registration logic for MCP tools. Knowledge upload is an additional
> step you'll add.

To enable knowledge grounding, the registration flow is:

1. **Upload files** — `project_client.agents.files.upload(file_path=...)`
2. **Create vector store** — `project_client.agents.vector_stores.create(file_ids=[...])`
3. **Attach to agent** — add `FileSearchTool(vector_store_ids=[vs_id])` to the tools list

```python
# Conceptual code — adding FileSearchTool to the agent
from azure.ai.projects.models import FileSearchTool

# After uploading files and creating a vector store:
file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])

# Include alongside the MCP tool when creating the agent:
tools = [mcp_tool, file_search_tool]
```

### Step 3: Verify Knowledge Registration

After registration, check that the agent has both tool types configured:

```powershell
# Check agent state
Get-Content .agent-state.json | ConvertFrom-Json | Format-List
```

The agent should have access to both MCP tools (for structured data) and
file_search (for knowledge retrieval).

### Checkpoint 2

- [ ] Reviewed the knowledge section in `agent.yaml`
- [ ] Understand the 3-step flow: upload → vector store → attach
- [ ] Agent state shows both MCP and knowledge capabilities

---

## Part 3 — Test Knowledge-Only Queries

These prompts test whether the agent can answer questions purely from the
device manuals, without needing to call MCP tools.

### Test 1: Threshold Lookup

```
What is the critical jitter threshold for a Cisco ASR-9000?
```

**Expected behavior:**
- Agent uses `file_search` to find the ASR-9000 manual
- Response cites the threshold: **100 ms** (Critical)
- No MCP tool calls needed — this is pure knowledge grounding

### Test 2: CLI Command Lookup

```
What CLI command would I use to check BGP neighbor status on a Juniper MX960?
```

**Expected behavior:**
- Agent retrieves the Juniper MX960 manual
- Response includes the Junos command: `show bgp neighbor`
- Agent cites the manual as the source

### Test 3: Escalation Criteria

```
When should I escalate a link flap issue on a Nokia 7750 SR to the vendor?
```

**Expected behavior:**
- Agent finds the Nokia 7750 SR manual's link flap / escalation section
- Response includes specific escalation criteria from the manual
- May mention TAC engagement or threshold conditions

### Test 4: Cross-Model Comparison

```
Compare the packet loss warning thresholds across Cisco ASR-9000 and Arista 7280R3.
```

**Expected behavior:**
- Agent searches both manuals
- Response cites both threshold values with model attribution

### Checkpoint 3

- [ ] Agent answers threshold questions using manual data
- [ ] Agent provides vendor-specific CLI commands
- [ ] Agent cites the manual (e.g., "per the Cisco ASR-9000 operations manual")
- [ ] Agent does NOT fabricate values when the manual has the data

---

## Part 4 — Test Hybrid Grounding (Tools + Knowledge)

The most powerful use of knowledge grounding is **hybrid mode** — combining
structured data from MCP tools with unstructured guidance from device manuals.

### Test 5: Triage with Manual Context

```
Summarize ticket TKT-0042 and include the recommended diagnostic commands from the device manual.
```

**Expected behavior:**
- Agent calls `query_ticket_context` for TKT-0042 (structured data)
- Agent uses `file_search` to find the relevant device manual (knowledge)
- Summary includes:
  - Ticket fields (severity, signal_type, metrics) from the tool
  - CLI commands and thresholds from the device manual
  - Threshold comparison: is the metric above Warning? Critical?
- Up to 6 bullets covering both data sources

### Test 6: Remediation with Manual Guidance

```
What remediation steps does the operations manual recommend for the anomaly in TKT-0015?
```

**Expected behavior:**
- Agent queries TKT-0015 to learn the signal type and device model
- Agent searches the relevant device manual for remediation procedures
- Response includes ordered remediation steps from the manual
- Agent cites both the ticket data AND the manual

### Test 7: Manual-Informed Approval Request

```
Propose a remediation for TKT-0042 using the guidance from the device operations manual.
```

**Expected behavior:**
- Agent queries TKT-0042, retrieves device model and signal type
- Agent consults the manual for recommended actions
- Remediation proposal cites manual-recommended steps
- Agent calls `request_approval` with a rationale grounded in both sources

### Checkpoint 4

- [ ] Triage summaries cite both tool output AND manual data
- [ ] Agent includes device-specific CLI commands in summaries
- [ ] Agent compares actual metrics against manual thresholds
- [ ] Remediation proposals reference manual procedures

---

## Part 5 — Compare Responses With and Without Knowledge

To appreciate the impact of knowledge grounding, compare the agent's responses
when manuals are available versus when they are not.

### Without Knowledge (Baseline)

Register a temporary agent **without** `FileSearchTool`:

```powershell
# Register agent without knowledge (MCP tools only)
uv run scripts/create_agent.py --resource-group rg-iq-lab-dev
```

Then ask:

```
Summarize ticket TKT-0042 and recommend diagnostic CLI commands.
```

Note the response — the agent can triage from structured data but will likely
give generic CLI suggestions (or say "not available") since it has no manual access.

### With Knowledge (Enhanced)

Re-register with knowledge sources attached (per Part 2), then ask the same prompt.

**What changes:**

| Aspect | Without Knowledge | With Knowledge |
|---|---|---|
| Threshold comparison | ❌ Cannot compare | ✅ "jitter 142ms exceeds Critical (100ms)" |
| CLI commands | ❌ Generic or absent | ✅ Vendor-specific (e.g., `show monitor interface`) |
| Remediation steps | ❌ Generic suggestions | ✅ Ordered steps from manual |
| Manual citations | ❌ None | ✅ "per Cisco ASR-9000 operations manual" |
| Escalation criteria | ❌ Not available | ✅ Specific escalation triggers |

### Checkpoint 5

- [ ] Observed the difference in triage quality with and without knowledge
- [ ] Knowledge-grounded responses include specific thresholds and CLI commands
- [ ] Responses cite the device manual by name

---

## Part 6 — Add a Knowledge Evaluation Case

Extend the eval suite to test knowledge grounding. Open `evals/dataset.json`
and add a new case:

```json
{
  "id": "knowledge-threshold-001",
  "category": "grounding",
  "description": "Agent should cite device manual thresholds when triaging",
  "prompt": "Summarize ticket TKT-0042 and compare the metrics against the device manual thresholds.",
  "expected_tools": ["query_ticket_context"],
  "assertions": {
    "must_contain": ["TKT-0042"],
    "must_contain_any": ["threshold", "manual", "operations manual", "warning", "critical"],
    "requires_tool_call": true,
    "requires_grounding": true,
    "max_bullets": 6
  }
}
```

Run the new case:

```powershell
uv run evals/run_evals.py -g rg-iq-lab-dev --case knowledge-threshold-001 -v
```

**Expected output:**
- The agent calls `query_ticket_context` for TKT-0042
- The agent uses `file_search` to retrieve the relevant device manual
- Response mentions thresholds or manual references
- All grounding assertions pass

### Stretch: Add More Knowledge Cases

Consider adding cases for:

| Case ID | Tests | Prompt |
|---|---|---|
| `knowledge-cli-001` | CLI command from manual | "What command checks BGP on the device for TKT-0015?" |
| `knowledge-escalation-001` | Escalation criteria | "Should I escalate the issue in TKT-0042?" |
| `knowledge-cross-model-001` | Multi-manual retrieval | "Compare thresholds for TKT-0042's device vs Arista 7280R3" |

### Checkpoint 6

- [ ] Added at least one knowledge eval case to `dataset.json`
- [ ] Case passes when run against the knowledge-enabled agent
- [ ] Response contains manual-specific content (thresholds, CLI, or procedures)

---

## Part 7 — Regenerate Manuals (Optional)

If you modify the seed data (add device models, change signal types), regenerate
the manuals to keep them in sync:

```powershell
# Regenerate all device manuals
uv run data/manuals/generate_manuals.py
```

The generator reads from a `MODELS` dictionary that matches `DEVICE_MODELS` in
`data/generator/generate_seed.py`. If you add a new device model:

1. Add the model to `DEVICE_MODELS` in `data/generator/generate_seed.py`
2. Add matching entry to `MODELS` in `data/manuals/generate_manuals.py`
3. Run `uv run data/manuals/generate_manuals.py`
4. Add the new file to `foundry/agent.yaml` → `knowledge.files`
5. Re-register the agent to upload the new manual

### Checkpoint 7

- [ ] Understand how manuals are generated from the `MODELS` dictionary
- [ ] Know which files to update when adding a new device model
- [ ] (Optional) Successfully regenerated manuals after a test change

---

## Summary

| Skill | What you practiced |
|---|---|
| Knowledge exploration | Reviewing device manual structure and content |
| Agent registration | Attaching vector store knowledge to a Foundry agent |
| Knowledge-only queries | Testing agent responses from manuals alone |
| Hybrid grounding | Combining MCP tool data with manual knowledge |
| Before/after comparison | Observing triage quality improvement with knowledge |
| Eval extension | Adding knowledge-aware test cases to the eval suite |
| Manual regeneration | Keeping knowledge sources in sync with seed data |

---

## Cross-References

| Related Lab | Connection |
|---|---|
| [Lab 1](lab-1-safe-tool-invocation.md) | MCP tool calls (structured data source) |
| [Lab 2](lab-2-structured-data-grounding.md) | Field-level data grounding (complements knowledge grounding) |
| [Lab 3](lab-3-governance-safety.md) | Approval workflow still applies with knowledge-enhanced proposals |
| [Lab 5](lab-5-agent-evaluation.md) | Eval framework used to test knowledge grounding quality |

---

## What's Next

With knowledge grounding in place, the agent now has access to both structured
data (via MCP tools) and unstructured guidance (via device manuals). Future
enhancements (Phase 6) include:

- **Agent memory** — persistent context across sessions
- **Foundry portal evaluations** — LLM-judged scoring of knowledge-grounded responses
- **Additional knowledge sources** — vendor release notes, network topology docs
