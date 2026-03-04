#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy IQ Foundry Agent Lab infrastructure and tool service to Azure.

.DESCRIPTION
    Turnkey deployment script for workshop proctors and lab participants.
    Deploys all Bicep resources (SQL, ACR, Container Apps, AI Services + gpt-4.1-mini),
    builds the tool service image, updates the Container App, and optionally
    seeds the database and grants managed identity permissions.

.PARAMETER ResourceGroup
    Target resource group name (default: rg-iq-lab-dev).

.PARAMETER Location
    Azure region (default: westus3).

.PARAMETER ParameterFile
    Path to Bicep parameters file (default: ../infra/bicep/parameters.dev.json).

.PARAMETER ImageTag
    Docker image tag for the tool service (default: timestamp-based, e.g. v20260303-1430).

.PARAMETER SkipBicep
    Skip Bicep infrastructure deployment (useful when only rebuilding the image).

.PARAMETER SkipImage
    Skip image build and container update.

.PARAMETER SeedDatabase
    Run schema.sql + seed.sql against Azure SQL after deployment.

.EXAMPLE
    # Full deployment (first time)
    .\deploy.ps1 -SeedDatabase

.EXAMPLE
    # Rebuild image only
    .\deploy.ps1 -SkipBicep -ImageTag v5

.EXAMPLE
    # Bicep only (no image rebuild)
    .\deploy.ps1 -SkipImage
#>

[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-iq-lab-dev",
    [string]$Location = "westus3",
    [string]$ParameterFile = "$PSScriptRoot\..\infra\bicep\parameters.dev.json",
    [string]$ImageTag = "v$(Get-Date -Format 'yyyyMMdd-HHmm')",
    [switch]$SkipBicep,
    [switch]$SkipImage,
    [switch]$SeedDatabase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$BicepFile = Join-Path $RepoRoot "infra\bicep\main.bicep"
$ApiToolsDir = Join-Path $RepoRoot "services\api-tools"

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------
function Write-Step([string]$msg) { Write-Host "`n===> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------
Write-Step "Pre-flight checks"

$azVersion = az version 2>$null | ConvertFrom-Json
if (-not $azVersion) { throw "Azure CLI not found. Install from https://aka.ms/installazurecli" }
Write-Ok "Azure CLI $($azVersion.'azure-cli')"

$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) { throw "Not logged in. Run 'az login' first." }
Write-Ok "Subscription: $($account.name) ($($account.id))"

# Ensure resource group exists
$rgExists = az group exists --name $ResourceGroup 2>$null
if ($rgExists -eq "false") {
    Write-Step "Creating resource group $ResourceGroup in $Location"
    az group create --name $ResourceGroup --location $Location --output none
    Write-Ok "Resource group created"
}
else {
    Write-Ok "Resource group $ResourceGroup exists"
}

# -----------------------------------------------------------------------
# Step 0.5: Purge soft-deleted Cognitive Services if they conflict
# -----------------------------------------------------------------------
# When a resource group is deleted, Azure soft-deletes Cognitive Services
# accounts for 48 hours. Re-deploying the same Bicep template within that
# window fails with FlagMustBeSetForRestore. This function detects any
# soft-deleted accounts that match the target resource group and prompts
# the operator to purge them before proceeding.
# See: https://learn.microsoft.com/azure/ai-services/recover-purge-resources
# -----------------------------------------------------------------------
function Resolve-SoftDeletedCognitiveServices([string]$rg, [string]$loc) {
    Write-Step "Checking for soft-deleted Cognitive Services accounts"
    $raw = az cognitiveservices account list-deleted `
        --query "[?contains(id, '$rg')].{name:name, location:location}" `
        --output tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        Write-Ok "No conflicting soft-deleted accounts"
        return
    }
    # Each TSV line: name<TAB>location
    foreach ($line in ($raw -split "`n")) {
        $parts = ($line.Trim() -split "`t")
        if ($parts.Length -lt 2) { continue }
        $name    = $parts[0]
        $itemLoc = $parts[1]
        Write-Warn "Found soft-deleted Cognitive Services: $name (location: $itemLoc)"
        $choice = Read-Host "  Purge '$name' so it can be recreated? (Y/n)"
        if ($choice -eq '' -or $choice -match '^[Yy]') {
            Write-Host "  Purging $name ..." -ForegroundColor Yellow
            az cognitiveservices account purge --name $name --resource-group $rg --location $itemLoc --output none 2>$null
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to purge '$name'. Manual: az cognitiveservices account purge --name $name --resource-group $rg --location $itemLoc"
            }
            Write-Ok "Purged $name"
        }
        else {
            throw "Cannot proceed — soft-deleted account '$name' blocks deployment. Purge it or restore manually."
        }
    }
}

