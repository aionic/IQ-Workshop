# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-projects>=2.0.0b2",
#     "azure-identity>=1.15.0",
# ]
# ///
"""
create_agent.py — Register the IQ triage agent as a Foundry Prompt Agent.

Uses the **new** Agent API (``AIProjectClient.agents.create_version``) which
creates agents visible in the new Foundry portal experience — NOT classic
Assistants-based agents that appear under "Classic Agents".

Default mode (MCP):
  Creates a ``PromptAgentDefinition`` with ``MCPTool`` pointing at the
  co-hosted MCP server on the FastAPI tool service.  ``require_approval``
  is set to ``"always"`` so every tool call surfaces for client-side
  approval/rejection (the chat client auto-approves safe tools and prompts
  the operator for ``execute_remediation``).

Legacy mode (--legacy):
  Creates a ``PromptAgentDefinition`` with ``FunctionTool`` definitions.
  ``chat_agent.py`` handles tool execution by calling the FastAPI service
  via HTTP.

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

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FunctionTool,
    MCPTool,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAME = "iq-triage-agent"


# ---------------------------------------------------------------------------
# Function tool JSON schemas — used only in legacy mode.
# These match the FastAPI endpoint signatures in services/api-tools/app/main.py.
# ---------------------------------------------------------------------------

LEGACY_TOOLS: list[FunctionTool] = [
    FunctionTool(
        name="query_ticket_context",
        description=(
            "Query ticket context with linked anomaly and device data. "
            "Returns minimal structured fields for a given ticket."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket identifier (e.g. TKT-0042).",
                },
            },
            "required": ["ticket_id"],
        },
    ),
    FunctionTool(
        name="request_approval",
        description=(
            "Request approval for a proposed remediation action. "
            "Returns an approval_token and sets status to PENDING."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Ticket to remediate."},
                "proposed_action": {"type": "string", "description": "Action to perform (e.g. restart_bgp_sessions)."},
                "rationale": {"type": "string", "description": "Why this action is appropriate."},
                "correlation_id": {"type": "string", "description": "Optional correlation ID for tracing."},
            },
            "required": ["ticket_id", "proposed_action", "rationale"],
        },
    ),
    FunctionTool(
        name="execute_remediation",
        description=(
            "Execute an approved remediation action. Requires a valid, APPROVED "
            "approval_token. Logs the outcome and updates ticket status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "The ticket identifier."},
                "action": {"type": "string", "description": "The action to execute."},
                "approved_by": {"type": "string", "description": "Email of the person who approved."},
                "approval_token": {"type": "string", "description": "Token from request_approval (must be APPROVED)."},
                "correlation_id": {"type": "string", "description": "Correlation ID for tracing."},
            },
            "required": ["ticket_id", "action", "approved_by", "approval_token"],
        },
    ),
    FunctionTool(
        name="post_teams_summary",
        description=(
            "Post a remediation summary to Microsoft Teams. Returns logged=true "
            "and teams_posted=false (stub) unless a Teams webhook is configured."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "The ticket identifier."},
                "summary": {"type": "string", "description": "Summary text."},
                "action_taken": {"type": "string", "description": "Action that was executed."},
                "approved_by": {"type": "string", "description": "Approver email."},
                "correlation_id": {"type": "string", "description": "Correlation ID for tracing."},
            },
            "required": ["ticket_id", "summary", "action_taken", "approved_by"],
        },
    ),
]


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

    # --- Build tool definitions: MCP (default) or legacy FunctionTool ---
    if args.legacy:
        print("Mode: Legacy (FunctionTool)")
        tools = LEGACY_TOOLS
    else:
        print("Mode: MCP (Streamable HTTP)")
        mcp_server_url = f"{tool_service_url}/mcp"
        mcp_tool = MCPTool(
            server_label="iq-tools",
            server_url=mcp_server_url,
            require_approval="always",
        )
        tools = [mcp_tool]
        print(f"  MCP URL: {mcp_server_url}")
        print(f"  Approval: always (human-in-the-loop for execute_remediation)")

    # Connect via AIProjectClient (new Agent API)
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )

    # Create prompt agent version (new-style — visible in Foundry portal)
    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        description="IQ network triage agent — triages anomalies and proposes safe remediations.",
        definition=PromptAgentDefinition(
            model=model_deployment,
            instructions=system_prompt,
            tools=tools,
            temperature=0.3,
        ),
    )
    print()
    print(f"Agent created (new-style Prompt Agent):")
    print(f"  Name:    {agent.name}")
    print(f"  Version: {agent.version}")
    print(f"  ID:      {agent.id}")
    print()

    # Save agent state for use by chat_agent.py
    state = {
        "agent_name": agent.name,
        "agent_version": agent.version,
        "tool_service_url": tool_service_url,
        "tool_mode": "legacy" if args.legacy else "mcp",
    }
    if not args.legacy:
        state["mcp_server_url"] = f"{tool_service_url}/mcp"
    state_path = REPO_ROOT / ".agent-state.json"
    state_path.write_text(json.dumps(state, indent=2))
    print(f"Agent state saved to {state_path}")
    print()
    print("Run the agent interactively:")
    print(f"  uv run scripts/chat_agent.py --resource-group {args.resource_group or '<rg>'}")
    print()
    print("Or chat in the Foundry Agents playground:")
    print("  https://ai.azure.com")


if __name__ == "__main__":
    main()
