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
# Acquire Entra token
# ---------------------------------------------------------------------------
step "Acquiring Entra token for Azure SQL"
TOKEN=$(az account get-access-token --resource https://database.windows.net --query accessToken -o tsv 2>/dev/null)
if [[ -z "$TOKEN" ]]; then
    echo "ERROR: Failed to get access token. Run 'az login' first." >&2
    exit 1
fi
ok "Token acquired"

# ---------------------------------------------------------------------------
# Check sqlcmd availability
# ---------------------------------------------------------------------------
if ! command -v sqlcmd &>/dev/null; then
    echo "ERROR: sqlcmd not found. Install:" >&2
    echo "  macOS:  brew install microsoft/mssql-release/mssql-tools18" >&2
    echo "  Linux:  https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-setup-tools" >&2
    exit 1
fi
ok "sqlcmd available"

# ---------------------------------------------------------------------------
# Run schema.sql
# ---------------------------------------------------------------------------
SCHEMA_FILE="$DATA_DIR/schema.sql"
if [[ -f "$SCHEMA_FILE" ]]; then
    step "Applying schema.sql"
    sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
        -G -P "$TOKEN" \
        -i "$SCHEMA_FILE" \
        -C  # Trust server certificate
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
    sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
        -G -P "$TOKEN" \
        -i "$SEED_FILE" \
        -C
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
    COUNT=$(sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
        -G -P "$TOKEN" \
        -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.$TABLE" \
        -h -1 -C 2>/dev/null | tr -d '[:space:]')
    ok "$TABLE: $COUNT rows"
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
        sqlcmd -S "$SERVER_FQDN" -d "$DATABASE_NAME" \
            -G -P "$TOKEN" \
            -Q "$STMT" \
            -C 2>/dev/null || warn "Statement failed (may be OK if already applied): $STMT"
    done
    ok "Managed identity permissions granted"
fi

echo -e "\n${GREEN}Database seeding complete.${NC}"
