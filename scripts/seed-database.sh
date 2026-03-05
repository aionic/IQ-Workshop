#!/usr/bin/env bash
# ============================================================================
# seed-database.sh — Seed Azure SQL with schema + sample data via Entra token
#
# Usage:
#   ./scripts/seed-database.sh                        # seed schema + data
#   ./scripts/seed-database.sh --grant-permissions     # also grant MI access
#   ./scripts/seed-database.sh -g rg-iq-lab-staging    # different RG
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-iq-lab-dev"
SERVER_NAME=""
DATABASE_NAME="sqldb-iq"
GRANT_PERMISSIONS=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -g, --resource-group NAME    Resource group (default: rg-iq-lab-dev)"
    echo "  -s, --server-name NAME       SQL server name (auto-detected if omitted)"
    echo "  -d, --database-name NAME     Database name (default: sqldb-iq)"
    echo "  --grant-permissions           Grant managed identity DB access"
    echo "  -h, --help                   Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -g|--resource-group)    RESOURCE_GROUP="$2"; shift 2 ;;
        -s|--server-name)       SERVER_NAME="$2"; shift 2 ;;
        -d|--database-name)     DATABASE_NAME="$2"; shift 2 ;;
        --grant-permissions)    GRANT_PERMISSIONS=true; shift ;;
        -h|--help)              usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

step() { echo -e "\n${CYAN}===> $1${NC}"; }
ok()   { echo -e "  ${GREEN}OK: $1${NC}"; }
warn() { echo -e "  ${YELLOW}WARN: $1${NC}"; }

