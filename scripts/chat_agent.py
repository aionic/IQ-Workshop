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
chat_agent.py — Interactive chat loop with client-side tool execution.

Uses Agent Framework v2 SDK (``AIProjectClient`` + ``FunctionTool``).
Connects to the Foundry agent created by create_agent.py, sends user messages,
intercepts requires_action events, calls the FastAPI tool service over HTTP,
and submits tool outputs back to the agent run.

Usage:

    uv run scripts/chat_agent.py --resource-group rg-iq-lab-dev

Or with explicit env vars:

    $env:AZURE_AI_PROJECT_ENDPOINT = "..."
    $env:TOOL_SERVICE_URL = "..."
    $env:AGENT_ID = "asst_..."
    uv run scripts/chat_agent.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from azure.ai.agents.models import MessageRole, RunStatus, ToolOutput
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Module-level tool service URL — set at runtime before tool functions are
# called.  The tool functions below read this to build HTTP URLs.
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
# Tool functions — these are the real implementations that call the FastAPI
# service over HTTP.  Function names match the agent's function tool
# definitions (snake_case) registered by create_agent.py.
# ---------------------------------------------------------------------------


def query_ticket_context(ticket_id: str) -> str:
    """
    Query ticket context with linked anomaly and device data.

    :param ticket_id: The ticket identifier (e.g. TKT-0042).
    :return: JSON with ticket metadata, anomaly metrics, and device/site info.
    """
    return _call_tool_service("query_ticket_context", {"ticket_id": ticket_id})


def request_approval(
    ticket_id: str,
    proposed_action: str,
    rationale: str,
    correlation_id: str = "",
) -> str:
    """
    Request approval for a proposed remediation action.

    :param ticket_id: Ticket to remediate.
    :param proposed_action: Action to perform (e.g. restart_bgp_sessions).
    :param rationale: Why this action is appropriate.
    :param correlation_id: Optional correlation ID for tracing.
    :return: JSON with remediation_id, approval_token, and status.
    """
    payload: dict = {
        "ticket_id": ticket_id,
        "proposed_action": proposed_action,
        "rationale": rationale,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return _call_tool_service("request_approval", payload)


def execute_remediation(
    ticket_id: str,
    action: str,
    approved_by: str,
    approval_token: str,
    correlation_id: str = "",
) -> str:
    """
    Execute an approved remediation action.

    :param ticket_id: The ticket identifier.
    :param action: The action to execute.
    :param approved_by: Email of the person who approved.
    :param approval_token: Token from request_approval (must be APPROVED).
    :param correlation_id: Correlation ID for tracing.
    :return: JSON with remediation_id, outcome, and executed_utc.
    """
    payload: dict = {
        "ticket_id": ticket_id,
        "action": action,
        "approved_by": approved_by,
        "approval_token": approval_token,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return _call_tool_service("execute_remediation", payload)


def post_teams_summary(
    ticket_id: str,
    summary: str,
    action_taken: str,
    approved_by: str,
    correlation_id: str = "",
) -> str:
    """
    Post a remediation summary to Microsoft Teams.

    :param ticket_id: The ticket identifier.
    :param summary: Summary text.
    :param action_taken: Action that was executed.
    :param approved_by: Approver email.
    :param correlation_id: Correlation ID for tracing.
    :return: JSON with teams_posted, logged, and correlation_id.
    """
    payload: dict = {
        "ticket_id": ticket_id,
        "summary": summary,
        "action_taken": action_taken,
        "approved_by": approved_by,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return _call_tool_service("post_teams_summary", payload)


# Lookup table: function name → callable (used in the tool-call loop)
TOOL_CALLABLES: dict[str, callable] = {
    "query_ticket_context": query_ticket_context,
    "request_approval": request_approval,
    "execute_remediation": execute_remediation,
    "post_teams_summary": post_teams_summary,
}


# ---------------------------------------------------------------------------
# HTTP helper
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
# Helpers — Bicep / state
# ---------------------------------------------------------------------------


def _az_output(cmd: list[str]) -> str:
    az_exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run(  # noqa: S603
        [az_exe, *cmd[1:]], capture_output=True, text=True, check=True
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
    """Load agent ID + tool service URL from .agent-state.json if present."""
    state_path = REPO_ROOT / ".agent-state.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


# ---------------------------------------------------------------------------
# Agent turn — poll loop with client-side tool execution
# ---------------------------------------------------------------------------


def run_agent_turn(
    project_client: AIProjectClient,
    thread_id: str,
    agent_id: str,
    user_message: str,
) -> str:
    """Send a message, handle tool calls, and return the assistant's reply."""
    # Post user message
    project_client.agents.messages.create(
        thread_id=thread_id, role="user", content=user_message,
    )

    # Start a run
    run = project_client.agents.runs.create(thread_id=thread_id, agent_id=agent_id)

    # Poll until terminal state
    poll_count = 0
    while run.status in (RunStatus.QUEUED, RunStatus.IN_PROGRESS, RunStatus.REQUIRES_ACTION):
        poll_count += 1
        if run.status == RunStatus.REQUIRES_ACTION:
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            tool_outputs: list[ToolOutput] = []

            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                print(f"  -> Calling {fn_name}({json.dumps(fn_args, separators=(',', ':'))})")

                # Look up and call the real tool function
                fn = TOOL_CALLABLES.get(fn_name)
                if fn:
                    result = fn(**fn_args)
                else:
                    result = json.dumps({"error": f"Unknown function: {fn_name}"})

                tool_outputs.append(ToolOutput(tool_call_id=tc.id, output=result))

            run = project_client.agents.runs.submit_tool_outputs(
                thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs,
            )
        else:
            time.sleep(1)
            run = project_client.agents.runs.get(thread_id=thread_id, run_id=run.id)

    if run.status == RunStatus.FAILED:
        return f"[Run failed: {run.last_error}]"

    if run.status != RunStatus.COMPLETED:
        return f"[Run ended with status: {run.status}]"

    # Get the latest assistant message
    messages = project_client.agents.messages.list(thread_id=thread_id, order="desc")
    all_msgs = list(messages)
    for msg in all_msgs:
        if msg.role == MessageRole.AGENT:
            parts = []
            for block in msg.content:
                if hasattr(block, "text"):
                    parts.append(block.text.value)
            if parts:
                return "\n".join(parts)
    return "[No response]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    global _tool_service_url  # noqa: PLW0603

    import argparse

    parser = argparse.ArgumentParser(description="Chat with the IQ triage agent.")
    parser.add_argument("--resource-group", "-g", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--single", "-s", default="", help="Send a single message and exit.")
    args = parser.parse_args()

    # Resolve configuration
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
        print("ERROR: Set TOOL_SERVICE_URL, use --resource-group, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)
    if not agent_id:
        print("ERROR: Set AGENT_ID, use --agent-id, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project_endpoint}")
    print(f"Tools:    {_tool_service_url}")
    print(f"Agent:    {agent_id}")
    print()

    # Connect via AIProjectClient (Agent Framework v2 entry point)
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )
    thread = project_client.agents.threads.create()
    print(f"Thread:   {thread.id}")
    print()

    # Single-shot mode (for scripting / CI)
    if args.single:
        reply = run_agent_turn(project_client, thread.id, agent_id, args.single)
        print(reply)
        return

    # Interactive loop
    print("Type a message (or 'quit' to exit):")
    print("-" * 60)
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        reply = run_agent_turn(project_client, thread.id, agent_id, user_input)
        print(f"\nAgent> {reply}")


if __name__ == "__main__":
    main()
