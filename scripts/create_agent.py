"""
create_agent.py — Register the IQ triage agent via the Foundry Agent SDK.

Architecture: Prompt Agent (LLM in Foundry) + OpenAPI Tools (FastAPI on Container Apps)
The agent uses gpt-5-mini and calls tool endpoints on the Container App.

Usage:
    $env:AZURE_AI_PROJECT_ENDPOINT = "https://ai-iq-lab-dev.services.ai.azure.com/api/projects/iq-lab-project"
    $env:TOOL_SERVICE_URL = "https://ca-tools-iq-lab-dev.<hash>.westus3.azurecontainerapps.io"
    uv run python scripts/create_agent.py

Prerequisites:
    uv pip install azure-ai-projects azure-identity
"""

import json
import os
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import OpenApiTool, OpenApiAnonymousAuthDetails
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ENDPOINT = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
TOOL_SERVICE_URL = os.environ.get("TOOL_SERVICE_URL", "")
MODEL_DEPLOYMENT = os.environ.get("AI_MODEL_DEPLOYMENT", "gpt-5-mini")
AGENT_NAME = "iq-triage-agent"


def main() -> None:
    if not PROJECT_ENDPOINT:
        print("ERROR: Set AZURE_AI_PROJECT_ENDPOINT env var", file=sys.stderr)
        sys.exit(1)
    if not TOOL_SERVICE_URL:
        print("ERROR: Set TOOL_SERVICE_URL env var", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {PROJECT_ENDPOINT}")
    print(f"Tools:    {TOOL_SERVICE_URL}")
    print(f"Model:    {MODEL_DEPLOYMENT}")
    print()

    # Load system prompt
    system_prompt = (REPO_ROOT / "foundry" / "prompts" / "system.md").read_text()

    # Load and patch OpenAPI spec with live tool service URL
    spec = json.loads((REPO_ROOT / "foundry" / "tools.openapi.json").read_text())
    spec["servers"][0]["url"] = TOOL_SERVICE_URL

    # Connect to project
    client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )

    # Create prompt agent with OpenAPI tools
    agent = client.agents.create_agent(
        model=MODEL_DEPLOYMENT,
        name=AGENT_NAME,
        instructions=system_prompt,
        temperature=0.3,
        tools=[
            OpenApiTool(
                name="iq-lab-tools",
                description="IQ Lab tool endpoints for ticket triage and remediation",
                spec=spec,
                auth=OpenApiAnonymousAuthDetails(),
            )
        ],
    )
    print(f"Agent created: {agent.id}")
    print(f"  Name:  {agent.name}")
    print(f"  Model: {agent.model}")
    print()
    print("Test in the Foundry Agents playground:")
    print("  https://ai.azure.com")


if __name__ == "__main__":
    main()
