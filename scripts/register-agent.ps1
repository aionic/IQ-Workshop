#Requires -Version 7.0
<#
.SYNOPSIS
    Register the IQ triage agent in Azure AI Foundry Agent Service.

.DESCRIPTION
    Two-step workflow:
      Step 1: Upload knowledge files to a Foundry vector store (upload_knowledge.py).
      Step 2: Create the Foundry prompt agent with MCP tools (create_agent.py).

    Both steps resolve values from Bicep deployment outputs automatically.
    The vector store ID is persisted in .agent-state.json between steps.

    Use -SkipKnowledge to skip the knowledge upload step (e.g. if already done).
    Use -ManualOnly to display portal instructions instead of SDK creation.

    Prerequisites:
      - Azure CLI logged in with access to the AI Foundry project
      - Container App running with healthy /health endpoint
      - uv installed (https://docs.astral.sh/uv/getting-started/installation/)

.PARAMETER ResourceGroup
    Resource group. Resolved from RESOURCE_GROUP env var or prompted.

.PARAMETER AgentName
    Name for the agent (default: iq-triage-agent).

.PARAMETER SkipKnowledge
    Skip the knowledge upload step (use existing vector store from .agent-state.json).

.PARAMETER ManualOnly
    Skip SDK agent creation; only show portal instructions.

.EXAMPLE
    .\register-agent.ps1

.EXAMPLE
    .\register-agent.ps1 -SkipKnowledge

.EXAMPLE
    .\register-agent.ps1 -ResourceGroup rg-iq-lab-staging
#>

[CmdletBinding()]
param(
    [string]$ResourceGroup = "",
    [string]$AgentName = "iq-triage-agent",
    [switch]$SkipKnowledge,
    [switch]$ManualOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path

function Write-Step([string]$msg) { Write-Host "`n===> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------
# Resolve resource group — from parameter, env var, or prompt
# -----------------------------------------------------------------------
if (-not $ResourceGroup) { $ResourceGroup = $env:RESOURCE_GROUP }
if (-not $ResourceGroup) {
    $ResourceGroup = Read-Host "Resource group (e.g. rg-iq-lab-dev)"
}
if (-not $ResourceGroup) {
    throw "Resource group is required. Pass -ResourceGroup or set RESOURCE_GROUP env var."
}

# -----------------------------------------------------------------------
# Resolve deployment outputs from Bicep
# -----------------------------------------------------------------------
Write-Step "Resolving deployment outputs from $ResourceGroup"

$outputsRaw = az deployment group show `
    --resource-group $ResourceGroup `
    --name main `
    --query "properties.outputs" `
    --output json 2>$null

if ($LASTEXITCODE -ne 0 -or -not $outputsRaw) {
    throw "No Bicep deployment named 'main' found in $ResourceGroup. Run deploy.ps1 first."
}

$outputs = $outputsRaw | Out-String | ConvertFrom-Json

$toolServiceUrl     = $outputs.toolServiceUrl.value
$aiServicesName     = $outputs.aiServicesName.value
$aiServicesEndpoint = $outputs.aiServicesEndpoint.value
$projectEndpoint    = $outputs.foundryProjectEndpoint.value
$projectName        = $outputs.foundryProjectName.value
$modelDeployment    = $outputs.aiModelDeploymentName.value
$uniqueSuffix       = if ($outputs.uniqueSuffix) { $outputs.uniqueSuffix.value } else { "" }

Write-Ok "Tool Service:     $toolServiceUrl"
Write-Ok "AI Services:      $aiServicesName"
Write-Ok "Foundry Project:  $projectName"
Write-Ok "Project Endpoint: $projectEndpoint"
Write-Ok "Model:            $modelDeployment"
Write-Ok "Unique Suffix:    $uniqueSuffix"

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

# (AI Services endpoint already resolved from Bicep outputs above)

# -----------------------------------------------------------------------
# Load system prompt
# -----------------------------------------------------------------------
$systemPromptPath = Join-Path $RepoRoot "foundry\prompts\system.md"
$systemPrompt = Get-Content $systemPromptPath -Raw
Write-Ok "System prompt loaded ($($systemPrompt.Length) chars)"

# -----------------------------------------------------------------------
# Step 1: Upload knowledge files (unless -SkipKnowledge)
# -----------------------------------------------------------------------
if (-not $ManualOnly) {
    $uvPath = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvPath) {
        Write-Warn "uv not found -- install from https://docs.astral.sh/uv/getting-started/installation/"
        Write-Warn "Falling back to manual instructions below."
        $ManualOnly = $true
    }
}

if (-not $ManualOnly -and -not $SkipKnowledge) {
    Write-Step "Step 1: Uploading knowledge files to vector store"

    $uploadScript = Join-Path $RepoRoot "scripts\upload_knowledge.py"
    Write-Host "  Running: uv run $uploadScript --resource-group $ResourceGroup"
    uv run $uploadScript --resource-group $ResourceGroup

    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Knowledge upload complete"
    }
    else {
        Write-Warn "Knowledge upload failed (exit code $LASTEXITCODE)"
        Write-Warn "Agent will be created without FileSearchTool."
    }
}
elseif (-not $ManualOnly) {
    Write-Step "Step 1: Knowledge upload skipped (-SkipKnowledge)"
    Write-Host "  Using existing vector store from .agent-state.json (if present)."
}

# -----------------------------------------------------------------------
# Step 2: Create agent via SDK (unless -ManualOnly)
# -----------------------------------------------------------------------
if (-not $ManualOnly) {
    Write-Step "Step 2: Creating agent via Foundry Agent SDK"

    $createScript = Join-Path $RepoRoot "scripts\create_agent.py"
    $suffixArgs = if ($uniqueSuffix) { @("--suffix", $uniqueSuffix) } else { @() }
    Write-Host "  Running: uv run $createScript --resource-group $ResourceGroup $($suffixArgs -join ' ')"
    uv run $createScript --resource-group $ResourceGroup @suffixArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Agent created successfully"
    }
    else {
        Write-Warn "Agent creation failed (exit code $LASTEXITCODE)"
        Write-Warn "Displaying manual instructions instead."
        $ManualOnly = $true
    }
}

