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
    Target resource group name. Resolved from RESOURCE_GROUP env var or prompted.

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
    [string]$ResourceGroup = "",
    [string]$Location = "westus3",
    [string]$ParameterFile = "$PSScriptRoot\..\infra\bicep\parameters.dev.json",
    [string]$ImageTag = "v$(Get-Date -Format 'yyyyMMdd-HHmm')",
    [string]$UniqueSuffix = "",
    [switch]$SkipBicep,
    [switch]$SkipImage,
    [switch]$SkipRoleAssignments,
    [switch]$SeedDatabase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve resource group: parameter > env var > prompt
if (-not $ResourceGroup) { $ResourceGroup = $env:RESOURCE_GROUP }
if (-not $ResourceGroup) { $ResourceGroup = Read-Host "Resource group (e.g. rg-iq-lab-dev)" }
if (-not $ResourceGroup) { throw "Resource group is required. Pass -ResourceGroup or set RESOURCE_GROUP env var." }

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

    # ---------------------------------------------------------------
    # Prompt for unique suffix if not provided (avoids global name
    # collisions on SQL Server, ACR, AI Services)
    # ---------------------------------------------------------------
    if ([string]::IsNullOrWhiteSpace($UniqueSuffix)) {
        Write-Host ""
        Write-Host "  Resource names for SQL Server, ACR, and AI Services must be globally" -ForegroundColor Yellow
        Write-Host "  unique across all Azure tenants. A short suffix avoids collisions." -ForegroundColor Yellow
        $UniqueSuffix = Read-Host "  Enter a unique suffix (e.g. your initials + 2 digits: an42) or press Enter to skip"
    }

    # Build parameter overrides
    $bicepOverrides = @()
    if (-not [string]::IsNullOrWhiteSpace($UniqueSuffix)) {
        $bicepOverrides += "uniqueSuffix=$UniqueSuffix"
    }
    if ($SkipRoleAssignments) {
        $bicepOverrides += "skipRoleAssignments=true"
    }

    Write-Step "Deploying Bicep infrastructure"
    Write-Host "  Template:   $BicepFile"
    Write-Host "  Parameters: $ParameterFile"
    Write-Host "  RG:         $ResourceGroup"
    if ($UniqueSuffix) { Write-Host "  Suffix:     $UniqueSuffix" }
    if ($SkipRoleAssignments) { Write-Host "  RBAC:       skipped (Contributor-only mode)" -ForegroundColor Yellow }

    # Run Bicep deployment — stderr goes to console, stdout captured as JSON
    $deployArgs = @(
        "deployment", "group", "create",
        "--resource-group", $ResourceGroup,
        "--template-file", $BicepFile,
        "--parameters", $ParameterFile
    )
    foreach ($override in $bicepOverrides) {
        $deployArgs += "--parameters"
        $deployArgs += $override
    }
    $deployArgs += @("--query", "properties.{state:provisioningState, outputs:outputs}", "--output", "json")

    $deployRaw = & az @deployArgs
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
    Push-Location $RepoRoot
    try {
        az acr build --registry $acrName --image "iq-tools:$ImageTag" --platform linux/amd64 services/api-tools
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
    # ---------------------------------------------------------------
    # Primary seeding method: PowerShell seed-database.ps1
    # Connects to Azure SQL via Entra token (your az login identity),
    # runs schema.sql + seed.sql, and grants MI permissions in one shot.
    # ---------------------------------------------------------------
    Write-Step "Seeding database and granting MI permissions (via seed-database.ps1)"
    & "$PSScriptRoot\seed-database.ps1" -ResourceGroup $ResourceGroup -GrantPermissions

    # Give the Container App a few seconds to pick up DB connectivity
    # after MI permissions are granted (token cache refresh).
    Write-Host "  Waiting 15s for managed identity token propagation..." -ForegroundColor Yellow
    Start-Sleep -Seconds 15

    # Resolve Container App name and restart revision to pick up fresh MI token
    if (-not $caName) {
        $caName = if ($outputs) {
            $fqdn = ($outputs.toolServiceUrl.value -replace '^https://', '')
            ($fqdn -split '\.')[0]
        }
        else {
            (az containerapp list -g $ResourceGroup --query "[0].name" -o tsv)
        }
    }
    $latestRev = (az containerapp revision list --name $caName --resource-group $ResourceGroup --query "sort_by([],&properties.createdTime)[-1].name" -o tsv)
    if ($latestRev) {
        Write-Step "Restarting Container App revision to pick up MI credentials"
        az containerapp revision restart --name $caName --resource-group $ResourceGroup --revision $latestRev --output none 2>$null
        Write-Host "  Waiting 30s for revision restart..." -ForegroundColor Yellow
        Start-Sleep -Seconds 30
    }
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

# -----------------------------------------------------------------------
# Post-deploy: role assignment commands for Contributor-only deploys
# -----------------------------------------------------------------------
if ($SkipRoleAssignments) {
    Write-Host ""
    Write-Host "  RBAC ROLE ASSIGNMENTS WERE SKIPPED." -ForegroundColor Yellow
    Write-Host "  Ask an Owner or RBAC Administrator to run these 3 commands:" -ForegroundColor Yellow
    Write-Host ""
    # Fetch principal IDs from deployment outputs
    $roleOutputs = az deployment group show `
        --resource-group $ResourceGroup `
        --name main `
        --query "properties.outputs" `
        --output json 2>$null | Out-String | ConvertFrom-Json
    $miToolsPid  = if ($roleOutputs) { $roleOutputs.miToolsPrincipalId.value } else { '<miToolsPrincipalId>' }
    $miAgentPid  = if ($roleOutputs) { $roleOutputs.miAgentPrincipalId.value } else { '<miAgentPrincipalId>' }
    $acrId       = if ($roleOutputs) { "/subscriptions/$($account.id)/resourceGroups/$ResourceGroup/providers/Microsoft.ContainerRegistry/registries/$($roleOutputs.acrLoginServer.value -replace '\.azurecr\.io','')" } else { '<acrResourceId>' }
    $aiName      = if ($roleOutputs) { $roleOutputs.aiServicesName.value } else { '<aiServicesName>' }
    $aiId        = "/subscriptions/$($account.id)/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$aiName"

    Write-Host "  # 1. AcrPull — let Container Apps pull images"
    Write-Host "  az role assignment create --assignee-object-id $miToolsPid --assignee-principal-type ServicePrincipal --role 'AcrPull' --scope $acrId" -ForegroundColor White
    Write-Host ""
    Write-Host "  # 2. Cognitive Services OpenAI User — tool service MI"
    Write-Host "  az role assignment create --assignee-object-id $miToolsPid --assignee-principal-type ServicePrincipal --role 'Cognitive Services OpenAI User' --scope $aiId" -ForegroundColor White
    Write-Host ""
    Write-Host "  # 3. Cognitive Services OpenAI User — agent MI"
    Write-Host "  az role assignment create --assignee-object-id $miAgentPid --assignee-principal-type ServicePrincipal --role 'Cognitive Services OpenAI User' --scope $aiId" -ForegroundColor White
    Write-Host ""
}

Write-Host "Next steps:"
$step = 1
if (-not $SeedDatabase) {
    Write-Host "  $step. Seed + grant MI permissions: .\scripts\deploy.ps1 -SeedDatabase -SkipBicep -SkipImage"
    $step++
}
if ($SkipRoleAssignments) {
    Write-Host "  $step. Create the 3 RBAC role assignments shown above (requires Owner or RBAC Admin)"
    $step++
}
Write-Host "  $step. Register Foundry agent: .\scripts\register-agent.ps1"
$step++
Write-Host "  $step. Open AI Foundry playground and test the agent"
Write-Host ""
