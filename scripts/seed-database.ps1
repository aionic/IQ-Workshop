#Requires -Version 7.0
<#
.SYNOPSIS
    Seed the Azure SQL database with schema and sample data via Entra token auth.

.DESCRIPTION
    Connects to Azure SQL using Entra token auth (your current az login identity)
    and runs schema.sql + seed.sql to set up the IQ Lab tables and sample data.
    Optionally runs grant-permissions.sql to grant managed identity access.

.PARAMETER ResourceGroup
    Resource group containing the SQL server (default: rg-iq-lab-dev).

.PARAMETER ServerName
    SQL server name without .database.windows.net suffix (default: auto-detected from RG).

.PARAMETER DatabaseName
    Database name (default: sqldb-iq).

.PARAMETER GrantPermissions
    Also run grant-permissions.sql to set up managed identity DB roles.

.EXAMPLE
    # Seed schema + data
    .\seed-database.ps1

.EXAMPLE
    # Seed + grant MI permissions
    .\seed-database.ps1 -GrantPermissions
#>

[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-iq-lab-dev",
    [string]$ServerName,
    [string]$DatabaseName = "sqldb-iq",
    [switch]$GrantPermissions
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$DataDir = Join-Path $RepoRoot "data"

function Write-Step([string]$msg) { Write-Host "`n===> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------
# Helper: create or ensure a SQL firewall rule for a given IP
# -----------------------------------------------------------------------
function Ensure-FirewallRule {
    param(
        [string]$Rg,
        [string]$Server,
        [string]$Ip
    )
    $ruleName = "deploy-script-$($Ip -replace '\.', '-')"
    $existing = az sql server firewall-rule show `
        --resource-group $Rg --server $Server `
        --name $ruleName --output tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $existing) {
        az sql server firewall-rule create `
            --resource-group $Rg --server $Server `
            --name $ruleName `
            --start-ip-address $Ip --end-ip-address $Ip `
            --output none
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create SQL firewall rule for $Ip"
        }
        Write-Ok "Firewall rule '$ruleName' created for $Ip"
        return @{ Name = $ruleName; Created = $true }
    }
    else {
        Write-Ok "Firewall rule '$ruleName' already exists"
        return @{ Name = $ruleName; Created = $false }
    }
}

