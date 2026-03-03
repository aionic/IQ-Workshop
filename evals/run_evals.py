# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-projects",
#     "azure-ai-agents>=1.2.0b2",
#     "azure-identity>=1.15.0",
#     "httpx>=0.27",
# ]
# ///
"""
run_evals.py — Run the IQ agent evaluation suite against a live Foundry agent.

Loads test cases from ``evals/dataset.json``, sends each prompt through the
agent (with client-side tool execution), scores the response with the scorers
from ``evals/scorers.py``, and writes a results report to ``evals/results/``.

Usage:

    uv run evals/run_evals.py --resource-group rg-iq-lab-dev

    # Or with explicit env vars:
    AZURE_AI_PROJECT_ENDPOINT=... TOOL_SERVICE_URL=... AGENT_ID=asst_...
    uv run evals/run_evals.py

    # Run a single case:
    uv run evals/run_evals.py --resource-group rg-iq-lab-dev --case triage-basic-001

    # Verbose output:
    uv run evals/run_evals.py --resource-group rg-iq-lab-dev -v
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from azure.ai.agents.models import MessageRole, RunStatus, ToolOutput
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = Path(__file__).resolve().parent
DATASET_PATH = EVALS_DIR / "dataset.json"
RESULTS_DIR = EVALS_DIR / "results"

# Ensure evals/ is importable
sys.path.insert(0, str(EVALS_DIR))
from scorers import compute_aggregate, run_all_scorers  # noqa: E402

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_tool_service_url: str = ""

# Map tool function names → FastAPI endpoint paths
FUNCTION_TO_ENDPOINT: dict[str, tuple[str, str]] = {
    "query_ticket_context": ("POST", "/tools/query-ticket-context"),
    "request_approval": ("POST", "/tools/request-approval"),
    "execute_remediation": ("POST", "/tools/execute-remediation"),
    "post_teams_summary": ("POST", "/tools/post-teams-summary"),
}


# ---------------------------------------------------------------------------
# HTTP helper (reused from chat_agent.py pattern)
# ---------------------------------------------------------------------------


def _call_tool_service(function_name: str, arguments: dict) -> str:
    """Call a FastAPI tool endpoint and return the JSON response as a string."""
    if function_name not in FUNCTION_TO_ENDPOINT:
        return json.dumps({"error": f"Unknown function: {function_name}"})
    method, path = FUNCTION_TO_ENDPOINT[function_name]
    url = f"{_tool_service_url}{path}"
    try:
        resp = httpx.request(method, url, json=arguments, timeout=30)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "detail": e.response.text})
    except httpx.RequestError as e:
        return json.dumps({"error": f"Request failed: {e}"})


# ---------------------------------------------------------------------------
# Agent turn — returns response + structured tool call log
# ---------------------------------------------------------------------------


def run_agent_turn(
    project_client: AIProjectClient,
    thread_id: str,
    agent_id: str,
    user_message: str,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """
    Send a message, handle tool calls, and return:
      (agent_response_text, list_of_tool_call_records)

    Each tool call record:
        {"function_name": str, "arguments": dict, "output": str}
    """
    tool_call_log: list[dict] = []
    turn_correlation_id = str(uuid.uuid4())

    # Post user message
    project_client.agents.messages.create(
        thread_id=thread_id, role="user", content=user_message,
    )

    # Start a run
    run = project_client.agents.runs.create(thread_id=thread_id, agent_id=agent_id)

    # Poll until terminal state
    while run.status in (RunStatus.QUEUED, RunStatus.IN_PROGRESS, RunStatus.REQUIRES_ACTION):
        if run.status == RunStatus.REQUIRES_ACTION:
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            tool_outputs: list[ToolOutput] = []

            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)

                if fn_name in {"request_approval", "execute_remediation", "post_teams_summary"}:
                    if not fn_args.get("correlation_id"):
                        fn_args["correlation_id"] = turn_correlation_id

                if verbose:
                    print(f"    -> {fn_name}({json.dumps(fn_args, separators=(',', ':'))})")

                result = _call_tool_service(fn_name, fn_args)
                tool_call_log.append({
                    "function_name": fn_name,
                    "arguments": fn_args,
                    "output": result,
                })
                tool_outputs.append(ToolOutput(tool_call_id=tc.id, output=result))

            run = project_client.agents.runs.submit_tool_outputs(
                thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs,
            )
        else:
            time.sleep(1)
            run = project_client.agents.runs.get(thread_id=thread_id, run_id=run.id)

    if run.status == RunStatus.FAILED:
        return f"[Run failed: {run.last_error}]", tool_call_log

    if run.status != RunStatus.COMPLETED:
        return f"[Run ended with status: {run.status}]", tool_call_log

    # Get the latest assistant message
    messages = project_client.agents.messages.list(thread_id=thread_id, order="desc")
    for msg in messages:
        if msg.role == MessageRole.AGENT:
            parts = []
            for block in msg.content:
                if hasattr(block, "text"):
                    parts.append(block.text.value)
            if parts:
                return "\n".join(parts), tool_call_log

    return "[No response]", tool_call_log


# ---------------------------------------------------------------------------
# Helpers — Bicep / state
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
        "tool_service_url": outputs["toolServiceUrl"]["value"],
    }


def _load_agent_state() -> dict[str, str]:
    state_path = REPO_ROOT / ".agent-state.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _print_report(results: list[dict], verbose: bool) -> None:
    """Print a summary table to stdout."""
    passed = sum(1 for r in results if r["aggregate_score"] == 1.0)
    total = len(results)

    print()
    print("=" * 72)
    print(f"  IQ AGENT EVALUATION REPORT — {passed}/{total} cases fully passed")
    print("=" * 72)
    print()

    for r in results:
        status = "PASS" if r["aggregate_score"] == 1.0 else "FAIL"
        icon = "✓" if status == "PASS" else "✗"
        print(f"  {icon} [{status}] {r['case_id']:30s}  score={r['aggregate_score']:.2f}  ({r['category']})")

        if verbose or status == "FAIL":
            for s in r["scores"]:
                s_icon = "✓" if s["passed"] else "✗"
                print(f"       {s_icon} {s['scorer']:20s} — {s['detail']}")
            if verbose:
                print(f"       Response preview: {r['agent_response'][:120]}...")
            print()

    print("-" * 72)
    avg = sum(r["aggregate_score"] for r in results) / total if total else 0
    print(f"  Aggregate score: {avg:.2%}  |  {passed}/{total} cases passed")
    print("-" * 72)
    print()


def _save_results(results: list[dict], metadata: dict) -> Path:
    """Save results JSON to evals/results/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"eval-{timestamp}.json"

    report = {
        "metadata": metadata,
        "summary": {
            "total_cases": len(results),
            "passed": sum(1 for r in results if r["aggregate_score"] == 1.0),
            "failed": sum(1 for r in results if r["aggregate_score"] < 1.0),
            "aggregate_score": round(
                sum(r["aggregate_score"] for r in results) / len(results), 4
            ) if results else 0,
        },
        "results": results,
    }

    out_path.write_text(json.dumps(report, indent=2, default=str))
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    global _tool_service_url  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="Run IQ agent evaluation suite.")
    parser.add_argument("--resource-group", "-g", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--case", "-c", default="", help="Run a single case by ID.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # --- Resolve configuration ---
    state = _load_agent_state()
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    _tool_service_url = state.get("tool_service_url", os.environ.get("TOOL_SERVICE_URL", ""))
    agent_id = args.agent_id or state.get("agent_id", os.environ.get("AGENT_ID", ""))

    if args.resource_group:
        vals = _resolve_from_bicep(args.resource_group)
        project_endpoint = project_endpoint or vals["project_endpoint"]
        _tool_service_url = _tool_service_url or vals["tool_service_url"]

    if not project_endpoint:
        print("ERROR: Set AZURE_AI_PROJECT_ENDPOINT or use --resource-group.", file=sys.stderr)
        sys.exit(1)
    if not _tool_service_url:
        print("ERROR: Set TOOL_SERVICE_URL or use --resource-group.", file=sys.stderr)
        sys.exit(1)
    if not agent_id:
        print("ERROR: Set AGENT_ID, use --agent-id, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)

    # --- Load dataset ---
    dataset = json.loads(DATASET_PATH.read_text())
    cases = dataset["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"ERROR: Case '{args.case}' not found in dataset.", file=sys.stderr)
            sys.exit(1)

    print(f"Project:  {project_endpoint}")
    print(f"Tools:    {_tool_service_url}")
    print(f"Agent:    {agent_id}")
    print(f"Cases:    {len(cases)}")
    print()

    # --- Connect ---
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    # --- Run each case in its own thread (isolation) ---
    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        case_id = case["id"]
        prompt = case["prompt"]

        print(f"[{i}/{len(cases)}] {case_id}: {prompt[:60]}...")

        # Fresh thread per case (isolation)
        thread = project_client.agents.threads.create()

        t0 = time.time()
        agent_response, tool_call_log = run_agent_turn(
            project_client, thread.id, agent_id, prompt, verbose=args.verbose,
        )
        elapsed = round(time.time() - t0, 2)

        # Score
        scores = run_all_scorers(case, agent_response, tool_call_log)
        agg = compute_aggregate(scores)

        status = "PASS" if agg == 1.0 else "FAIL"
        print(f"         -> {status}  (score={agg:.2f}, {elapsed}s)")

        results.append({
            "case_id": case_id,
            "category": case.get("category", ""),
            "description": case.get("description", ""),
            "prompt": prompt,
            "agent_response": agent_response,
            "tool_calls": tool_call_log,
            "scores": scores,
            "aggregate_score": agg,
            "elapsed_seconds": elapsed,
        })

    # --- Report ---
    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "project_endpoint": project_endpoint,
        "tool_service_url": _tool_service_url,
        "model": "gpt-4.1-mini",
        "dataset_version": dataset.get("_version", "unknown"),
    }

    _print_report(results, verbose=args.verbose)
    out_path = _save_results(results, metadata)
    print(f"Results saved to: {out_path}")


if __name__ == "__main__":
    main()
