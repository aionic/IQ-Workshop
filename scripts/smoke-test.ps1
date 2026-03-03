#Requires -Version 7.0
<#
.SYNOPSIS
    Smoke test all IQ Lab tool service endpoints against the live deployment.

.DESCRIPTION
    Calls every endpoint on the deployed Container App and validates responses.
    Returns exit code 0 if all pass, 1 if any fail.

.PARAMETER ResourceGroup
    Resource group (default: rg-iq-lab-dev).

.PARAMETER BaseUrl
    Override the tool service URL (auto-detected from Container App if omitted).

.EXAMPLE
    .\smoke-test.ps1

.EXAMPLE
    .\smoke-test.ps1 -BaseUrl http://localhost:8000
#>

[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-iq-lab-dev",
    [string]$BaseUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) { Write-Host "`n===> $msg" -ForegroundColor Cyan }
function Write-Pass([string]$msg) { Write-Host "  PASS: $msg" -ForegroundColor Green }
function Write-Fail([string]$msg) { Write-Host "  FAIL: $msg" -ForegroundColor Red; $script:failures++ }

$script:failures = 0
$script:total = 0

function Test-Endpoint([string]$name, [scriptblock]$test) {
    $script:total++
    try {
        & $test
        Write-Pass $name
    }
    catch {
        Write-Fail "$name — $($_.Exception.Message)"
    }
}

# -----------------------------------------------------------------------
# Resolve base URL
# -----------------------------------------------------------------------
if (-not $BaseUrl) {
    $fqdn = az containerapp show `
        -n ca-tools-iq-lab-dev -g $ResourceGroup `
        --query "properties.configuration.ingress.fqdn" -o tsv 2>$null
    if (-not $fqdn) { throw "Container App not found in $ResourceGroup" }
    $BaseUrl = "https://$fqdn"
}

Write-Host "Target: $BaseUrl" -ForegroundColor White

# -----------------------------------------------------------------------
# 1. Health
# -----------------------------------------------------------------------
Write-Step "1/7 — GET /health"
Test-Endpoint "Health check" {
    $r = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 10
    if ($r.status -ne "ok") { throw "status=$($r.status)" }
    if ($r.db -ne "connected") { throw "db=$($r.db)" }
}

# -----------------------------------------------------------------------
# 2. Query ticket context
# -----------------------------------------------------------------------
Write-Step "2/7 — POST /tools/query-ticket-context"
Test-Endpoint "Query ticket TKT-0042" {
    $body = @{ ticket_id = "TKT-0042" } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$BaseUrl/tools/query-ticket-context" `
        -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    if ($r.ticket_id -ne "TKT-0042") { throw "ticket_id mismatch: $($r.ticket_id)" }
    if (-not $r.device_id) { throw "device_id missing" }
    if (-not $r.severity) { throw "severity missing" }
}

# -----------------------------------------------------------------------
# 3. Query non-existent ticket (404)
# -----------------------------------------------------------------------
Write-Step "3/7 — POST /tools/query-ticket-context (404)"
Test-Endpoint "Query non-existent ticket returns 404" {
    try {
        Invoke-RestMethod -Uri "$BaseUrl/tools/query-ticket-context" `
            -Method Post -Body '{"ticket_id":"TKT-9999"}' `
            -ContentType "application/json" -TimeoutSec 15
        throw "Expected 404 but got 200"
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) {
            throw "Expected 404 but got $($_.Exception.Response.StatusCode.value__)"
        }
    }
}

# -----------------------------------------------------------------------
# 4. Request approval
# -----------------------------------------------------------------------
Write-Step "4/7 — POST /tools/request-approval"
$correlationId = [guid]::NewGuid().ToString()
Test-Endpoint "Request approval" {
    $body = @{
        ticket_id       = "TKT-0042"
        proposed_action = "smoke_test_restart_bgp"
        rationale       = "Automated smoke test"
        correlation_id  = $correlationId
    } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$BaseUrl/tools/request-approval" `
        -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    if ($r.status -ne "PENDING") { throw "status=$($r.status)" }
    $script:remediationId = $r.remediation_id
    $script:approvalToken = $r.approval_token
}

# -----------------------------------------------------------------------
# 5. Decide approval
# -----------------------------------------------------------------------
Write-Step "5/7 — POST /admin/approvals/{id}/decide"
Test-Endpoint "Approve remediation" {
    $body = @{
        decision = "APPROVED"
        approver = "smoke-test@contoso.com"
    } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$BaseUrl/admin/approvals/$($script:remediationId)/decide" `
        -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    if ($r.status -ne "APPROVED") { throw "status=$($r.status)" }
}

# -----------------------------------------------------------------------
# 6. Execute remediation
# -----------------------------------------------------------------------
Write-Step "6/7 — POST /tools/execute-remediation"
Test-Endpoint "Execute remediation" {
    $body = @{
        ticket_id      = "TKT-0042"
        action         = "smoke_test_restart_bgp"
        approved_by    = "smoke-test@contoso.com"
        approval_token = "$($script:approvalToken)"
        correlation_id = $correlationId
    } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$BaseUrl/tools/execute-remediation" `
        -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    if (-not $r.remediation_id) { throw "remediation_id missing" }
    if (-not $r.executed_utc) { throw "executed_utc missing" }
}

# -----------------------------------------------------------------------
# 7. Post Teams summary
# -----------------------------------------------------------------------
Write-Step "7/7 — POST /tools/post-teams-summary"
Test-Endpoint "Post Teams summary" {
    $body = @{
        ticket_id      = "TKT-0042"
        summary        = "Smoke test completed successfully"
        action_taken   = "smoke_test_restart_bgp"
        approved_by    = "smoke-test@contoso.com"
        correlation_id = $correlationId
    } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$BaseUrl/tools/post-teams-summary" `
        -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    if ($r.logged -ne $true) { throw "logged=$($r.logged)" }
}

# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor $(if ($script:failures -eq 0) { "Green" } else { "Red" })
$passed = $script:total - $script:failures
Write-Host " Results: $passed/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { "Green" } else { "Red" })
Write-Host "============================================" -ForegroundColor $(if ($script:failures -eq 0) { "Green" } else { "Red" })

if ($script:failures -gt 0) { exit 1 }
