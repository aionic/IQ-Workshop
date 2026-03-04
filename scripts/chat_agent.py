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
chat_agent.py — Interactive chat with the IQ triage agent via the Responses API.

Uses the **new** Agent API with ``openai_client.responses.create()`` and
``openai_client.conversations.create()`` — NOT the classic Assistants
threads/runs model.

Supports two tool modes based on how the agent was registered (create_agent.py):

**MCP mode** (default):
  The Foundry Agent Service calls the MCP server directly via Streamable HTTP.
  This client handles MCP approval requests — auto-approves safe tools
  (query_ticket_context, request_approval, post_teams_summary) and prompts the
  human operator for ``execute_remediation`` (human-in-the-loop).

**Legacy mode** (``--legacy`` or ``tool_mode=legacy`` in ``.agent-state.json``):
  The agent uses FunctionTool definitions.  This client intercepts
  ``function_call`` outputs in the response, calls the FastAPI REST endpoints
  over HTTP, and submits ``function_call_output`` items back via the
  Responses API.

Usage:

    uv run scripts/chat_agent.py --resource-group rg-iq-lab-dev

Legacy mode:

    uv run scripts/chat_agent.py --resource-group rg-iq-lab-dev --legacy

Or with explicit env vars:

    $env:AZURE_AI_PROJECT_ENDPOINT = "..."
    $env:TOOL_SERVICE_URL = "..."
    $env:AGENT_NAME = "iq-triage-agent"
    uv run scripts/chat_agent.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses.response_input_param import McpApprovalResponse

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAME = "iq-triage-agent"

# ---------------------------------------------------------------------------
# MCP approval policy — auto-approve safe tools, require human for mutations
# ---------------------------------------------------------------------------
AUTO_APPROVE_TOOLS = {"query_ticket_context", "request_approval", "post_teams_summary"}
HUMAN_APPROVE_TOOLS = {"execute_remediation"}

# ---------------------------------------------------------------------------
# Module-level tool service URL — set at runtime before tool functions are
# called.  The legacy tool functions read this to build HTTP URLs.
# ---------------------------------------------------------------------------
_tool_service_url: str = ""

# Map tool function names → FastAPI endpoint paths (legacy mode only)
FUNCTION_TO_ENDPOINT: dict[str, tuple[str, str]] = {
    "query_ticket_context": ("POST", "/tools/query-ticket-context"),
    "request_approval": ("POST", "/tools/request-approval"),
    "execute_remediation": ("POST", "/tools/execute-remediation"),
    "post_teams_summary": ("POST", "/tools/post-teams-summary"),
}


# ---------------------------------------------------------------------------
# HTTP helper — legacy mode only
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
    """Load agent name + tool service URL from .agent-state.json if present."""
    state_path = REPO_ROOT / ".agent-state.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


# ---------------------------------------------------------------------------
# Agent turn — MCP mode (approval flow, no client-side tool dispatch)
# ---------------------------------------------------------------------------


def run_turn_mcp(
    openai_client,
    agent_name: str,
    conversation_id: str,
    user_message: str,
) -> str:
    """MCP mode: send a message, handle MCP tool approvals, return reply.

    The Foundry Agent Service calls the MCP server directly.  This client
    only handles approval/rejection of each tool invocation:
    - Tools in AUTO_APPROVE_TOOLS are approved automatically.
    - Tools in HUMAN_APPROVE_TOOLS prompt the operator for confirmation.
    - Unknown tools are rejected.
    """
    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}

    # Send user message via the Responses API
    response = openai_client.responses.create(
        conversation=conversation_id,
        input=user_message,
        extra_body=agent_ref,
    )

    # Loop: handle approval requests until the agent produces a final response
    while True:
        approval_inputs: list[McpApprovalResponse] = []
        for item in response.output:
            if item.type == "mcp_approval_request":
                fn_name = item.name
                print(f"  -> MCP tool: {fn_name}({item.arguments})")

                if fn_name in AUTO_APPROVE_TOOLS:
                    approved = True
                    print("     Auto-approved")
                elif fn_name in HUMAN_APPROVE_TOOLS:
                    try:
                        choice = input(f"     Approve '{fn_name}'? [y/N] ").strip().lower()
                        approved = choice in ("y", "yes")
                    except (EOFError, KeyboardInterrupt):
                        approved = False
                    print(f"     {'APPROVED' if approved else 'REJECTED'} by operator")
                else:
                    print(f"     Unknown tool '{fn_name}' — rejected")
                    approved = False

                approval_inputs.append(
                    McpApprovalResponse(
                        type="mcp_approval_response",
                        approve=approved,
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
        return f"[Response failed: {response.error}]"
    if response.status == "incomplete":
        return f"[Response incomplete: {response.incomplete_details}]"

    return response.output_text or "[No response]"


# ---------------------------------------------------------------------------
# Agent turn — Legacy mode (function call dispatch via HTTP)
# ---------------------------------------------------------------------------


def run_turn_legacy(
    openai_client,
    agent_name: str,
    conversation_id: str,
    user_message: str,
) -> str:
    """Legacy mode: send a message, handle function calls via HTTP, return reply."""
    agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}
    turn_correlation_id = str(uuid.uuid4())

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

                print(f"  -> Calling {fn_name}({json.dumps(fn_args, separators=(',', ':'))})")
                result = _call_tool_service(fn_name, fn_args)

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
        return f"[Response failed: {response.error}]"

    return response.output_text or "[No response]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    global _tool_service_url  # noqa: PLW0603

    import argparse

    parser = argparse.ArgumentParser(description="Chat with the IQ triage agent.")
    parser.add_argument("--resource-group", "-g", default="")
    parser.add_argument("--agent-name", default="", help="Agent name (default: from state file).")
    parser.add_argument("--single", "-s", default="", help="Send a single message and exit.")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Force legacy FunctionTool mode (HTTP dispatch) instead of MCP.",
    )
    args = parser.parse_args()

    # Resolve configuration
    state = _load_agent_state()
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    _tool_service_url = state.get("tool_service_url", os.environ.get("TOOL_SERVICE_URL", ""))
    agent_name = args.agent_name or state.get("agent_name", os.environ.get("AGENT_NAME", AGENT_NAME))

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
        print("ERROR: Set TOOL_SERVICE_URL for legacy mode, use --resource-group, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)
    if not agent_name:
        print("ERROR: Set AGENT_NAME, use --agent-name, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project_endpoint}")
    print(f"Tools:    {_tool_service_url}")
    print(f"Agent:    {agent_name}")
    print(f"Mode:     {'MCP (approval flow)' if tool_mode == 'mcp' else 'Legacy (HTTP dispatch)'}")
    print()

    # Connect via AIProjectClient (new Agent API) + OpenAI client
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
    openai_client = project_client.get_openai_client()

    # Create a conversation (replaces threads in the classic API)
    conversation = openai_client.conversations.create()
    print(f"Conversation: {conversation.id}")
    print()

    # Helper: dispatch to the right turn function based on mode
    def _turn(msg: str) -> str:
        if tool_mode == "mcp":
            return run_turn_mcp(openai_client, agent_name, conversation.id, msg)
        return run_turn_legacy(openai_client, agent_name, conversation.id, msg)

    # Single-shot mode (for scripting / CI)
    if args.single:
        reply = _turn(args.single)
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

        reply = _turn(user_input)
        print(f"\nAgent> {reply}")


if __name__ == "__main__":
    main()
