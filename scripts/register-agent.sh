#!/usr/bin/env bash
# ============================================================================
# register-agent.sh — Register the IQ triage agent in Azure AI Foundry
#
# Resolves all values from Bicep deployment outputs and creates the agent
# via Agent Framework v2 SDK (scripts/create_agent.py) using uv run.
#
# Usage:
#   ./scripts/register-agent.sh                         # auto-create via SDK
#   ./scripts/register-agent.sh --manual-only            # show portal steps
#   ./scripts/register-agent.sh -g rg-iq-lab-staging     # different RG
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-iq-lab-dev"
AGENT_NAME="iq-triage-agent"
MANUAL_ONLY=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -g, --resource-group NAME   Resource group (default: rg-iq-lab-dev)"
    echo "  -n, --agent-name NAME       Agent name (default: iq-triage-agent)"
    echo "  --manual-only               Skip SDK creation; show portal instructions"
    echo "  -h, --help                  Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -g|--resource-group)  RESOURCE_GROUP="$2"; shift 2 ;;
        -n|--agent-name)      AGENT_NAME="$2"; shift 2 ;;
        --manual-only)        MANUAL_ONLY=true; shift ;;
        -h|--help)            usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
NC='\033[0m'

step() { echo -e "\n${CYAN}===> $1${NC}"; }
ok()   { echo -e "  ${GREEN}OK: $1${NC}"; }
warn() { echo -e "  ${YELLOW}WARN: $1${NC}"; }

# ---------------------------------------------------------------------------
# Resolve deployment outputs from Bicep
# ---------------------------------------------------------------------------
step "Resolving deployment outputs from $RESOURCE_GROUP"

OUTPUTS_RAW=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name main \
    --query "properties.outputs" \
    --output json 2>/dev/null || echo "")

if [[ -z "$OUTPUTS_RAW" || "$OUTPUTS_RAW" == "{}" ]]; then
    echo "ERROR: No Bicep deployment named 'main' found in $RESOURCE_GROUP. Run deploy.sh first." >&2
    exit 1
fi

# Parse outputs via Python (universally available, no jq dependency)
get_output() {
    echo "$OUTPUTS_RAW" | python3 -c "import sys,json; print(json.load(sys.stdin).get('$1',{}).get('value',''))" 2>/dev/null
}

TOOL_SERVICE_URL=$(get_output "toolServiceUrl")
AI_SERVICES_NAME=$(get_output "aiServicesName")
AI_SERVICES_ENDPOINT=$(get_output "aiServicesEndpoint")
PROJECT_ENDPOINT=$(get_output "foundryProjectEndpoint")
PROJECT_NAME=$(get_output "foundryProjectName")
MODEL_DEPLOYMENT=$(get_output "aiModelDeploymentName")
UNIQUE_SUFFIX=$(get_output "uniqueSuffix")

ok "Tool Service:     $TOOL_SERVICE_URL"
ok "AI Services:      $AI_SERVICES_NAME"
ok "Foundry Project:  $PROJECT_NAME"
ok "Project Endpoint: $PROJECT_ENDPOINT"
ok "Model:            $MODEL_DEPLOYMENT"
ok "Unique Suffix:    $UNIQUE_SUFFIX"

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
step "Checking tool service health"
HEALTH_RESPONSE=$(curl -sf --max-time 10 "$TOOL_SERVICE_URL/health" 2>/dev/null || echo "")

if [[ -z "$HEALTH_RESPONSE" ]]; then
    echo "ERROR: Tool service at $TOOL_SERVICE_URL is not responding." >&2
    exit 1
fi

DB_STATUS=$(echo "$HEALTH_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('db','unknown'))" 2>/dev/null)

if [[ "$DB_STATUS" == "connected" ]]; then
    ok "Tool service healthy (db=connected)"
else
    warn "Tool service health: db=$DB_STATUS — DB may need attention"
fi

# ---------------------------------------------------------------------------
# Load system prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_PATH="$REPO_ROOT/foundry/prompts/system.md"
if [[ ! -f "$SYSTEM_PROMPT_PATH" ]]; then
    echo "ERROR: System prompt not found at $SYSTEM_PROMPT_PATH" >&2
    exit 1
