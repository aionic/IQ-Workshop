# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-agents>=1.1.0",
#     "azure-identity>=1.15.0",
#     "httpx>=0.27",
# ]
# ///
"""
chat_agent.py — Interactive chat loop with client-side tool execution.

Connects to the Foundry agent created by create_agent.py, sends user messages,
intercepts requires_action events, calls the FastAPI tool service, and submits
tool outputs back to the agent run.

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
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import ToolOutput
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent

# Map function tool names → FastAPI endpoint paths
FUNCTION_TO_ENDPOINT: dict[str, tuple[str, str]] = {
    "queryTicketContext": ("POST", "/tools/query-ticket-context"),
    "requestApproval": ("POST", "/tools/request-approval"),
    "executeRemediation": ("POST", "/tools/execute-remediation"),
    "postTeamsSummary": ("POST", "/tools/post-teams-summary"),
}


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


def call_tool_service(base_url: str, function_name: str, arguments: dict) -> str:
    """Call a FastAPI tool endpoint and return the JSON response as a string."""
    if function_name not in FUNCTION_TO_ENDPOINT:
        return json.dumps({"error": f"Unknown function: {function_name}"})

    method, path = FUNCTION_TO_ENDPOINT[function_name]
    url = f"{base_url}{path}"

    try:
        resp = httpx.request(method, url, json=arguments, timeout=30)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "detail": e.response.text})
    except httpx.RequestError as e:
        return json.dumps({"error": f"Request failed: {e}"})


def run_agent_turn(
    client: AgentsClient,
    thread_id: str,
    agent_id: str,
    tool_service_url: str,
    user_message: str,
) -> str:
    """Send a message, handle tool calls, and return the assistant's reply."""
    # Post user message
    client.messages.create(thread_id=thread_id, role="user", content=user_message)

    # Start a run
    run = client.runs.create(thread_id=thread_id, agent_id=agent_id)

    # Poll until terminal state
    while run.status in ("queued", "in_progress", "requires_action"):
        if run.status == "requires_action":
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            tool_outputs: list[ToolOutput] = []

            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                print(f"  -> Calling {fn_name}({json.dumps(fn_args, separators=(',', ':'))})")

                result = call_tool_service(tool_service_url, fn_name, fn_args)
                tool_outputs.append(ToolOutput(tool_call_id=tc.id, output=result))

            run = client.runs.submit_tool_outputs(
                thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs
            )
        else:
            time.sleep(1)
            run = client.runs.get(thread_id=thread_id, run_id=run.id)

    if run.status == "failed":
        return f"[Run failed: {run.last_error}]"

    # Get the latest assistant message
    messages = client.messages.list(thread_id=thread_id)
    for msg in messages.data:
        if msg.role == "assistant":
            parts = []
            for block in msg.content:
                if hasattr(block, "text"):
                    parts.append(block.text.value)
            if parts:
                return "\n".join(parts)
    return "[No response]"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Chat with the IQ triage agent.")
    parser.add_argument("--resource-group", "-g", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--single", "-s", default="", help="Send a single message and exit.")
    args = parser.parse_args()

    # Resolve configuration
    state = _load_agent_state()
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    tool_service_url = state.get("tool_service_url", os.environ.get("TOOL_SERVICE_URL", ""))
    agent_id = args.agent_id or state.get("agent_id", os.environ.get("AGENT_ID", ""))

    if args.resource_group:
        vals = _resolve_from_bicep(args.resource_group)
        project_endpoint = project_endpoint or vals["project_endpoint"]
        tool_service_url = tool_service_url or vals["tool_service_url"]

    if not project_endpoint:
        print("ERROR: Set AZURE_AI_PROJECT_ENDPOINT or use --resource-group.", file=sys.stderr)
        sys.exit(1)
    if not tool_service_url:
        print("ERROR: Set TOOL_SERVICE_URL, use --resource-group, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)
    if not agent_id:
        print("ERROR: Set AGENT_ID, use --agent-id, or run create_agent.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project_endpoint}")
    print(f"Tools:    {tool_service_url}")
    print(f"Agent:    {agent_id}")
    print()

    client = AgentsClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )
    thread = client.threads.create()
    print(f"Thread:   {thread.id}")
    print()

    # Single-shot mode (for scripting / CI)
    if args.single:
        reply = run_agent_turn(client, thread.id, agent_id, tool_service_url, args.single)
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

        reply = run_agent_turn(client, thread.id, agent_id, tool_service_url, user_input)
        print(f"\nAgent> {reply}")


if __name__ == "__main__":
    main()
