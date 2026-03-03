#!/usr/bin/env bash
# ============================================================================
# smoke-test.sh — Smoke test all IQ Lab tool service endpoints
#
# Usage:
#   ./scripts/smoke-test.sh                           # auto-detect from Bicep outputs
#   ./scripts/smoke-test.sh -b http://localhost:8000   # explicit base URL
#   ./scripts/smoke-test.sh -g rg-iq-lab-staging       # different resource group
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults & argument parsing
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-iq-lab-dev"
BASE_URL=""

usage() {
    echo "Usage: $0 [-g resource_group] [-b base_url]"
    echo "  -g  Resource group (default: rg-iq-lab-dev)"
    echo "  -b  Base URL override (auto-detected from Bicep outputs if omitted)"
    exit 1
}

while getopts "g:b:h" opt; do
    case $opt in
        g) RESOURCE_GROUP="$OPTARG" ;;
        b) BASE_URL="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
FAILURES=0
TOTAL=0
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

step()  { echo -e "\n${CYAN}===> $1${NC}"; }
pass()  { echo -e "  ${GREEN}PASS: $1${NC}"; }
fail()  { echo -e "  ${RED}FAIL: $1${NC}"; FAILURES=$((FAILURES + 1)); }

test_endpoint() {
    local name="$1"
    shift
    TOTAL=$((TOTAL + 1))
    if "$@" 2>/dev/null; then
        pass "$name"
    else
        fail "$name — $*"
    fi
}

# ---------------------------------------------------------------------------
# Resolve base URL
# ---------------------------------------------------------------------------
if [[ -z "$BASE_URL" ]]; then
    step "Resolving tool service URL from Bicep outputs"
    BASE_URL=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name main \
        --query "properties.outputs.toolServiceUrl.value" \
        --output tsv 2>/dev/null || true)

    if [[ -z "$BASE_URL" ]]; then
        FQDN=$(az containerapp list -g "$RESOURCE_GROUP" \
            --query "[0].properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true)
        if [[ -z "$FQDN" ]]; then
            echo "ERROR: No Container App found in $RESOURCE_GROUP" >&2
            exit 1
        fi
        BASE_URL="https://$FQDN"
    fi
fi

echo "Target: $BASE_URL"

# ---------------------------------------------------------------------------
# 1. Health
# ---------------------------------------------------------------------------
step "1/7 — GET /health"
test_endpoint "Health check" bash -c "
    resp=\$(curl -fsS '$BASE_URL/health' --max-time 10)
    echo \"\$resp\" | grep -q '\"ok\"'
"

# ---------------------------------------------------------------------------
# 2. Query ticket context
# ---------------------------------------------------------------------------
step "2/7 — POST /tools/query-ticket-context"
test_endpoint "Query ticket TKT-0042" bash -c "
    resp=\$(curl -fsS -X POST '$BASE_URL/tools/query-ticket-context' \
        -H 'Content-Type: application/json' \
        -d '{\"ticket_id\": \"TKT-0042\"}' --max-time 15)
    echo \"\$resp\" | grep -q 'TKT-0042'
"

# ---------------------------------------------------------------------------
# 3. Query non-existent ticket (404)
# ---------------------------------------------------------------------------
step "3/7 — POST /tools/query-ticket-context (404)"
test_endpoint "Query non-existent ticket returns 404" bash -c "
    code=\$(curl -s -o /dev/null -w '%{http_code}' -X POST '$BASE_URL/tools/query-ticket-context' \
        -H 'Content-Type: application/json' \
        -d '{\"ticket_id\": \"TKT-9999\"}' --max-time 15)
    [[ \"\$code\" == '404' ]]
"

# ---------------------------------------------------------------------------
# 4. Request approval
# ---------------------------------------------------------------------------
CORRELATION_ID=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")

step "4/7 — POST /tools/request-approval"
APPROVAL_RESP=$(curl -fsS -X POST "$BASE_URL/tools/request-approval" \
    -H "Content-Type: application/json" \
    -d "{
        \"ticket_id\": \"TKT-0042\",
        \"proposed_action\": \"smoke_test_restart_bgp\",
        \"rationale\": \"Automated smoke test\",
        \"correlation_id\": \"$CORRELATION_ID\"
    }" --max-time 15 2>/dev/null || echo '{}')

REMEDIATION_ID=$(echo "$APPROVAL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('remediation_id',''))" 2>/dev/null || echo "")
APPROVAL_TOKEN=$(echo "$APPROVAL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('approval_token',''))" 2>/dev/null || echo "")

if echo "$APPROVAL_RESP" | grep -q '"PENDING"'; then
    pass "Request approval"
    TOTAL=$((TOTAL + 1))
else
    fail "Request approval"
    TOTAL=$((TOTAL + 1))
fi

# ---------------------------------------------------------------------------
# 5. Decide approval
# ---------------------------------------------------------------------------
step "5/7 — POST /admin/approvals/{id}/decide"
test_endpoint "Approve remediation" bash -c "
    resp=\$(curl -fsS -X POST '$BASE_URL/admin/approvals/$REMEDIATION_ID/decide' \
        -H 'Content-Type: application/json' \
        -d '{\"decision\": \"APPROVED\", \"approver\": \"smoke-test@contoso.com\"}' --max-time 15)
    echo \"\$resp\" | grep -q 'APPROVED'
"

# ---------------------------------------------------------------------------
# 6. Execute remediation
# ---------------------------------------------------------------------------
step "6/7 — POST /tools/execute-remediation"
test_endpoint "Execute remediation" bash -c "
    resp=\$(curl -fsS -X POST '$BASE_URL/tools/execute-remediation' \
        -H 'Content-Type: application/json' \
        -d '{
            \"ticket_id\": \"TKT-0042\",
            \"action\": \"smoke_test_restart_bgp\",
            \"approved_by\": \"smoke-test@contoso.com\",
            \"approval_token\": \"$APPROVAL_TOKEN\",
            \"correlation_id\": \"$CORRELATION_ID\"
        }' --max-time 15)
    echo \"\$resp\" | grep -q 'remediation_id'
"

# ---------------------------------------------------------------------------
# 7. Post Teams summary
# ---------------------------------------------------------------------------
step "7/7 — POST /tools/post-teams-summary"
test_endpoint "Post Teams summary" bash -c "
    resp=\$(curl -fsS -X POST '$BASE_URL/tools/post-teams-summary' \
        -H 'Content-Type: application/json' \
        -d '{
            \"ticket_id\": \"TKT-0042\",
            \"summary\": \"Smoke test completed successfully\",
            \"action_taken\": \"smoke_test_restart_bgp\",
            \"approved_by\": \"smoke-test@contoso.com\",
            \"correlation_id\": \"$CORRELATION_ID\"
        }' --max-time 15)
    echo \"\$resp\" | grep -q '\"logged\"'
"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
PASSED=$((TOTAL - FAILURES))
if [[ $FAILURES -eq 0 ]]; then
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN} Results: $PASSED/$TOTAL passed${NC}"
    echo -e "${GREEN}============================================${NC}"
else
    echo -e "${RED}============================================${NC}"
    echo -e "${RED} Results: $PASSED/$TOTAL passed${NC}"
    echo -e "${RED}============================================${NC}"
    exit 1
fi