# -----------------------------------------------------------------------
# Manual registration instructions (shown when -ManualOnly or SDK fails)
# -----------------------------------------------------------------------
if ($ManualOnly) {
    Write-Step "Manual Agent Registration (AI Foundry Portal)"

    Write-Host @"

  +------------------------------------------------------------------+
  |                    FOUNDRY AGENT CONFIGURATION                   |
  +------------------------------------------------------------------+
  |                                                                  |
  |  Agent Name:        $AgentName
  |  Model Deployment:  $modelDeployment
  |  AI Services:       $aiServicesEndpoint
  |  Project Endpoint:  $projectEndpoint
  |  Tool Service URL:  $toolServiceUrl
  |                                                                  |
  |  -- System Prompt --                                             |
  |  File: foundry/prompts/system.md                                 |
  |  (Copy the full contents into the agent's Instructions field)    |
  |                                                                  |
  |  -- Tools --                                                     |
  |  Function tools (Responses API compatible, auto-generated by       |
  |  FunctionTool in scripts/create_agent.py). Client-side execution   |
  |  via scripts/chat_agent.py.                                        |
  |                                                                  |
  +------------------------------------------------------------------+

  Steps:
    1. Go to https://ai.azure.com
    2. Open project: $projectName
    3. Navigate to 'Agents' in the left menu
    4. Click '+ New Agent'
    5. Select model: $modelDeployment
    6. Paste the system prompt from foundry/prompts/system.md
    7. Add function tools (see create_agent.py for definitions)
    8. Test with: uv run scripts/chat_agent.py --resource-group $ResourceGroup

"@ -ForegroundColor White
}

# -----------------------------------------------------------------------
# Test prompts
# -----------------------------------------------------------------------
Write-Step "Sample test prompts for the Foundry playground"

Write-Host @"

  Once the agent is registered, test with these prompts:

  1. "Summarize ticket TKT-0042"
     -> Should call query-ticket-context, return a 3-bullet triage summary

  2. "What's the status of TKT-0018?"
     -> Should query context, cite severity/signal_type/metrics

  3. "Remediate TKT-0042 by restarting BGP sessions"
     -> Should call request-approval, then wait for human approval

  4. "Post a summary to Teams for TKT-0042"
     -> Should call post-teams-summary (logged, not posted unless webhook set)

"@ -ForegroundColor White

Write-Host "`nAgent registration complete." -ForegroundColor Green