fi
PROMPT_LENGTH=$(wc -c < "$SYSTEM_PROMPT_PATH" | tr -d '[:space:]')
ok "System prompt loaded ($PROMPT_LENGTH chars)"

# ---------------------------------------------------------------------------
# Create agent via SDK (unless --manual-only)
# ---------------------------------------------------------------------------
if [[ "$MANUAL_ONLY" == "false" ]]; then
    step "Creating agent via Foundry Agent SDK (uv run)"

    if ! command -v uv &>/dev/null; then
        warn "uv not found — install from https://docs.astral.sh/uv/getting-started/installation/"
        warn "Falling back to manual instructions below."
        MANUAL_ONLY=true
    else
        CREATE_SCRIPT="$REPO_ROOT/scripts/create_agent.py"
        SUFFIX_ARGS=()
        if [[ -n "$UNIQUE_SUFFIX" ]]; then
            SUFFIX_ARGS=("--suffix" "$UNIQUE_SUFFIX")
        fi
        echo "  Running: uv run $CREATE_SCRIPT --resource-group $RESOURCE_GROUP ${SUFFIX_ARGS[*]}"

        if uv run "$CREATE_SCRIPT" --resource-group "$RESOURCE_GROUP" "${SUFFIX_ARGS[@]}"; then
            ok "Agent created successfully"
        else
            warn "Agent creation failed (exit code $?)"
            warn "Displaying manual instructions instead."
            MANUAL_ONLY=true
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Manual registration instructions
# ---------------------------------------------------------------------------
if [[ "$MANUAL_ONLY" == "true" ]]; then
    step "Manual Agent Registration (AI Foundry Portal)"

    echo -e "${WHITE}"
    cat <<EOF

  +------------------------------------------------------------------+
  |                    FOUNDRY AGENT CONFIGURATION                   |
  +------------------------------------------------------------------+
  |                                                                  |
  |  Agent Name:        $AGENT_NAME
  |  Model Deployment:  $MODEL_DEPLOYMENT
  |  AI Services:       $AI_SERVICES_ENDPOINT
  |  Project Endpoint:  $PROJECT_ENDPOINT
  |  Tool Service URL:  $TOOL_SERVICE_URL
  |                                                                  |
  |  -- System Prompt --                                             |
  |  File: foundry/prompts/system.md                                 |
  |  (Copy the full contents into the agent's Instructions field)    |
  |                                                                  |
  |  -- Tools --                                                     |
  |  Function tools (Responses API compatible, auto-generated by     |
  |  FunctionTool in scripts/create_agent.py). Client-side execution |
  |  via scripts/chat_agent.py.                                      |
  |                                                                  |
  +------------------------------------------------------------------+

  Steps:
    1. Go to https://ai.azure.com
    2. Open project: $PROJECT_NAME
    3. Navigate to 'Agents' in the left menu
    4. Click '+ New Agent'
    5. Select model: $MODEL_DEPLOYMENT
    6. Paste the system prompt from foundry/prompts/system.md
    7. Add function tools (see create_agent.py for definitions)
    8. Test with: uv run scripts/chat_agent.py --resource-group $RESOURCE_GROUP

EOF
    echo -e "${NC}"
fi

# ---------------------------------------------------------------------------
# Test prompts
# ---------------------------------------------------------------------------
step "Sample test prompts for the Foundry playground"

cat <<EOF

  Once the agent is registered, test with these prompts:

  1. "Summarize ticket TKT-0042"
     -> Should call query-ticket-context, return a 3-bullet triage summary

  2. "What's the status of TKT-0018?"
     -> Should query context, cite severity/signal_type/metrics

  3. "Remediate TKT-0042 by restarting BGP sessions"
     -> Should call request-approval, then wait for human approval

  4. "Post a summary to Teams for TKT-0042"
     -> Should call post-teams-summary (logged, not posted unless webhook set)

EOF

echo -e "\n${GREEN}Agent registration complete.${NC}"
