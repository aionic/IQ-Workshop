#Requires -Version 7.0
<#
.SYNOPSIS
    Register the IQ triage agent in Azure AI Foundry Agent Service.

.DESCRIPTION
    Creates (or updates) the Foundry hosted agent using the Azure CLI and the
    agent definition in foundry/agent.yaml. Sets the tool service URL from the
    live Container App deployment.

    Prerequisites:
      - Azure CLI logged in with access to the AI Foundry project
      - AI Services resource deployed (ai-iq-lab-dev)
      - Container App running with healthy /health endpoint

.PARAMETER ResourceGroup
    Resource group (default: rg-iq-lab-dev).

.PARAMETER ProjectName
    AI Foundry project name. If not provided, you'll be prompted.

.PARAMETER AgentName
    Name for the agent (default: iq-triage-agent).

.PARAMETER ModelDeployment
    Model deployment name (default: gpt-5-mini).

.EXAMPLE
    .\register-agent.ps1

.EXAMPLE
    .\register-agent.ps1 -ProjectName my-foundry-project -AgentName iq-triage-agent
#>

[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-iq-lab-dev",
    [string]$ProjectName,
    [string]$AgentName = "iq-triage-agent",
    [string]$ModelDeployment = "gpt-5-mini"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path

function Write-Step([string]$msg) { Write-Host "`n===> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------
# Pre-flight: Resolve live values
# -----------------------------------------------------------------------
Write-Step "Resolving deployment values"

# Tool service URL
$toolServiceUrl = az containerapp show `
    -n ca-tools-iq-lab-dev -g $ResourceGroup `
    --query "properties.configuration.ingress.fqdn" -o tsv 2>$null
if (-not $toolServiceUrl) { throw "Container App not found. Deploy infrastructure first." }
$toolServiceUrl = "https://$toolServiceUrl"
Write-Ok "Tool Service: $toolServiceUrl"

# Health check
try {
    $health = Invoke-RestMethod -Uri "$toolServiceUrl/health" -TimeoutSec 10
    if ($health.db -ne "connected") {
        Write-Warn "Tool service health: db=$($health.db) — DB may need attention"
    }
    else {
        Write-Ok "Tool service healthy (db=connected)"
    }
}
catch {
    throw "Tool service at $toolServiceUrl is not responding: $_"
}

# AI Services endpoint
$aiEndpoint = az cognitiveservices account show `
    -n ai-iq-lab-dev -g $ResourceGroup `
    --query "properties.endpoint" -o tsv 2>$null
if (-not $aiEndpoint) { throw "AI Services resource 'ai-iq-lab-dev' not found." }
Write-Ok "AI Services: $aiEndpoint"

# -----------------------------------------------------------------------
# Load system prompt
# -----------------------------------------------------------------------
$systemPromptPath = Join-Path $RepoRoot "foundry\prompts\system.md"
$systemPrompt = Get-Content $systemPromptPath -Raw
Write-Ok "System prompt loaded ($($systemPrompt.Length) chars)"

# -----------------------------------------------------------------------
# Load OpenAPI spec and patch server URL
# -----------------------------------------------------------------------
$openApiPath = Join-Path $RepoRoot "foundry\tools.openapi.json"
$openApiSpec = Get-Content $openApiPath -Raw | ConvertFrom-Json
$openApiSpec.servers[0].url = $toolServiceUrl
$openApiSpec.servers[0].description = "Azure Container Apps deployment (live)"
$patchedSpecPath = Join-Path $env:TEMP "iq-tools-openapi-patched.json"
$openApiSpec | ConvertTo-Json -Depth 20 | Set-Content $patchedSpecPath -Encoding UTF8
Write-Ok "OpenAPI spec patched with live URL: $toolServiceUrl"

# -----------------------------------------------------------------------
# Resolve Foundry project
# -----------------------------------------------------------------------
Write-Step "Resolving AI Foundry project"

if (-not $ProjectName) {
    Write-Host ""
    Write-Host "  No AI Foundry project specified." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To create the agent, you need an AI Foundry project." -ForegroundColor Yellow
    Write-Host "  You can create one at: https://ai.azure.com" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  === Manual Agent Registration (Recommended for Workshop) ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Since the Foundry Agent Service uses the AI Foundry portal for" -ForegroundColor White
    Write-Host "  agent creation, follow these steps:" -ForegroundColor White
    Write-Host ""
    Write-Host "  1. Go to https://ai.azure.com" -ForegroundColor White
    Write-Host "  2. Create or select a project in the westus3 region" -ForegroundColor White
    Write-Host "  3. Navigate to 'Agents' in the left menu" -ForegroundColor White
    Write-Host "  4. Click '+ New Agent'" -ForegroundColor White
    Write-Host "  5. Configure the agent with these values:" -ForegroundColor White
    Write-Host ""
}

# -----------------------------------------------------------------------
# Output agent configuration for portal registration
# -----------------------------------------------------------------------
Write-Step "Agent Configuration Summary"

$config = @"

  ┌──────────────────────────────────────────────────────────────────┐
  │                    FOUNDRY AGENT CONFIGURATION                   │
  ├──────────────────────────────────────────────────────────────────┤
  │                                                                  │
  │  Agent Name:        $AgentName
  │  Model Deployment:  $ModelDeployment
  │  AI Services:       $aiEndpoint
  │  Tool Service URL:  $toolServiceUrl
  │                                                                  │
  │  ── System Prompt ──                                             │
  │  File: foundry/prompts/system.md                                 │
  │  (Copy the full contents into the agent's Instructions field)    │
  │                                                                  │
  │  ── OpenAPI Tool ──                                              │
  │  File: foundry/tools.openapi.json                                │
  │  (Upload as an OpenAPI tool definition)                          │
  │  Server URL has been patched to: $toolServiceUrl
  │  Patched spec saved to: $patchedSpecPath
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘

"@
Write-Host $config -ForegroundColor White

# -----------------------------------------------------------------------
# Generate az cli commands (for SDK/CLI-based registration)
# -----------------------------------------------------------------------
Write-Step "CLI Commands (if using Foundry Agent SDK)"

Write-Host @"

  # Install the Foundry Agent SDK (if needed)
  uv pip install azure-ai-projects azure-identity

  # Python quick-start to create the agent programmatically:
  # See: scripts/create_agent.py (generated below)

  # Or via REST API:
  # POST {project-endpoint}/agents?api-version=2025-05-01
  # Body: { "name": "$AgentName", "model": "$ModelDeployment", "instructions": "<system-prompt>", "tools": [...] }

"@ -ForegroundColor Gray

# -----------------------------------------------------------------------
# Generate Python helper script
# -----------------------------------------------------------------------
$pythonScript = @"
"""
create_agent.py — Register the IQ triage agent via the Foundry Agent SDK.

Usage:
    export AZURE_AI_PROJECT_ENDPOINT="https://your-project.services.ai.azure.com"
    uv run python scripts/create_agent.py

Prerequisites:
    uv pip install azure-ai-projects azure-identity
"""

import json
import os
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import OpenApiTool, OpenApiAnonymousAuthDetails
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ENDPOINT = os.environ.get(
    "AZURE_AI_PROJECT_ENDPOINT",
    "TODO: set AZURE_AI_PROJECT_ENDPOINT env var or paste your endpoint here",
)
TOOL_SERVICE_URL = "$toolServiceUrl"
MODEL_DEPLOYMENT = "$ModelDeployment"
AGENT_NAME = "$AgentName"

def main() -> None:
    # Load system prompt
    system_prompt = (REPO_ROOT / "foundry" / "prompts" / "system.md").read_text()

    # Load and patch OpenAPI spec
    spec = json.loads((REPO_ROOT / "foundry" / "tools.openapi.json").read_text())
    spec["servers"][0]["url"] = TOOL_SERVICE_URL

    # Connect to project
    client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )

    # Create the agent
    agent = client.agents.create_agent(
        model=MODEL_DEPLOYMENT,
        name=AGENT_NAME,
        instructions=system_prompt,
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
    print(f"  https://ai.azure.com")

if __name__ == "__main__":
    main()
"@

$pythonScriptPath = Join-Path $RepoRoot "scripts\create_agent.py"
$pythonScript | Set-Content $pythonScriptPath -Encoding UTF8
Write-Ok "Python helper script generated: scripts/create_agent.py"

# -----------------------------------------------------------------------
# Test prompts
# -----------------------------------------------------------------------
Write-Step "Sample test prompts for the Foundry playground"

Write-Host @"

  Once the agent is registered, test with these prompts:

  1. "Summarize ticket TKT-0042"
     → Should call query-ticket-context, return a 3-bullet triage summary

  2. "What's the status of TKT-0018?"
     → Should query context, cite severity/signal_type/metrics

  3. "Remediate TKT-0042 by restarting BGP sessions"
     → Should call request-approval, then wait for human approval

  4. "Post a summary to Teams for TKT-0042"
     → Should call post-teams-summary (logged, not posted unless webhook set)

"@ -ForegroundColor White

Write-Host "`nAgent registration helper complete." -ForegroundColor Green
Write-Host "See scripts/README.md for the full walkthrough.`n" -ForegroundColor Gray