# ---------------------------------------------------------------------------
# Resolve SQL server
# ---------------------------------------------------------------------------
if [[ -z "$SERVER_NAME" ]]; then
    step "Detecting SQL server in $RESOURCE_GROUP"
    SERVER_NAME=$(az sql server list -g "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null || true)
    if [[ -z "$SERVER_NAME" ]]; then
        echo "ERROR: No SQL server found in $RESOURCE_GROUP" >&2
        exit 1
    fi
fi
SERVER_FQDN="$SERVER_NAME.database.windows.net"
ok "Server: $SERVER_FQDN / Database: $DATABASE_NAME"

# ---------------------------------------------------------------------------
# Ensure client IP is allowed through SQL firewall
# ---------------------------------------------------------------------------
# Azure SQL blocks connections from IPs not in its firewall allow-list.
# This step auto-detects your public IP, creates a temporary firewall
# rule, then probes connectivity with retries (rules can take up to 5 min
# to propagate). If the probe reveals a *different* blocked IP (common
# behind corporate VPN/proxy where Azure traffic egresses differently
# than general internet), a second rule is created for that IP.
# All temporary rules are removed at the end of the script.
# ---------------------------------------------------------------------------
CREATED_FW_RULES=()

ensure_firewall_rule() {
    local rg="$1" server="$2" ip="$3"
    local rule_name="deploy-script-${ip//./-}"
    if az sql server firewall-rule show \
        --resource-group "$rg" --server "$server" \
        --name "$rule_name" --output tsv &>/dev/null; then
        ok "Firewall rule '$rule_name' already exists"
    else
        az sql server firewall-rule create \
            --resource-group "$rg" --server "$server" \
            --name "$rule_name" \
            --start-ip-address "$ip" --end-ip-address "$ip" \
            --output none
        ok "Firewall rule '$rule_name' created for $ip"
        CREATED_FW_RULES+=("$rule_name")
    fi
}

cleanup_firewall_rules() {
    if [[ ${#CREATED_FW_RULES[@]} -gt 0 ]]; then
        step "Removing temporary SQL firewall rule(s)"
        for rule_name in "${CREATED_FW_RULES[@]}"; do
            az sql server firewall-rule delete \
                --resource-group "$RESOURCE_GROUP" --server "$SERVER_NAME" \
                --name "$rule_name" --output none 2>/dev/null || true
            ok "Firewall rule '$rule_name' removed"
        done
    fi
}
trap cleanup_firewall_rules EXIT

step "Detecting public IP(s) — probing multiple endpoints for multi-NIC support"

# Query several IP-detection services. Traffic may egress through different
# NICs depending on routing/DNS, so each service may return a different IP.
DETECTED_IPS=()
for endpoint in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com https://checkip.amazonaws.com; do
    ip=$(curl -fsS --max-time 5 "$endpoint" 2>/dev/null | tr -d '[:space:]' || true)
    if [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        # Add only if not already in the list
        local_dup=false
        for existing in "${DETECTED_IPS[@]+"${DETECTED_IPS[@]}"}"; do
            [[ "$existing" == "$ip" ]] && local_dup=true && break
        done
        if [[ "$local_dup" == "false" ]]; then
            DETECTED_IPS+=("$ip")
            ok "Detected IP: $ip (from $endpoint)"
        fi
    fi
done

if [[ ${#DETECTED_IPS[@]} -eq 0 ]]; then
    warn "Could not detect any public IP — ensure your IP is already allowed in SQL firewall"
else
    ok "Unique egress IPs detected: ${DETECTED_IPS[*]}"
    for ip in "${DETECTED_IPS[@]}"; do
        ensure_firewall_rule "$RESOURCE_GROUP" "$SERVER_NAME" "$ip"
    done
fi

# ---------------------------------------------------------------------------
# Connectivity test with retry + IP-mismatch recovery
# ---------------------------------------------------------------------------
# Firewall rule propagation can take up to 5 minutes. This function retries
# every 15 seconds. If the error reveals a different blocked IP (VPN/proxy
# egress), it returns that IP so the caller can create another rule.
# ---------------------------------------------------------------------------
test_sql_connectivity() {
    local max_retries=8 delay=15
    for (( i=1; i<=max_retries; i++ )); do
        local output
        output=$(run_sql_query "SELECT 1 AS probe" 2>&1) && return 0
        # Azure SQL error: "Client with IP address 'x.x.x.x' is not allowed"
        if [[ "$output" =~ Client\ with\ IP\ address\ \'([0-9.]+)\' ]]; then
            BLOCKED_IP="${BASH_REMATCH[1]}"
            warn "Attempt $i/$max_retries — blocked IP: $BLOCKED_IP"
            return 1
        fi
        if (( i < max_retries )); then
            echo -e "  ${YELLOW}Attempt $i/$max_retries — waiting ${delay}s for firewall propagation...${NC}"
            sleep "$delay"
        else
            warn "All $max_retries connectivity attempts failed"
            return 1
        fi
    done
}

# ---------------------------------------------------------------------------
# Check sqlcmd availability and detect variant
# ---------------------------------------------------------------------------
if ! command -v sqlcmd &>/dev/null; then
    echo "ERROR: sqlcmd not found. Install:" >&2
    echo "  Go sqlcmd (recommended): https://github.com/microsoft/go-sqlcmd" >&2
    echo "  macOS:  brew install microsoft/mssql-release/mssql-tools18" >&2
    echo "  Linux:  https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-setup-tools" >&2
    exit 1
fi

# Detect Go-based sqlcmd vs classic ODBC sqlcmd
SQLCMD_VERSION=$(sqlcmd --version 2>&1 || sqlcmd -? 2>&1 || echo "")
if echo "$SQLCMD_VERSION" | grep -qi "Install/Create/Query"; then
    SQLCMD_TYPE="go"
    ok "sqlcmd available (Go-based — uses ActiveDirectoryDefault auth)"
else
    SQLCMD_TYPE="classic"
    ok "sqlcmd available (classic ODBC)"
fi

# ---------------------------------------------------------------------------
# Acquire Entra token (classic sqlcmd only)
# ---------------------------------------------------------------------------
TOKEN=""
if [[ "$SQLCMD_TYPE" == "classic" ]]; then
    step "Acquiring Entra token for Azure SQL"
    TOKEN=$(az account get-access-token --resource https://database.windows.net --query accessToken -o tsv 2>/dev/null)
    if [[ -z "$TOKEN" ]]; then
        echo "ERROR: Failed to get access token. Run 'az login' first." >&2
        exit 1
    fi
    ok "Token acquired"
fi

# ---------------------------------------------------------------------------
# Helper: run SQL file or query via sqlcmd (handles both variants)
# ---------------------------------------------------------------------------
run_sql_file() {
    local file="$1"
    if [[ "$SQLCMD_TYPE" == "go" ]]; then
        sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
            --authentication-method ActiveDirectoryDefault \
            -i "$file" 2>&1
    else
        sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
            -G -P "$TOKEN" \
            -i "$file" \
            -C 2>&1
    fi
}

run_sql_query() {
    local query="$1"
    if [[ "$SQLCMD_TYPE" == "go" ]]; then
        sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
            --authentication-method ActiveDirectoryDefault \
            -Q "$query" 2>&1
    else
        sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
            -G -P "$TOKEN" \
            -Q "$query" \
            -C 2>&1
    fi
}

# ---------------------------------------------------------------------------
# Connectivity probe with retry + IP-mismatch recovery
# ---------------------------------------------------------------------------
step "Testing SQL connectivity (with firewall propagation retries)"

# Loop handles the case where Azure SQL sees additional egress IPs we
# missed (VPN split tunnels, load-balanced NAT gateways, etc.).
# Each iteration adds the newly-discovered IP and retries — up to 3 rounds.
# KNOWN_IPS tracks all IPs we've already created firewall rules for.
KNOWN_IPS=("${DETECTED_IPS[@]+"${DETECTED_IPS[@]}"}")
MAX_MISMATCH_ROUNDS=3
CONNECTED=false

for (( round=0; round<=MAX_MISMATCH_ROUNDS; round++ )); do
    BLOCKED_IP=""
    if test_sql_connectivity; then
        CONNECTED=true
        break
    fi

    if [[ -n "$BLOCKED_IP" ]]; then
        # Check if this IP is already known
        already_known=false
        for known in "${KNOWN_IPS[@]+"${KNOWN_IPS[@]}"}"; do
            [[ "$known" == "$BLOCKED_IP" ]] && already_known=true && break
        done
        if [[ "$already_known" == "false" ]]; then
            warn "Azure SQL sees an additional egress IP ($BLOCKED_IP) — adding firewall rule (round $((round + 1))/$MAX_MISMATCH_ROUNDS)"
            KNOWN_IPS+=("$BLOCKED_IP")
            ensure_firewall_rule "$RESOURCE_GROUP" "$SERVER_NAME" "$BLOCKED_IP"
            continue
        fi
    fi

    if (( round == MAX_MISMATCH_ROUNDS )); then
        echo "ERROR: Cannot connect to $SERVER_FQDN after $MAX_MISMATCH_ROUNDS IP-mismatch recovery rounds. Check VPN/network settings." >&2
        exit 1
    fi
done

if [[ "$CONNECTED" != "true" ]]; then
    echo "ERROR: Cannot connect to $SERVER_FQDN after firewall configuration. Check VPN/network settings." >&2
    exit 1
fi
ok "SQL connectivity confirmed"

# ---------------------------------------------------------------------------
# Run schema.sql
# ---------------------------------------------------------------------------
SCHEMA_FILE="$DATA_DIR/schema.sql"
if [[ -f "$SCHEMA_FILE" ]]; then
    step "Applying schema.sql"
    run_sql_file "$SCHEMA_FILE"
    ok "Schema applied"
else
    echo "ERROR: schema.sql not found at $SCHEMA_FILE" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Run seed.sql
# ---------------------------------------------------------------------------
SEED_FILE="$DATA_DIR/seed.sql"
if [[ -f "$SEED_FILE" ]]; then
    step "Applying seed.sql"
    run_sql_file "$SEED_FILE"
    ok "Seed data applied"
else
    echo "ERROR: seed.sql not found at $SEED_FILE" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Verify row counts
# ---------------------------------------------------------------------------
step "Verifying table row counts"
for TABLE in iq_devices iq_anomalies iq_tickets iq_remediation_log; do
    COUNT=$(run_sql_query "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.$TABLE" 2>/dev/null | tr -d '[:space:]' | grep -oE '[0-9]+' | tail -1)
    ok "$TABLE: ${COUNT:-0} rows"
done

# ---------------------------------------------------------------------------
# Grant permissions (optional)
# ---------------------------------------------------------------------------
if [[ "$GRANT_PERMISSIONS" == "true" ]]; then
    step "Granting managed identity permissions"

    # Resolve MI names from Bicep deployment outputs
    OUTPUTS=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name main \
        --query "properties.outputs" \
        --output json 2>/dev/null || echo "{}")

    MI_TOOLS_NAME=$(echo "$OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('miToolsName',{}).get('value',''))" 2>/dev/null || echo "")
    MI_AGENT_NAME=$(echo "$OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('miAgentName',{}).get('value',''))" 2>/dev/null || echo "")

    if [[ -z "$MI_TOOLS_NAME" ]]; then
        # Fallback: derive from naming convention
        ENV_SUFFIX="${RESOURCE_GROUP#rg-iq-lab-}"
        MI_TOOLS_NAME="id-iq-tools-iq-lab-$ENV_SUFFIX"
        MI_AGENT_NAME="id-iq-agent-iq-lab-$ENV_SUFFIX"
        warn "No Bicep outputs found — using derived names: $MI_TOOLS_NAME, $MI_AGENT_NAME"
    fi
    ok "MI Tools: $MI_TOOLS_NAME  |  MI Agent: $MI_AGENT_NAME"

    # Run each statement individually (graceful on duplicates)
    STATEMENTS=(
        "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$MI_TOOLS_NAME') CREATE USER [$MI_TOOLS_NAME] FROM EXTERNAL PROVIDER;"
        "ALTER ROLE db_datareader ADD MEMBER [$MI_TOOLS_NAME];"
        "GRANT INSERT ON dbo.iq_remediation_log TO [$MI_TOOLS_NAME];"
        "GRANT UPDATE ON dbo.iq_remediation_log TO [$MI_TOOLS_NAME];"
        "GRANT UPDATE ON dbo.iq_tickets TO [$MI_TOOLS_NAME];"
        "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$MI_AGENT_NAME') CREATE USER [$MI_AGENT_NAME] FROM EXTERNAL PROVIDER;"
        "ALTER ROLE db_datareader ADD MEMBER [$MI_AGENT_NAME];"
    )

    for STMT in "${STATEMENTS[@]}"; do
        run_sql_query "$STMT" 2>/dev/null || warn "Statement failed (may be OK if already applied): $STMT"
    done
    ok "Managed identity permissions granted"
fi

echo -e "\n${GREEN}Database seeding complete.${NC}"
