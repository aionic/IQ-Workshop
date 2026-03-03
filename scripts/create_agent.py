# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-projects>=2.0.0b2",
#     "azure-ai-agents>=1.2.0b2",
#     "azure-identity>=1.15.0",
# ]
# ///
"""
create_agent.py — Register the IQ triage agent via the Agent Framework v2 SDK.

Architecture: Prompt Agent (LLM in Foundry) + MCP Tools (default) or Function Tools (legacy).

Default mode (MCP):
  The agent uses gpt-4.1-mini with an MCP tool definition pointing at the
  co-hosted MCP server on the FastAPI tool service. The Foundry Agent Service
  calls the MCP server directly over Streamable HTTP — no client-side tool loop.

Legacy mode (--legacy):
  Falls back to ``FunctionTool`` definitions auto-generated from Python stubs.
  A client program (chat_agent.py) handles tool execution by calling the FastAPI
  service on ACA.

Usage (uv auto-installs deps via PEP 723 inline metadata):

    uv run scripts/create_agent.py --resource-group rg-iq-lab-dev

Legacy mode:

    uv run scripts/create_agent.py --resource-group rg-iq-lab-dev --legacy

Or with explicit env vars:

    $env:AZURE_AI_PROJECT_ENDPOINT = "https://<ai-services>.services.ai.azure.com/api/projects/<project>"
    $env:TOOL_SERVICE_URL = "https://<container-app-fqdn>"
    uv run scripts/create_agent.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from azure.ai.agents.models import FunctionTool
from azure.ai.projects import AIProjectClient
from azure.ai.projects.tools.mcp import MCPTool
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAME = "iq-triage-agent"


# ---------------------------------------------------------------------------
# Tool function stubs — FunctionTool auto-generates JSON Schema from the
# typed signatures + :param docstrings.  These are *not* executed at
# registration time; the real implementations live in chat_agent.py where
# they call the FastAPI service over HTTP.
# ---------------------------------------------------------------------------


def query_ticket_context(ticket_id: str) -> str:
    """
    Query ticket context with linked anomaly and device data.
    Returns minimal structured fields for a given ticket: ticket metadata,
    anomaly metrics, and device/site info.

    :param ticket_id: The ticket identifier (e.g. TKT-0042).
    :return: JSON with ticket metadata, anomaly metrics, and device/site info.
    """
    raise NotImplementedError("Stub — executed via HTTP in chat_agent.py")


def request_approval(
    ticket_id: str,
    proposed_action: str,
    rationale: str,
    correlation_id: str = "",
) -> str:
    """
    Request approval for a proposed remediation action.
    Returns an approval_token and sets status to PENDING.

    :param ticket_id: Ticket to remediate.
    :param proposed_action: Action to perform (e.g. restart_bgp_sessions).
    :param rationale: Why this action is appropriate.
    :param correlation_id: Optional correlation ID for tracing.
    :return: JSON with remediation_id, approval_token, and status.
    """
    raise NotImplementedError("Stub — executed via HTTP in chat_agent.py")


def execute_remediation(
    ticket_id: str,
    action: str,
    approved_by: str,
    approval_token: str,
    correlation_id: str = "",
) -> str:
    """
    Execute an approved remediation action. Requires a valid, APPROVED
    approval_token. Logs the outcome and updates ticket status.

    :param ticket_id: The ticket identifier.
    :param action: The action to execute.
    :param approved_by: Email of the person who approved.
    :param approval_token: Token from request_approval (must be APPROVED).
    :param correlation_id: Correlation ID for tracing.
    :return: JSON with remediation_id, outcome, and executed_utc.
    """
    raise NotImplementedError("Stub — executed via HTTP in chat_agent.py")


def post_teams_summary(
    ticket_id: str,
    summary: str,
    action_taken: str,
    approved_by: str,
    correlation_id: str = "",
) -> str:
    """
    Post a remediation summary to Microsoft Teams. Returns logged=true and
    teams_posted=false (stub) unless a Teams webhook is configured.

    :param ticket_id: The ticket identifier.
    :param summary: Summary text.
    :param action_taken: Action that was executed.
    :param approved_by: Approver email.
    :param correlation_id: Correlation ID for tracing.
    :return: JSON with teams_posted, logged, and correlation_id.
    """
    raise NotImplementedError("Stub — executed via HTTP in chat_agent.py")


# Build tool definitions from the stub functions
TOOL_FUNCTIONS = FunctionTool(
    functions={query_ticket_context, request_approval, execute_remediation, post_teams_summary}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _az_output(cmd: list[str]) -> str:
    """Run an az CLI command and return stripped stdout."""
    az_exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run(  # noqa: S603
        [az_exe, *cmd[1:]], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _resolve_from_bicep(resource_group: str) -> dict[str, str]:
    """Fetch Bicep deployment outputs from the most recent deployment."""
    print(f"Resolving values from Bicep outputs in {resource_group}...")
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
        "model_deployment": outputs["aiModelDeploymentName"]["value"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the IQ triage agent in Foundry.")
    parser.add_argument(
        "--resource-group", "-g",
        default=os.environ.get("RESOURCE_GROUP", ""),
        help="Azure RG to auto-discover Bicep outputs (default: use env vars).",
    )
    parser.add_argument(
        "--model", "-m",
        default=os.environ.get("AI_MODEL_DEPLOYMENT", "gpt-4.1-mini"),
        help="Model deployment name (default: gpt-4.1-mini).",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy FunctionTool definitions instead of MCP.",
    )
    args = parser.parse_args()

    # --- Resolve endpoints: either from Bicep outputs or env vars ---
    if args.resource_group:
        vals = _resolve_from_bicep(args.resource_group)
        project_endpoint = vals["project_endpoint"]
        tool_service_url = vals["tool_service_url"]
        # CLI --model takes precedence; fall back to Bicep output
        model_deployment = (
            args.model
            if args.model != parser.get_default("model")
            else vals["model_deployment"]
        )
    else:
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
        tool_service_url = os.environ.get("TOOL_SERVICE_URL", "")
        model_deployment = args.model

    if not project_endpoint:
        print("ERROR: Provide --resource-group or set AZURE_AI_PROJECT_ENDPOINT.", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project_endpoint}")
    print(f"Tools:    {tool_service_url}")
    print(f"Model:    {model_deployment}")
    print()

    # Load system prompt
    system_prompt = (REPO_ROOT / "foundry" / "prompts" / "system.md").read_text()

    # Connect via AIProjectClient (Agent Framework v2 entry point)
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    # --- Build tool definitions: MCP (default) or legacy FunctionTool ---
    if args.legacy:
        print("Mode: Legacy (FunctionTool)")
        tools = TOOL_FUNCTIONS.definitions
        tool_resources = None
    else:
        print("Mode: MCP (Streamable HTTP)")
        mcp_server_url = f"{tool_service_url}/mcp"
        mcp_tool = MCPTool(
            server_label="iq-tools",
            server_url=mcp_server_url,
            require_approval="always",
        )
        tools = mcp_tool.definitions
        tool_resources = mcp_tool.resources
        print(f"  MCP URL: {mcp_server_url}")
        print(f"  Approval: always (human-in-the-loop for execute_remediation)")

    # Create prompt agent
    agent = project_client.agents.create_agent(
        model=model_deployment,
        name=AGENT_NAME,
        instructions=system_prompt,
        temperature=0.3,
        tools=tools,
        tool_resources=tool_resources,
    )
    print(f"Agent created: {agent.id}")
    print(f"  Name:  {agent.name}")
    print(f"  Model: {agent.model}")
    print()

    # Save agent ID + tool service URL for use by chat_agent.py
    state = {
        "agent_id": agent.id,
        "tool_service_url": tool_service_url,
        "tool_mode": "legacy" if args.legacy else "mcp",
    }
    if not args.legacy and tool_resources:
        state["mcp_server_url"] = f"{tool_service_url}/mcp"
    state_path = REPO_ROOT / ".agent-state.json"
    state_path.write_text(json.dumps(state, indent=2))
    print(f"Agent state saved to {state_path}")
    print()
    print("Run the agent interactively:")
    print(f"  uv run scripts/chat_agent.py --resource-group {args.resource_group or '<rg>'}")
    print()
    print("Or test in the Foundry Agents playground:")
    print("  https://ai.azure.com")


if __name__ == "__main__":
    main()
