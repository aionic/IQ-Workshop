# Agent Evaluations — IQ Foundry Agent Lab

Automated evaluation suite for the IQ triage agent. Tests grounding accuracy,
tool-call correctness, safety refusals, governance compliance, and output format.

## Quick Start

```bash
# Run the full eval suite against a live agent
uv run evals/run_evals.py --resource-group rg-iq-lab-dev

# Run a single case
uv run evals/run_evals.py -g rg-iq-lab-dev --case triage-basic-001

# Verbose output (shows tool calls + response previews)
uv run evals/run_evals.py -g rg-iq-lab-dev -v
```

## Architecture

```
evals/
├── dataset.json      # Test cases: prompts, expected tools, assertions
├── scorers.py        # Scoring functions (grounding, safety, format, etc.)
├── run_evals.py      # PEP 723 runner script (uv run)
├── README.md         # This file
└── results/          # JSON reports (gitignored, auto-created)
    └── eval-20260303T120000Z.json
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

## Scorers

Each eval case is scored by **5 independent scorers**:

1. **`score_tool_calls`** — Were the expected tools called? No unexpected tools?
2. **`score_grounding`** — Does the response contain required terms? Exclude forbidden ones?
3. **`score_format`** — Does the output respect bullet count and structure rules?
4. **`score_safety`** — Did the agent refuse disallowed requests? Avoid hallucination?
5. **`score_tool_call_args`** — Were tool call arguments correct (e.g., right ticket_id)?

Aggregate score = weighted pass rate across all scorers (0.0 – 1.0).

## Results Format

Results are saved to `evals/results/eval-<timestamp>.json`:

```json
{
  "metadata": {
    "timestamp": "2026-03-03T12:00:00+00:00",
    "agent_id": "asst_...",
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
```

## Demo Tips

1. Run the full suite to show the summary table
2. Use `--case safety-refusal-001` to demo a single safety check
3. Use `-v` to show tool call details for grounding demos
4. Open `evals/results/*.json` for the structured report
