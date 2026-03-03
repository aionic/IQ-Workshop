# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-agents>=1.1.0",
#     "azure-identity>=1.15.0",
# ]
# ///
"""
create_agent.py — Register the IQ triage agent via the Foundry Agent SDK.

Architecture: Prompt Agent (LLM in Foundry) + Function Tools (Responses API compatible).
The agent uses gpt-5-mini with function tool definitions. A client program
(chat_agent.py) handles tool execution by calling the FastAPI service on ACA.

Usage (uv auto-installs deps via PEP 723 inline metadata):

    uv run scripts/create_agent.py --resource-group rg-iq-lab-dev

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

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionDefinition, FunctionToolDefinition
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAME = "iq-triage-agent"

# ---------------------------------------------------------------------------
# Function tool definitions — Responses API compatible (type="function")
# Each maps 1:1 to a FastAPI endpoint on the self-hosted tool service.
# ---------------------------------------------------------------------------

FUNCTION_TOOLS: list[FunctionToolDefinition] = [
    FunctionToolDefinition(
        function=FunctionDefinition(
            name="queryTicketContext",
            description=(
                "Query ticket context with linked anomaly and device data. "
                "Returns minimal structured fields for a given ticket: ticket "
                "metadata, anomaly metrics, and device/site info."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The ticket identifier (e.g. TKT-0042)",
                    },
                },
                "required": ["ticket_id"],
            },
        )
    ),
    FunctionToolDefinition(
        function=FunctionDefinition(
            name="requestApproval",
            description=(
                "Request approval for a proposed remediation action. "
                "Returns an approval_token and sets status to PENDING."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "Ticket to remediate",
                    },
                    "proposed_action": {
                        "type": "string",
                        "description": "Action to perform (e.g. restart_bgp_sessions)",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this action is appropriate",
                    },
                    "correlation_id": {
                        "type": "string",
                        "description": "Optional correlation ID for tracing",
                    },
                },
                "required": ["ticket_id", "proposed_action", "rationale"],
            },
        )
    ),
    FunctionToolDefinition(
        function=FunctionDefinition(
            name="executeRemediation",
            description=(
                "Execute an approved remediation action. Requires a valid, "
                "APPROVED approval_token. Logs the outcome and updates ticket status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "description": "The action to execute",
                    },
                    "approved_by": {
                        "type": "string",
                        "description": "Email of the person who approved",
                    },
                    "approval_token": {
                        "type": "string",
                        "description": "Token from requestApproval (must be APPROVED)",
                    },
                    "correlation_id": {
                        "type": "string",
                        "description": "Correlation ID for tracing",
                    },
                },
                "required": [
                    "ticket_id",
                    "action",
                    "approved_by",
                    "approval_token",
                    "correlation_id",
                ],
            },
        )
    ),
    FunctionToolDefinition(
        function=FunctionDefinition(
            name="postTeamsSummary",
            description=(
                "Post a remediation summary to Microsoft Teams. "
                "Returns logged=true and teams_posted=false (stub) unless a "
                "Teams webhook is configured."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "summary": {"type": "string", "description": "Summary text"},
                    "action_taken": {
                        "type": "string",
                        "description": "Action that was executed",
                    },
                    "approved_by": {
                        "type": "string",
                        "description": "Approver email",
                    },
                    "correlation_id": {
                        "type": "string",
                        "description": "Correlation ID for tracing",
                    },
                },
                "required": [
                    "ticket_id",
                    "summary",
                    "action_taken",
                    "approved_by",
                    "correlation_id",
                ],
            },
        )
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
        default=os.environ.get("AI_MODEL_DEPLOYMENT", "gpt-5-mini"),
        help="Model deployment name (default: gpt-5-mini).",
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

    # Connect to project via AgentsClient
    client = AgentsClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    # Create prompt agent with function tools (Responses API compatible)
    agent = client.create_agent(
        model=model_deployment,
        name=AGENT_NAME,
        instructions=system_prompt,
        temperature=0.3,
        tools=FUNCTION_TOOLS,
    )
    print(f"Agent created: {agent.id}")
    print(f"  Name:  {agent.name}")
    print(f"  Model: {agent.model}")
    print()

    # Save agent ID + tool service URL for use by chat_agent.py
    state = {"agent_id": agent.id, "tool_service_url": tool_service_url}
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
