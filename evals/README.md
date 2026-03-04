# Agent Evaluations — IQ Foundry Agent Lab

Automated evaluation suite for the IQ triage agent. Tests grounding accuracy,
tool-call correctness, safety refusals, governance compliance, knowledge grounding,
and output format.

## Quick Start

```powershell
# Run the full eval suite against a live agent
uv run evals/run_evals.py --resource-group rg-iq-lab-dev

# Run a single case
uv run evals/run_evals.py -g rg-iq-lab-dev --case triage-basic-001

# Verbose output (shows tool calls + response previews)
uv run evals/run_evals.py -g rg-iq-lab-dev -v

# Upload results to Azure AI Foundry for LLM-judged evaluation
uv run evals/upload_to_foundry.py -g rg-iq-lab-dev
```

> Both scripts use the **Responses API** (`openai_client.responses.create()` with
> `agent_reference`) — matching `chat_agent.py`. MCP mode is the default; use
> `--legacy` for HTTP dispatch mode.

## Architecture

```
evals/
├── dataset.json           # Test cases: prompts, expected tools, assertions
├── scorers.py             # Scoring functions (grounding, safety, format, etc.)
├── run_evals.py           # PEP 723 runner — runs eval suite against live agent
├── upload_to_foundry.py   # PEP 723 uploader — sends results to Foundry Evaluations
├── README.md              # This file
└── results/               # JSON reports (gitignored, auto-created)
    ├── eval-*.json            # Local eval results
    └── foundry-eval-*.json    # Foundry evaluator output (local copy)
```

## Test Categories

| Category       | What it tests                                           | Cases |
|---------------|---------------------------------------------------------|-------|
| `triage`      | Basic ticket query + summary accuracy                   | 3     |
| `safety`      | Hallucination prevention, refusal of disallowed actions  | 4     |
| `governance`  | Approval workflow enforcement                            | 1     |
| `grounding`   | Metric citation, field-level accuracy                    | 2     |
| `tool_use`    | Correct tool selection and argument passing              | 1     |
| `consistency` | Same data across multiple questions                      | 1     |
| `knowledge`   | Device manual grounding, CLI commands, SLA, hybrid triage    | 5     |

## Scorers

Each eval case is scored by **6 independent scorers**:

1. **`score_tool_calls`** — Were the expected tools called? No unexpected tools?
2. **`score_grounding`** — Does the response contain required terms? Exclude forbidden ones?
3. **`score_format`** — Does the output respect bullet count and structure rules?
4. **`score_safety`** — Did the agent refuse disallowed requests? Avoid hallucination?
5. **`score_tool_call_args`** — Were tool call arguments correct (e.g., right ticket_id)?
6. **`score_knowledge`** — Did the agent cite device manuals, thresholds, or CLI commands?

Aggregate score = weighted pass rate across all scorers (0.0 – 1.0).

## Results Format

Results are saved to `evals/results/eval-<timestamp>.json`:

```json
{
  "metadata": {
    "timestamp": "2026-03-03T12:00:00+00:00",
    "agent_name": "iq-triage-agent",
    "model": "gpt-4.1-mini"
  },
  "summary": {
    "total_cases": 12,
    "passed": 11,
    "failed": 1,
    "aggregate_score": 0.95
  },
  "results": [
    {
      "case_id": "triage-basic-001",
      "prompt": "Summarize ticket TKT-0042",
      "agent_response": "**Ticket TKT-0042** — ...",
      "tool_calls": [...],
      "scores": [...],
      "aggregate_score": 1.0,
      "elapsed_seconds": 3.2
    }
  ]
}
```

## Adding Test Cases

Add entries to `dataset.json`. Each case needs:

```json
{
  "id": "unique-case-id",
  "category": "triage|safety|governance|grounding|tool_use|consistency",
  "description": "What this tests",
  "prompt": "User message to send",
  "expected_tools": ["query_ticket_context"],
  "assertions": {
    "must_contain": ["terms that MUST appear in response"],
    "must_contain_any": ["at least ONE of these must appear"],
    "must_not_contain": ["terms that MUST NOT appear"],
    "must_not_contain_pattern": "regex that must NOT match",
    "max_bullets": 3,
    "requires_tool_call": true,
    "requires_grounding": true,
    "no_hallucination": true,
    "refusal_expected": false,
    "requires_approval_mention": false,
    "tool_call_args_contain": {
      "function_name": {"arg": "expected_value"}
    }
  }
}
```

## Adding Custom Scorers

Add a function to `scorers.py` and register it in `ALL_SCORERS`. Signature:

```python
def score_my_check(case: dict, agent_response: str, ...) -> ScoreResult:
    return {
        "scorer": "my_check",
        "passed": True,
        "detail": "Explanation",
        "weight": 1.0,
    }
```

## CI Integration

Add to your CI workflow:

```yaml
- name: Run agent evals
  run: uv run evals/run_evals.py --resource-group ${{ vars.RESOURCE_GROUP }}
  env:
    AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}

- name: Upload results to Foundry
  run: uv run evals/upload_to_foundry.py -g ${{ vars.RESOURCE_GROUP }} --no-wait
```

## Upload to Azure AI Foundry

Results can be uploaded to Foundry's portal-based evaluation dashboard using
built-in evaluators (tool call accuracy, task adherence, intent resolution,
coherence, groundedness).

```powershell
# Upload latest results and run Foundry built-in evaluators
uv run evals/upload_to_foundry.py --resource-group rg-iq-lab-dev

# Upload a specific result file
uv run evals/upload_to_foundry.py -g rg-iq-lab-dev `
    --result-file evals/results/eval-20260304T162306Z.json

# Upload dataset only (no Foundry scoring)
uv run evals/upload_to_foundry.py -g rg-iq-lab-dev --dataset-only

# Use a specific model for LLM-judged evaluators
uv run evals/upload_to_foundry.py -g rg-iq-lab-dev --model-deployment gpt-4.1-mini

# Start the run without waiting for completion
uv run evals/upload_to_foundry.py -g rg-iq-lab-dev --no-wait
```

Foundry evaluators applied:

| Evaluator | What it measures |
|---|---|
| `builtin.tool_call_accuracy` | Correct tool selection + parameter accuracy |
| `builtin.task_adherence` | Response alignment with task instructions |
| `builtin.intent_resolution` | User intent correctly identified and resolved |
| `builtin.coherence` | Natural language quality |
| `builtin.groundedness` | Claims substantiated by tool output context |

Results appear in the Foundry portal under **Evaluations** and are also saved
locally to `evals/results/foundry-eval-<timestamp>.json`.

## Demo Tips

1. Run the full suite to show the summary table
2. Use `--case safety-refusal-001` to demo a single safety check
3. Use `-v` to show tool call details for grounding demos
4. Open `evals/results/*.json` for the structured report
5. Upload to Foundry for portal-based evaluation dashboard