# -----------------------------------------------------------------------
# Helper: test SQL connectivity with retries
# Returns $true if connection succeeds, $false otherwise.
# On failure, also returns the blocked IP parsed from the error message
# (Azure SQL includes it) so the caller can create a rule for the right IP.
# -----------------------------------------------------------------------
function Test-SqlConnectivity {
    param(
        [string]$Server,
        [string]$Database,
        [string]$Token,
        [int]$MaxRetries = 8,      # 8 x 15s = 2 min max wait
        [int]$RetryDelaySec = 15
    )
    for ($i = 1; $i -le $MaxRetries; $i++) {
        try {
            $null = Invoke-Sqlcmd -ServerInstance $Server -Database $Database `
                -AccessToken $Token -Query "SELECT 1 AS probe" -ErrorAction Stop
            return @{ Connected = $true; BlockedIp = $null }
        }
        catch {
            $msg = $_.Exception.Message
            # Azure SQL error: "Client with IP address 'x.x.x.x' is not allowed"
            if ($msg -match "Client with IP address '([\d\.]+)'") {
                $blockedIp = $Matches[1]
                Write-Warn "Attempt $i/$MaxRetries — blocked IP: $blockedIp"
                return @{ Connected = $false; BlockedIp = $blockedIp }
            }
            if ($i -lt $MaxRetries) {
                Write-Host "  Attempt $i/$MaxRetries — waiting ${RetryDelaySec}s for firewall propagation..." -ForegroundColor Yellow
                Start-Sleep -Seconds $RetryDelaySec
            }
            else {
                Write-Warn "All $MaxRetries connectivity attempts failed: $msg"
                return @{ Connected = $false; BlockedIp = $null }
            }
        }
    }
}

# -----------------------------------------------------------------------
# Resolve SQL server name
# -----------------------------------------------------------------------
if (-not $ServerName) {
    Write-Step "Detecting SQL server in $ResourceGroup"
    $ServerName = az sql server list -g $ResourceGroup --query "[0].name" -o tsv
    if (-not $ServerName) { throw "No SQL server found in $ResourceGroup" }
}
$ServerFQDN = "$ServerName.database.windows.net"
Write-Ok "Server: $ServerFQDN / Database: $DatabaseName"

# -----------------------------------------------------------------------
# Ensure client IP is allowed through SQL firewall
# -----------------------------------------------------------------------
# Azure SQL blocks connections from IPs not in its firewall allow-list.
# This step auto-detects your public IP, creates a temporary firewall
# rule, then probes connectivity with retries (rules can take up to 5 min
# to propagate). If the probe reveals a *different* blocked IP (common
# behind corporate VPN/proxy where Azure traffic egresses differently
# than general internet), a second rule is created for that IP.
# All temporary rules are removed at the end of the script.
# -----------------------------------------------------------------------
Write-Step "Ensuring SQL firewall allows current client IP"
$clientIp = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 10).Trim()
Write-Ok "Detected public IP: $clientIp"

# Track all firewall rules we create so we can clean them up later
$script:createdFwRules = @()

$fwResult = Ensure-FirewallRule -Rg $ResourceGroup -Server $ServerName -Ip $clientIp
if ($fwResult.Created) { $script:createdFwRules += $fwResult.Name }

# -----------------------------------------------------------------------
# Acquire Entra token
# -----------------------------------------------------------------------
Write-Step "Acquiring Entra token for Azure SQL"
$token = az account get-access-token --resource https://database.windows.net --query accessToken -o tsv
if (-not $token) { throw "Failed to get access token. Run 'az login' first." }
Write-Ok "Token acquired"

# -----------------------------------------------------------------------
# Connectivity probe with retry + IP-mismatch recovery
# -----------------------------------------------------------------------
# Firewall rule propagation can take up to 5 minutes. This probe retries
# every 15 seconds. If the error reveals a different blocked IP (VPN/proxy
# egress), a second firewall rule is created and the probe restarts.
# -----------------------------------------------------------------------
Write-Step "Testing SQL connectivity (with firewall propagation retries)"
$probeResult = Test-SqlConnectivity -Server $ServerFQDN -Database $DatabaseName -Token $token

if (-not $probeResult.Connected -and $probeResult.BlockedIp -and $probeResult.BlockedIp -ne $clientIp) {
    # Azure SQL sees a different IP than api.ipify.org returned
    # (common behind corporate VPN/proxy split tunnels)
    Write-Warn "Azure SQL sees a different egress IP ($($probeResult.BlockedIp)) — adding firewall rule"
    $fwResult2 = Ensure-FirewallRule -Rg $ResourceGroup -Server $ServerName -Ip $probeResult.BlockedIp
    if ($fwResult2.Created) { $script:createdFwRules += $fwResult2.Name }

    # Retry with the new rule in place
    $probeResult = Test-SqlConnectivity -Server $ServerFQDN -Database $DatabaseName -Token $token
}

if (-not $probeResult.Connected) {
    throw "Cannot connect to $ServerFQDN after firewall configuration. Check VPN/network settings."
}
Write-Ok "SQL connectivity confirmed"

# -----------------------------------------------------------------------
# Check Invoke-Sqlcmd availability
# -----------------------------------------------------------------------
if (-not (Get-Command Invoke-Sqlcmd -ErrorAction SilentlyContinue)) {
    Write-Step "Installing SqlServer PowerShell module"
    Install-Module SqlServer -Scope CurrentUser -Force -AllowClobber
    Import-Module SqlServer
}

# -----------------------------------------------------------------------
# Run schema.sql
# -----------------------------------------------------------------------
# schema.sql is idempotent: it drops existing tables (FK-safe order)
# before recreating them, so re-runs are safe.
# -----------------------------------------------------------------------
$schemaFile = Join-Path $DataDir "schema.sql"
if (Test-Path $schemaFile) {
    Write-Step "Applying schema.sql"
    # Split on GO batches since Invoke-Sqlcmd handles them natively with -InputFile
    Invoke-Sqlcmd -ServerInstance $ServerFQDN -Database $DatabaseName `
        -AccessToken $token -InputFile $schemaFile -ErrorAction Stop
    Write-Ok "Schema applied"
}
else {
    throw "schema.sql not found at $schemaFile"
}

# -----------------------------------------------------------------------
# Run seed.sql
# -----------------------------------------------------------------------
# seed.sql is idempotent: it deletes all rows (FK-safe order) and
# reseeds the identity column before inserting, so re-runs are safe.
# -----------------------------------------------------------------------
$seedFile = Join-Path $DataDir "seed.sql"
if (Test-Path $seedFile) {
    Write-Step "Applying seed.sql"
    Invoke-Sqlcmd -ServerInstance $ServerFQDN -Database $DatabaseName `
        -AccessToken $token -InputFile $seedFile -ErrorAction Stop
    Write-Ok "Seed data applied"
}
else {
    throw "seed.sql not found at $seedFile"
}

# -----------------------------------------------------------------------
# Verify row counts
# -----------------------------------------------------------------------
Write-Step "Verifying table row counts"
$tables = @("iq_devices", "iq_anomalies", "iq_tickets", "iq_remediation_log")
foreach ($table in $tables) {
    $count = (Invoke-Sqlcmd -ServerInstance $ServerFQDN -Database $DatabaseName `
        -AccessToken $token -Query "SELECT COUNT(*) AS n FROM dbo.$table").n
    Write-Ok "$table`: $count rows"
}

# -----------------------------------------------------------------------
# Grant permissions (optional)
# -----------------------------------------------------------------------
if ($GrantPermissions) {
    $grantFile = Join-Path $DataDir "grant-permissions.sql"
    if (Test-Path $grantFile) {
        Write-Step "Granting managed identity permissions"

        # Resolve MI names from Bicep deployment outputs (not hardcoded)
        $outputsRaw = az deployment group show `
            --resource-group $ResourceGroup `
            --name main `
            --query "properties.outputs" `
            --output json 2>$null
        if ($LASTEXITCODE -eq 0 -and $outputsRaw) {
            $bOutputs = $outputsRaw | Out-String | ConvertFrom-Json
            $miToolsName = $bOutputs.miToolsName.value
            $miAgentName = $bOutputs.miAgentName.value
        }
        else {
            # Fallback: derive from resource group naming convention {type}-iq-lab-{env}
            $envSuffix = ($ResourceGroup -replace '^rg-iq-lab-', '')
            $miToolsName = "id-iq-tools-iq-lab-$envSuffix"
            $miAgentName = "id-iq-agent-iq-lab-$envSuffix"
            Write-Warn "No Bicep outputs found — using derived names: $miToolsName, $miAgentName"
        }
        Write-Ok "MI Tools: $miToolsName  |  MI Agent: $miAgentName"

        # Run each statement individually since CREATE USER FROM EXTERNAL PROVIDER
        # may fail if user already exists — we handle that gracefully
        $statements = @(
            "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$miToolsName') CREATE USER [$miToolsName] FROM EXTERNAL PROVIDER;",
            "ALTER ROLE db_datareader ADD MEMBER [$miToolsName];",
            "GRANT INSERT ON dbo.iq_remediation_log TO [$miToolsName];",
            "GRANT UPDATE ON dbo.iq_remediation_log TO [$miToolsName];",
            "GRANT UPDATE ON dbo.iq_tickets TO [$miToolsName];",
            "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$miAgentName') CREATE USER [$miAgentName] FROM EXTERNAL PROVIDER;",
            "ALTER ROLE db_datareader ADD MEMBER [$miAgentName];"
        )
        foreach ($stmt in $statements) {
            try {
                Invoke-Sqlcmd -ServerInstance $ServerFQDN -Database $DatabaseName `
                    -AccessToken $token -Query $stmt -ErrorAction Stop
            }
            catch {
                Write-Host "  WARN: $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
        Write-Ok "Managed identity permissions granted"
    }
    else {
        Write-Host "  WARN: grant-permissions.sql not found" -ForegroundColor Yellow
    }
}

Write-Host "`nDatabase seeding complete." -ForegroundColor Green

# -----------------------------------------------------------------------
# Cleanup: remove all temporary firewall rules we created
# -----------------------------------------------------------------------
# Clean up temporary SQL firewall rules to avoid leaving stale entries.
# If the script is re-run, it will re-create rules as needed.
# -----------------------------------------------------------------------
if ($script:createdFwRules.Count -gt 0) {
    Write-Step "Removing temporary SQL firewall rule(s)"
    foreach ($ruleName in $script:createdFwRules) {
        az sql server firewall-rule delete `
            --resource-group $ResourceGroup --server $ServerName `
            --name $ruleName --output none 2>$null
        Write-Ok "Firewall rule '$ruleName' removed"
    }
}
