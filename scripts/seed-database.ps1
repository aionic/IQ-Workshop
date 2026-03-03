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
# Acquire Entra token
# -----------------------------------------------------------------------
Write-Step "Acquiring Entra token for Azure SQL"
$token = az account get-access-token --resource https://database.windows.net --query accessToken -o tsv
if (-not $token) { throw "Failed to get access token. Run 'az login' first." }
Write-Ok "Token acquired"

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
        # Run each statement individually since CREATE USER FROM EXTERNAL PROVIDER
        # may fail if user already exists — we handle that gracefully
        $statements = @(
            "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'id-iq-tools-iq-lab-dev') CREATE USER [id-iq-tools-iq-lab-dev] FROM EXTERNAL PROVIDER;",
            "ALTER ROLE db_datareader ADD MEMBER [id-iq-tools-iq-lab-dev];",
            "GRANT INSERT ON dbo.iq_remediation_log TO [id-iq-tools-iq-lab-dev];",
            "GRANT UPDATE ON dbo.iq_remediation_log TO [id-iq-tools-iq-lab-dev];",
            "GRANT UPDATE ON dbo.iq_tickets TO [id-iq-tools-iq-lab-dev];",
            "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'id-iq-agent-iq-lab-dev') CREATE USER [id-iq-agent-iq-lab-dev] FROM EXTERNAL PROVIDER;",
            "ALTER ROLE db_datareader ADD MEMBER [id-iq-agent-iq-lab-dev];"
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
