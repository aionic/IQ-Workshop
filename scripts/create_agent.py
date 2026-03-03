# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-agents>=1.1.0",
#     "azure-identity>=1.15.0",
# ]
# ///
"""
create_agent.py — Register the IQ triage agent via the Foundry Agent SDK.

Architecture: Prompt Agent (LLM in Foundry) + OpenAPI Tools (FastAPI on Container Apps).
The agent uses gpt-5-mini and calls tool endpoints on the Container App.

Usage (uv auto-installs deps via PEP 723 inline metadata):

    $env:AZURE_AI_PROJECT_ENDPOINT = "https://<ai-services>.services.ai.azure.com/api/projects/<project>"
    $env:TOOL_SERVICE_URL = "https://<container-app-fqdn>"
    uv run scripts/create_agent.py

Or auto-discover from a Bicep deployment:

    uv run scripts/create_agent.py --resource-group rg-iq-lab-dev
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import OpenApiAnonymousAuthDetails, OpenApiTool
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAME = "iq-triage-agent"


def _az_output(cmd: list[str]) -> str:
    """Run an az CLI command and return stripped stdout."""
    result = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, check=True
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
        model_deployment = vals["model_deployment"]
    else:
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
        tool_service_url = os.environ.get("TOOL_SERVICE_URL", "")
        model_deployment = args.model

    if not project_endpoint:
        print("ERROR: Provide --resource-group or set AZURE_AI_PROJECT_ENDPOINT.", file=sys.stderr)
        sys.exit(1)
    if not tool_service_url:
        print("ERROR: Provide --resource-group or set TOOL_SERVICE_URL.", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project_endpoint}")
    print(f"Tools:    {tool_service_url}")
    print(f"Model:    {model_deployment}")
    print()

    # Load system prompt
    system_prompt = (REPO_ROOT / "foundry" / "prompts" / "system.md").read_text()

    # Load and patch OpenAPI spec with live tool service URL
    spec = json.loads((REPO_ROOT / "foundry" / "tools.openapi.json").read_text())
    spec["servers"][0]["url"] = tool_service_url

    # Connect to project via AgentsClient
    client = AgentsClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    # Build OpenAPI tool definitions
    openapi_tool = OpenApiTool(
        name="iq-lab-tools",
        description="IQ Lab tool endpoints for ticket triage and remediation",
        spec=spec,
        auth=OpenApiAnonymousAuthDetails(),
    )

    # Create prompt agent with OpenAPI tools
    agent = client.create_agent(
        model=model_deployment,
        name=AGENT_NAME,
        instructions=system_prompt,
        temperature=0.3,
        tools=openapi_tool.definitions,
    )
    print(f"Agent created: {agent.id}")
    print(f"  Name:  {agent.name}")
    print(f"  Model: {agent.model}")
    print()
    print("Test in the Foundry Agents playground:")
    print("  https://ai.azure.com")


if __name__ == "__main__":
    main()
