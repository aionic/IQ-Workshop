# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-projects>=2.0.0b2",
#     "azure-identity>=1.15.0",
#     "openai>=1.68.0",
#     "httpx>=0.27",
# ]
# ///
"""
run_evals.py — Run the IQ agent evaluation suite against a live Foundry agent.

Uses the **new** Responses API (``openai_client.responses.create()``) with
``agent_reference`` — matching the API used by ``chat_agent.py``.

Supports two tool modes (auto-detected from ``.agent-state.json``):

**MCP mode** (default): Foundry Agent Service calls the MCP server directly.
All MCP tool calls are auto-approved (no human-in-the-loop during automated evals).

**Legacy mode**: Client-side HTTP dispatch to FastAPI REST endpoints.

Usage:

    uv run evals/run_evals.py --resource-group rg-iq-lab-dev

    # Force legacy mode:
    uv run evals/run_evals.py --resource-group rg-iq-lab-dev --legacy

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
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses.response_input_param import McpApprovalResponse

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
# Agent turn — MCP mode (auto-approve all tools for evals)
# ---------------------------------------------------------------------------


def run_agent_turn_mcp(
    openai_client,
    agent_name: str,
    conversation_id: str,
    user_message: str,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """MCP mode: send a message, auto-approve all tools, return reply + log.

    During automated evals, ALL MCP tool calls are auto-approved so the
    agent can run end-to-end without human intervention.

    Uses the Responses API with ``agent_reference`` (new-style Prompt Agents).
    """
    tool_call_log: list[dict] = []
    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}

    # Send user message via the Responses API
    response = openai_client.responses.create(
        conversation=conversation_id,
        input=user_message,
        extra_body=agent_ref,
    )

    # Loop: auto-approve all MCP approval requests until the agent produces a final response
    while True:
        approval_inputs: list[McpApprovalResponse] = []
        for item in response.output:
            if item.type == "mcp_approval_request":
                fn_name = item.name
                if verbose:
                    print(f"    -> MCP auto-approve: {fn_name}({item.arguments})")
                # Parse arguments to dict for scorer compatibility
                fn_args = item.arguments if isinstance(item.arguments, dict) else json.loads(item.arguments or "{}")
                tool_call_log.append({
                    "function_name": fn_name,
                    "arguments": fn_args,
                    "output": "(MCP server-side execution)",
                })
                approval_inputs.append(
                    McpApprovalResponse(
                        type="mcp_approval_response",
                        approve=True,
                        approval_request_id=item.id,
                    )
                )

        if not approval_inputs:
            # No more approvals needed — agent is done
            break

        # Submit approvals and get next response
        response = openai_client.responses.create(
            input=approval_inputs,
            previous_response_id=response.id,
            extra_body=agent_ref,
        )

    # Check for error states
    if response.status == "failed":
        return f"[Response failed: {response.error}]", tool_call_log
    if response.status == "incomplete":
        return f"[Response incomplete: {response.incomplete_details}]", tool_call_log

    return response.output_text or "[No response]", tool_call_log


# ---------------------------------------------------------------------------
# Agent turn — Legacy mode (function call dispatch via HTTP)
# ---------------------------------------------------------------------------


def run_agent_turn(
    openai_client,
    agent_name: str,
    conversation_id: str,
    user_message: str,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """Legacy mode: send a message, handle function calls via HTTP, return reply + log.

    Each tool call record:
        {"function_name": str, "arguments": dict, "output": str}
    """
    tool_call_log: list[dict] = []
    turn_correlation_id = str(uuid.uuid4())
    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}

    # Send user message
    response = openai_client.responses.create(
        conversation=conversation_id,
        input=user_message,
        extra_body=agent_ref,
    )

    # Loop: handle function calls until the agent produces a final text response
    while True:
        function_outputs: list[dict] = []
        for item in response.output:
            if item.type == "function_call":
                fn_name = item.name
                fn_args = json.loads(item.arguments)

                # Inject correlation_id for mutating operations
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
                function_outputs.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": result,
                })

        if not function_outputs:
            break

        # Submit function outputs and get next response
        response = openai_client.responses.create(
            input=function_outputs,
            previous_response_id=response.id,
            extra_body=agent_ref,
        )

    if response.status == "failed":
        return f"[Response failed: {response.error}]", tool_call_log

    return response.output_text or "[No response]", tool_call_log


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
    parser.add_argument("--agent-name", default="", help="Agent name (default: from state file).")
    parser.add_argument("--case", "-c", default="", help="Run a single case by ID.")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Force legacy FunctionTool mode (HTTP dispatch) instead of MCP.",
    )
    args = parser.parse_args()

    # --- Resolve configuration ---
    state = _load_agent_state()
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    _tool_service_url = state.get("tool_service_url", os.environ.get("TOOL_SERVICE_URL", ""))
    agent_name = (
        args.agent_name
        or state.get("agent_name", "")
        or os.environ.get("AGENT_NAME", "iq-triage-agent")
    )

    # Determine tool mode: CLI flag overrides state file
    tool_mode = "legacy" if args.legacy else state.get("tool_mode", "mcp")

    if args.resource_group:
        vals = _resolve_from_bicep(args.resource_group)
        project_endpoint = project_endpoint or vals["project_endpoint"]
        _tool_service_url = _tool_service_url or vals["tool_service_url"]

    if not project_endpoint:
        print("ERROR: Set AZURE_AI_PROJECT_ENDPOINT or use --resource-group.", file=sys.stderr)
        sys.exit(1)
    if not _tool_service_url and tool_mode == "legacy":
        print("ERROR: Set TOOL_SERVICE_URL for legacy mode, or use --resource-group.", file=sys.stderr)
        sys.exit(1)
    if not agent_name:
        print("ERROR: Set AGENT_NAME, use --agent-name, or run create_agent.py first.", file=sys.stderr)
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
    print(f"Agent:    {agent_name}")
    print(f"Mode:     {'MCP (auto-approve all)' if tool_mode == 'mcp' else 'Legacy (HTTP dispatch)'}")
    print(f"Cases:    {len(cases)}")
    print()

    # --- Connect via AIProjectClient + OpenAI client (Responses API) ---
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )
    openai_client = project_client.get_openai_client()

    # --- Run each case in its own conversation (isolation) ---
    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        case_id = case["id"]
        prompt = case["prompt"]

        print(f"[{i}/{len(cases)}] {case_id}: {prompt[:60]}...")

        # Fresh conversation per case (isolation)
        conversation = openai_client.conversations.create()

        t0 = time.time()
        if tool_mode == "mcp":
            agent_response, tool_call_log = run_agent_turn_mcp(
                openai_client, agent_name, conversation.id, prompt,
                verbose=args.verbose,
            )
        else:
            agent_response, tool_call_log = run_agent_turn(
                openai_client, agent_name, conversation.id, prompt,
                verbose=args.verbose,
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
        "agent_name": agent_name,
        "project_endpoint": project_endpoint,
        "tool_service_url": _tool_service_url,
        "tool_mode": tool_mode,
        "model": "gpt-4.1-mini",
        "dataset_version": dataset.get("_version", "unknown"),
    }

    _print_report(results, verbose=args.verbose)
    out_path = _save_results(results, metadata)
    print(f"Results saved to: {out_path}")


if __name__ == "__main__":
    main()
