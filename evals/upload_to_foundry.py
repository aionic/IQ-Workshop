# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-projects>=2.0.0b2",
#     "azure-identity>=1.15.0",
#     "openai>=1.75",
# ]
# ///
"""
upload_to_foundry.py — Upload IQ agent evaluation results to Azure AI Foundry.

Converts local eval results (from run_evals.py) into Foundry's evaluation
framework so they appear in the Foundry portal under **Evaluations**.

Two modes:

1. **Upload existing results** (default):
   Converts a local eval result JSON into JSONL, uploads as a dataset,
   creates an evaluation definition with built-in Foundry evaluators,
   and starts a run.

2. **Upload dataset only** (``--dataset-only``):
   Uploads the JSONL for a past run so it's browseable in Foundry
   without re-scoring.

Usage:

    # Upload latest result and run Foundry evaluators:
    uv run evals/upload_to_foundry.py --resource-group rg-iq-lab-dev

    # Upload a specific result file:
    uv run evals/upload_to_foundry.py -g rg-iq-lab-dev \\
        --result-file evals/results/eval-20260303T203106Z.json

    # Upload dataset only (no Foundry scoring):
    uv run evals/upload_to_foundry.py -g rg-iq-lab-dev --dataset-only

    # Specify a model deployment for LLM-based evaluators:
    uv run evals/upload_to_foundry.py -g rg-iq-lab-dev --model-deployment gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"

# ---------------------------------------------------------------------------
# MCP tool definitions (for tool_call_accuracy evaluator)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "query_ticket_context",
        "description": "Query ticket context with linked anomaly and device data.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket identifier (e.g. TKT-0042).",
                },
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "request_approval",
        "description": "Request approval for a proposed remediation action.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "proposed_action": {"type": "string"},
                "rationale": {"type": "string"},
                "correlation_id": {"type": "string"},
            },
            "required": ["ticket_id", "proposed_action", "rationale"],
        },
    },
    {
        "name": "execute_remediation",
        "description": "Execute an approved remediation action.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "approval_token": {"type": "string"},
                "correlation_id": {"type": "string"},
            },
            "required": ["ticket_id", "approval_token"],
        },
    },
    {
        "name": "post_teams_summary",
        "description": "Post triage summary to Microsoft Teams.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "summary": {"type": "string"},
                "channel": {"type": "string"},
                "correlation_id": {"type": "string"},
            },
            "required": ["ticket_id", "summary"],
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _az_output(cmd: list[str]) -> str:
    az_exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run(  # noqa: S603
        [az_exe, *cmd[1:]], capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _resolve_from_bicep(resource_group: str) -> dict[str, str]:
    print(f"Resolving from Bicep outputs in {resource_group}...")
    raw = _az_output([
        "az", "deployment", "group", "show",
        "--resource-group", resource_group,
        "--name", "main",
        "--query", "properties.outputs",
        "--output", "json",
    ])
    outputs = json.loads(raw)
    return {
        "project_endpoint": outputs["foundryProjectEndpoint"]["value"],
    }


def _find_latest_result() -> Path | None:
    """Find the most recent eval result file."""
    if not RESULTS_DIR.exists():
        return None
    files = sorted(RESULTS_DIR.glob("eval-*.json"), reverse=True)
    return files[0] if files else None


def _result_to_conversation_messages(result: dict) -> list[dict]:
    """Convert a single eval result into the Foundry conversation-style
    response format (list of messages with role/content)."""
    messages: list[dict] = []

    # User message
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": result["prompt"]}],
    })

    # Tool calls + results (if any)
    for tc in result.get("tool_calls", []):
        # Assistant makes tool call
        # Foundry evaluators require 'arguments' as a dict, not a JSON string
        args_val = tc["arguments"]
        if isinstance(args_val, str):
            args_val = json.loads(args_val)
        messages.append({
            "role": "assistant",
            "content": [{
                "type": "tool_call",
                "tool_call_id": f"call_{tc['function_name']}",
                "name": tc["function_name"],
                "arguments": args_val,
            }],
        })
        # Tool result
        output = tc.get("output", "")
        if output == "(MCP server-side execution)":
            # MCP mode — no explicit output captured
            output = json.dumps({"status": "executed via MCP"})
        messages.append({
            "role": "tool",
            "tool_call_id": f"call_{tc['function_name']}",
            "content": [{"type": "tool_result", "tool_result": output}],
        })

    # Final assistant response
    messages.append({
        "role": "assistant",
        "content": [{"type": "text", "text": result["agent_response"]}],
    })

    return messages


def _convert_results_to_jsonl(results: list[dict]) -> str:
    """Convert eval results to JSONL format for Foundry upload.

    Each line is a JSON object with:
      - query: the user prompt
      - response: conversation messages (list format for agent evaluators)
      - tool_definitions: MCP tool schemas
      - context: tool output text (for groundedness evaluator)
    """
    lines: list[str] = []

    for r in results:
        # Build context from tool outputs
        context_parts = []
        for tc in r.get("tool_calls", []):
            output = tc.get("output", "")
            if output and output != "(MCP server-side execution)":
                context_parts.append(f"[{tc['function_name']}] {output}")

        row = {
            "query": r["prompt"],
            "response": _result_to_conversation_messages(r),
            "tool_definitions": TOOL_DEFINITIONS,
            "context": "\n".join(context_parts) if context_parts else "",
        }
        lines.append(json.dumps(row, default=str))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload IQ agent eval results to Azure AI Foundry.",
    )
    parser.add_argument("--resource-group", "-g", default="")
    parser.add_argument(
        "--result-file", "-f", default="",
        help="Path to a specific eval result JSON. Default: latest in evals/results/.",
    )
    parser.add_argument(
        "--model-deployment", "-m", default="gpt-4.1-mini",
        help="Model deployment name for LLM-based evaluators (default: gpt-4.1-mini).",
    )
    parser.add_argument(
        "--dataset-only", action="store_true",
        help="Upload dataset only — skip creating evaluation and run.",
    )
    parser.add_argument(
        "--no-wait", action="store_true",
        help="Start the eval run but don't poll — print the run ID and exit.",
    )
    args = parser.parse_args()

    # --- Resolve project endpoint ---
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    if args.resource_group:
        vals = _resolve_from_bicep(args.resource_group)
        project_endpoint = project_endpoint or vals["project_endpoint"]
    if not project_endpoint:
        print("ERROR: Set AZURE_AI_PROJECT_ENDPOINT or use --resource-group.", file=sys.stderr)
        sys.exit(1)

    # --- Load result file ---
    result_path: Path | None = None
    if args.result_file:
        result_path = Path(args.result_file)
    else:
        result_path = _find_latest_result()

    if not result_path or not result_path.exists():
        print("ERROR: No eval result file found. Run evals first:", file=sys.stderr)
        print("  uv run evals/run_evals.py --resource-group rg-iq-lab-dev", file=sys.stderr)
        sys.exit(1)

    print(f"Project:     {project_endpoint}")
    print(f"Result file: {result_path}")
    print(f"Model:       {args.model_deployment}")
    print()

    # --- Load results ---
    report = json.loads(result_path.read_text())
    results = report["results"]
    metadata = report.get("metadata", {})
    summary = report.get("summary", {})

    print(f"Results: {summary.get('total_cases', len(results))} cases, "
          f"{summary.get('passed', '?')} passed, "
          f"aggregate={summary.get('aggregate_score', '?')}")
    print()

    # --- Convert to JSONL ---
    jsonl_content = _convert_results_to_jsonl(results)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    # Write to temp file for upload
    tmp_dir = Path(tempfile.mkdtemp())
    jsonl_path = tmp_dir / f"iq-agent-eval-{timestamp}.jsonl"
    jsonl_path.write_text(jsonl_content)

    print(f"Converted {len(results)} results to JSONL ({jsonl_path.stat().st_size} bytes)")

    # --- Connect to Foundry ---
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )
    openai_client = project_client.get_openai_client()

    # --- Upload dataset ---
    print("Uploading dataset to Foundry...")
    dataset = project_client.datasets.upload_file(
        name=f"iq-agent-eval-{timestamp}",
        version="1",
        file_path=str(jsonl_path),
    )
    print(f"Dataset uploaded: {dataset.name} (ID: {dataset.id})")

    if args.dataset_only:
        print("\n--dataset-only: Skipping evaluation creation. Dataset is available in Foundry.")
        # Cleanup
        jsonl_path.unlink(missing_ok=True)
        tmp_dir.rmdir()
        return

    # --- Define data source config ---
    from openai.types.eval_create_params import DataSourceConfigCustom
    from openai.types.evals.create_eval_jsonl_run_data_source_param import (
        CreateEvalJSONLRunDataSourceParam,
        SourceFileID,
    )

    data_source_config = DataSourceConfigCustom({
        "type": "custom",
        "item_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "response": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "array"},
                        },
                    },
                },
                "tool_definitions": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "context": {"type": "string"},
            },
            "required": ["query", "response"],
        },
        "include_sample_schema": True,
    })

    # --- Define testing criteria (Foundry built-in evaluators) ---
    deployment = args.model_deployment

    testing_criteria = [
        # Agent-specific evaluators
        {
            "type": "azure_ai_evaluator",
            "name": "tool_call_accuracy",
            "evaluator_name": "builtin.tool_call_accuracy",
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
            "initialization_parameters": {"deployment_name": deployment},
        },
        {
            "type": "azure_ai_evaluator",
            "name": "task_adherence",
            "evaluator_name": "builtin.task_adherence",
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
            "initialization_parameters": {"deployment_name": deployment},
        },
        {
            "type": "azure_ai_evaluator",
            "name": "intent_resolution",
            "evaluator_name": "builtin.intent_resolution",
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
            "initialization_parameters": {"deployment_name": deployment},
        },
        {
            "type": "azure_ai_evaluator",
            "name": "coherence",
            "evaluator_name": "builtin.coherence",
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
            "initialization_parameters": {"deployment_name": deployment},
        },
        {
            "type": "azure_ai_evaluator",
            "name": "groundedness",
            "evaluator_name": "builtin.groundedness",
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "context": "{{item.context}}",
            },
            "initialization_parameters": {"deployment_name": deployment},
        },
    ]

    # --- Create evaluation ---
    print("Creating Foundry evaluation...")
    evaluation = openai_client.evals.create(
        name=f"iq-agent-eval-{timestamp}",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"Evaluation created: {evaluation.id}")

    # --- Create evaluation run ---
    print("Starting evaluation run...")
    run = openai_client.evals.runs.create(
        eval_id=evaluation.id,
        name=f"iq-agent-eval-run-{timestamp}",
        data_source=CreateEvalJSONLRunDataSourceParam(
            type="jsonl",
            source=SourceFileID(type="file_id", id=dataset.id),
        ),
    )
    print(f"Run created: {run.id}")
    print(f"Eval ID:     {evaluation.id}")

    if args.no_wait:
        print("\n--no-wait: Check results in the Foundry portal.")
        # Cleanup temp file
        jsonl_path.unlink(missing_ok=True)
        tmp_dir.rmdir()
        return

    # --- Poll for completion ---
    print("Waiting for evaluation to complete...")
    while run.status not in ("completed", "failed"):
        run = openai_client.evals.runs.retrieve(
            run_id=run.id, eval_id=evaluation.id,
        )
        print(f"  Status: {run.status}")
        time.sleep(5)

    print()
    if run.status == "completed":
        print("Evaluation completed!")
        print(f"Report URL: {run.report_url}")

        # Save output items locally
        output_items = list(
            openai_client.evals.runs.output_items.list(
                run_id=run.id, eval_id=evaluation.id,
            )
        )
        local_output = RESULTS_DIR / f"foundry-eval-{timestamp}.json"
        local_output.write_text(
            json.dumps(
                [item.model_dump() for item in output_items],
                indent=2,
                default=str,
            )
        )
        print(f"Local copy:  {local_output}")
    else:
        print(f"Evaluation failed with status: {run.status}")

    # Cleanup temp file
    jsonl_path.unlink(missing_ok=True)
    tmp_dir.rmdir()


if __name__ == "__main__":
    main()
