#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy IQ Foundry Agent Lab infrastructure and tool service to Azure.

.DESCRIPTION
    Turnkey deployment script for workshop proctors and lab participants.
    Deploys all Bicep resources (SQL, ACR, Container Apps, AI Services + gpt-5-mini),
    builds the tool service image, updates the Container App, and optionally
    seeds the database and grants managed identity permissions.

.PARAMETER ResourceGroup
    Target resource group name (default: rg-iq-lab-dev).

.PARAMETER Location
    Azure region (default: westus3).

.PARAMETER ParameterFile
    Path to Bicep parameters file (default: ../infra/bicep/parameters.dev.json).

.PARAMETER ImageTag
    Docker image tag for the tool service (default: v4).

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
    [string]$ImageTag = "v4",
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
# Step 1: Bicep deployment
# -----------------------------------------------------------------------
if (-not $SkipBicep) {
    Write-Step "Deploying Bicep infrastructure"
    Write-Host "  Template:   $BicepFile"
    Write-Host "  Parameters: $ParameterFile"
    Write-Host "  RG:         $ResourceGroup"

    $deployment = az deployment group create `
        --resource-group $ResourceGroup `
        --template-file $BicepFile `
        --parameters $ParameterFile `
        --query "properties.{state:provisioningState, outputs:outputs}" `
        --output json 2>&1

    $deployJson = $deployment | ConvertFrom-Json
    if ($deployJson.state -ne "Succeeded") {
        throw "Bicep deployment failed: $deployment"
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
    $outputs = az deployment group show `
        --resource-group $ResourceGroup `
        --name main `
        --query "properties.outputs" `
        --output json 2>$null | ConvertFrom-Json
    if (-not $outputs) {
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
        az acr build --registry $acrName --image "iq-tools:$ImageTag" --platform linux/amd64 . 2>&1 | Out-Null
    }
    finally { Pop-Location }
    Write-Ok "Image built: $imageFull"

    Write-Step "Updating Container App with new image"
    $caName = "ca-tools-iq-lab-$(($ParameterFile | Get-Content | ConvertFrom-Json).parameters.environmentName.value)"
    az containerapp update `
        --name $caName `
        --resource-group $ResourceGroup `
        --image $imageFull `
        --output none
    Write-Ok "Container App updated to $imageFull"
}
else {
    Write-Warn "Skipping image build (--SkipImage)"
}

# -----------------------------------------------------------------------
# Step 3: Seed database (optional)
# -----------------------------------------------------------------------
if ($SeedDatabase) {
    Write-Step "Seeding Azure SQL database"
    & "$PSScriptRoot\seed-database.ps1" -ResourceGroup $ResourceGroup
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
Write-Host "  1. Grant MI permissions: .\scripts\seed-database.ps1 -GrantPermissions"
Write-Host "  2. Register Foundry agent: .\scripts\register-agent.ps1"
Write-Host "  3. Open AI Foundry playground and test the agent"
Write-Host ""