# -----------------------------------------------------------------------
# Step 1: Bicep deployment
# -----------------------------------------------------------------------
# NOTE: The deploy script is idempotent — safe to re-run at any point.
# - Soft-deleted Cognitive Services are auto-detected and purged (Step 0.5)
# - Bicep template uses incremental deployment mode (Azure default)
# - ACR build overwrites existing image tags
# - Container App update is a rolling revision update
# -----------------------------------------------------------------------
if (-not $SkipBicep) {
    Resolve-SoftDeletedCognitiveServices -rg $ResourceGroup -loc $Location

    Write-Step "Deploying Bicep infrastructure"
    Write-Host "  Template:   $BicepFile"
    Write-Host "  Parameters: $ParameterFile"
    Write-Host "  RG:         $ResourceGroup"

    # Run Bicep deployment — stderr goes to console, stdout captured as JSON
    $deployRaw = az deployment group create `
        --resource-group $ResourceGroup `
        --template-file $BicepFile `
        --parameters $ParameterFile `
        --query "properties.{state:provisioningState, outputs:outputs}" `
        --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Bicep deployment failed (exit code $LASTEXITCODE). Review errors above."
    }

    $deployJson = $deployRaw | Out-String | ConvertFrom-Json
    if ($deployJson.state -ne "Succeeded") {
        throw "Bicep deployment state: $($deployJson.state)"
    }

    $outputs = $deployJson.outputs
    Write-Ok "Bicep deployment succeeded"
    Write-Host "  Tool Service URL:  $($outputs.toolServiceUrl.value)"
    Write-Host "  AI Services:       $($outputs.aiServicesName.value)"
    Write-Host "  Model Deployment:  $($outputs.aiModelDeploymentName.value)"
    Write-Host "  ACR:               $($outputs.acrLoginServer.value)"
    Write-Host "  SQL Server:        $($outputs.sqlServerFqdn.value)"
}
else {
    Write-Warn "Skipping Bicep deployment (--SkipBicep)"
    # Still need outputs for subsequent steps
    $outputsRaw = az deployment group show `
        --resource-group $ResourceGroup `
        --name main `
        --query "properties.outputs" `
        --output json 2>$null
    if ($LASTEXITCODE -eq 0 -and $outputsRaw) {
        $outputs = $outputsRaw | Out-String | ConvertFrom-Json
    }
    else {
        $outputs = $null
        Write-Warn "No previous deployment found — fetching resource names directly"
    }
}

# -----------------------------------------------------------------------
# Step 2: Build and deploy container image
# -----------------------------------------------------------------------
if (-not $SkipImage) {
    # Resolve ACR name
    $acrName = if ($outputs) { ($outputs.acrLoginServer.value -split '\.')[0] }
               else { (az acr list -g $ResourceGroup --query "[0].name" -o tsv) }
    $imageFull = "$acrName.azurecr.io/iq-tools:$ImageTag"

    Write-Step "Building container image: $imageFull"
    Push-Location $ApiToolsDir
    try {
        az acr build --registry $acrName --image "iq-tools:$ImageTag" --platform linux/amd64 .
        if ($LASTEXITCODE -ne 0) {
            throw "ACR build failed (exit code $LASTEXITCODE). Review errors above."
        }
    }
    finally { Pop-Location }
    Write-Ok "Image built: $imageFull"

    Write-Step "Updating Container App with new image"
    # Derive Container App name from Bicep deployment outputs
    $caName = if ($outputs) {
        # toolServiceUrl is like https://ca-tools-iq-lab-dev.<hash>.<region>.azurecontainerapps.io
        $fqdn = ($outputs.toolServiceUrl.value -replace '^https://', '')
        ($fqdn -split '\.')[0]
    }
    else {
        (az containerapp list -g $ResourceGroup --query "[0].name" -o tsv)
    }
    az containerapp update `
        --name $caName `
        --resource-group $ResourceGroup `
        --image $imageFull `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Container App update failed (exit code $LASTEXITCODE). Review errors above."
    }
    Write-Ok "Container App updated to $imageFull"
}
else {
    Write-Warn "Skipping image build (--SkipImage)"
}

# -----------------------------------------------------------------------
# Step 3: Seed database + grant MI permissions (optional)
# -----------------------------------------------------------------------
# When -SeedDatabase is set, we also pass -GrantPermissions so the
# Container App's managed identity (id-iq-tools-*) is created as a
# SQL user and granted the read/write roles it needs. Without this,
# every DB-dependent endpoint returns 503 "db unavailable".
# -----------------------------------------------------------------------
if ($SeedDatabase) {
    Write-Step "Seeding Azure SQL database (with MI permissions)"
    & "$PSScriptRoot\seed-database.ps1" -ResourceGroup $ResourceGroup -GrantPermissions
    # Give the Container App a few seconds to pick up DB connectivity
    # after MI permissions are granted (token cache refresh)
    Write-Host "  Waiting 10s for managed identity token propagation..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

# -----------------------------------------------------------------------
# Step 4: Smoke test
# -----------------------------------------------------------------------
Write-Step "Running smoke test"
& "$PSScriptRoot\smoke-test.ps1" -ResourceGroup $ResourceGroup

Write-Host "`n============================================" -ForegroundColor Green
Write-Host " Deployment complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
if (-not $SeedDatabase) {
    Write-Host "  1. Seed + grant MI permissions: .\scripts\deploy.ps1 -SeedDatabase -SkipBicep -SkipImage"
}
Write-Host "  $(if ($SeedDatabase) {'1'} else {'2'}). Register Foundry agent: .\scripts\register-agent.ps1"
Write-Host "  $(if ($SeedDatabase) {'2'} else {'3'}). Open AI Foundry playground and test the agent"
Write-Host ""
