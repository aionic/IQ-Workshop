#!/usr/bin/env bash
# ============================================================================
# deploy.sh — Deploy IQ Foundry Agent Lab to Azure
#
# Turnkey deployment: Bicep infra + container image build + optional DB seed.
#
# Usage:
#   ./scripts/deploy.sh                              # full deployment
#   ./scripts/deploy.sh -s                            # full + seed database
#   ./scripts/deploy.sh --skip-bicep -t v5            # image only
#   ./scripts/deploy.sh --skip-image                  # bicep only
# ============================================================================

set -euo pipefail

# Work around .NET ICU issue in WSL (Bicep CLI needs this)
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-iq-lab-dev"
LOCATION="westus3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PARAMETER_FILE="$REPO_ROOT/infra/bicep/parameters.dev.json"
BICEP_FILE="$REPO_ROOT/infra/bicep/main.bicep"
API_TOOLS_DIR="$REPO_ROOT/services/api-tools"
IMAGE_TAG="v$(date +%Y%m%d-%H%M)"
SKIP_BICEP=false
SKIP_IMAGE=false
SEED_DATABASE=false
UNIQUE_SUFFIX=""
SKIP_ROLE_ASSIGNMENTS=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -g, --resource-group NAME   Resource group (default: rg-iq-lab-dev)"
    echo "  -l, --location REGION       Azure region (default: westus3)"
    echo "  -p, --parameters FILE       Bicep parameters file"
    echo "  -t, --image-tag TAG         Docker image tag (default: timestamp)"
    echo "  -u, --unique-suffix SUFFIX  Short suffix for globally-unique names (e.g. an42)"
    echo "  --skip-bicep                Skip Bicep deployment"
    echo "  --skip-image                Skip image build + container update"
    echo "  --skip-role-assignments     Skip RBAC role assignments (Contributor-only)"
    echo "  -s, --seed-database         Seed database after deployment"
    echo "  -h, --help                  Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -g|--resource-group)       RESOURCE_GROUP="$2"; shift 2 ;;
        -l|--location)             LOCATION="$2"; shift 2 ;;
        -p|--parameters)           PARAMETER_FILE="$2"; shift 2 ;;
        -t|--image-tag)            IMAGE_TAG="$2"; shift 2 ;;
        -u|--unique-suffix)        UNIQUE_SUFFIX="$2"; shift 2 ;;
        --skip-bicep)              SKIP_BICEP=true; shift ;;
        --skip-image)              SKIP_IMAGE=true; shift ;;
        --skip-role-assignments)   SKIP_ROLE_ASSIGNMENTS=true; shift ;;
        -s|--seed-database)        SEED_DATABASE=true; shift ;;
        -h|--help)                 usage ;;
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
# Pre-flight checks
# ---------------------------------------------------------------------------
step "Pre-flight checks"

if ! command -v az &>/dev/null; then
    echo "ERROR: Azure CLI not found. Install from https://aka.ms/installazurecli" >&2
    exit 1
fi
ok "Azure CLI $(az version --query '\"azure-cli\"' -o tsv 2>/dev/null)"

ACCOUNT=$(az account show --query '{name:name, id:id}' -o tsv 2>/dev/null || true)
if [[ -z "$ACCOUNT" ]]; then
    echo "ERROR: Not logged in. Run 'az login' first." >&2
    exit 1
fi
ok "Subscription: $(az account show --query 'name' -o tsv)"

# Ensure resource group exists
RG_EXISTS=$(az group exists --name "$RESOURCE_GROUP" 2>/dev/null)
if [[ "$RG_EXISTS" == "false" ]]; then
    step "Creating resource group $RESOURCE_GROUP in $LOCATION"
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
    ok "Resource group created"
else
    ok "Resource group $RESOURCE_GROUP exists"
fi

# ---------------------------------------------------------------------------
# Step 0.5: Purge soft-deleted Cognitive Services if they conflict
# ---------------------------------------------------------------------------
# When a resource group is deleted, Azure soft-deletes Cognitive Services
# accounts for 48 hours. Re-deploying the same Bicep template within that
# window fails with FlagMustBeSetForRestore. This function detects any
# soft-deleted accounts that match the target resource group and prompts
# the operator to purge them before proceeding.
# ---------------------------------------------------------------------------
resolve_soft_deleted_cognitive_services() {
    local rg="$1" loc="$2"
    step "Checking for soft-deleted Cognitive Services accounts"
    local raw
    raw=$(az cognitiveservices account list-deleted \
        --query "[?contains(id, '$rg')].{name:name, location:location}" \
        --output tsv 2>/dev/null || true)
    if [[ -z "$raw" ]]; then
        ok "No conflicting soft-deleted accounts"
        return
    fi
    while IFS=$'\t' read -r name item_loc; do
        [[ -z "$name" ]] && continue
        warn "Found soft-deleted Cognitive Services: $name (location: $item_loc)"
        read -rp "  Purge '$name' so it can be recreated? (Y/n) " choice
        if [[ -z "$choice" || "$choice" =~ ^[Yy] ]]; then
            echo "  Purging $name ..." >&2
            if ! az cognitiveservices account purge --name "$name" --resource-group "$rg" --location "$item_loc" --output none 2>/dev/null; then
                echo "ERROR: Failed to purge '$name'. Manual: az cognitiveservices account purge --name $name --resource-group $rg --location $item_loc" >&2
                exit 1
            fi
            ok "Purged $name"
        else
            echo "ERROR: Cannot proceed — soft-deleted account '$name' blocks deployment. Purge it or restore manually." >&2
            exit 1
        fi
    done <<< "$raw"
}

# ---------------------------------------------------------------------------
# Step 1: Bicep deployment
# ---------------------------------------------------------------------------
if [[ "$SKIP_BICEP" == "false" ]]; then
    resolve_soft_deleted_cognitive_services "$RESOURCE_GROUP" "$LOCATION"

    # ---------------------------------------------------------------
    # Prompt for unique suffix if not provided (avoids global name
    # collisions on SQL Server, ACR, AI Services)
    # ---------------------------------------------------------------
    if [[ -z "$UNIQUE_SUFFIX" ]]; then
        echo ""
        warn "Resource names for SQL Server, ACR, and AI Services must be globally"
        warn "unique across all Azure tenants. A short suffix avoids collisions."
        read -rp "  Enter a unique suffix (e.g. your initials + 2 digits: an42) or press Enter to skip: " UNIQUE_SUFFIX
    fi

    # Build parameter overrides
    BICEP_OVERRIDES=()
    if [[ -n "$UNIQUE_SUFFIX" ]]; then
        BICEP_OVERRIDES+=("--parameters" "uniqueSuffix=$UNIQUE_SUFFIX")
    fi
    if [[ "$SKIP_ROLE_ASSIGNMENTS" == "true" ]]; then
        BICEP_OVERRIDES+=("--parameters" "skipRoleAssignments=true")
    fi

    step "Deploying Bicep infrastructure"
    echo "  Template:   $BICEP_FILE"
    echo "  Parameters: $PARAMETER_FILE"
    echo "  RG:         $RESOURCE_GROUP"
    [[ -n "$UNIQUE_SUFFIX" ]] && echo "  Suffix:     $UNIQUE_SUFFIX"
    [[ "$SKIP_ROLE_ASSIGNMENTS" == "true" ]] && warn "RBAC: skipped (Contributor-only mode)"

    DEPLOYMENT=$(az deployment group create \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "$BICEP_FILE" \
        --parameters "$PARAMETER_FILE" \
        "${BICEP_OVERRIDES[@]}" \
        --query "properties.{state:provisioningState, outputs:outputs}" \
        --output json 2>&1)

    STATE=$(echo "$DEPLOYMENT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "")
    if [[ "$STATE" != "Succeeded" ]]; then
        echo "ERROR: Bicep deployment failed" >&2
        echo "$DEPLOYMENT" >&2
        exit 1
    fi

    ok "Bicep deployment succeeded"
    echo "  Tool Service URL:  $(echo "$DEPLOYMENT" | python3 -c "import sys,json; print(json.load(sys.stdin)['outputs']['toolServiceUrl']['value'])" 2>/dev/null)"
    echo "  AI Services:       $(echo "$DEPLOYMENT" | python3 -c "import sys,json; print(json.load(sys.stdin)['outputs']['aiServicesName']['value'])" 2>/dev/null)"
    echo "  Model Deployment:  $(echo "$DEPLOYMENT" | python3 -c "import sys,json; print(json.load(sys.stdin)['outputs']['aiModelDeploymentName']['value'])" 2>/dev/null)"
    echo "  ACR:               $(echo "$DEPLOYMENT" | python3 -c "import sys,json; print(json.load(sys.stdin)['outputs']['acrLoginServer']['value'])" 2>/dev/null)"
    echo "  SQL Server:        $(echo "$DEPLOYMENT" | python3 -c "import sys,json; print(json.load(sys.stdin)['outputs']['sqlServerFqdn']['value'])" 2>/dev/null)"
else
    warn "Skipping Bicep deployment (--skip-bicep)"
fi

# Fetch outputs for subsequent steps
OUTPUTS=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name main \
    --query "properties.outputs" \
    --output json 2>/dev/null || echo "{}")

# ---------------------------------------------------------------------------
# Step 2: Build and deploy container image
# ---------------------------------------------------------------------------
if [[ "$SKIP_IMAGE" == "false" ]]; then
    ACR_NAME=$(echo "$OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('acrLoginServer',{}).get('value','').split('.')[0])" 2>/dev/null || \
        az acr list -g "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)
    IMAGE_FULL="$ACR_NAME.azurecr.io/iq-tools:$IMAGE_TAG"

    step "Building container image: $IMAGE_FULL"
    az acr build \
        --registry "$ACR_NAME" \
        --image "iq-tools:$IMAGE_TAG" \
        --platform linux/amd64 \
        "$API_TOOLS_DIR"
    ok "Image built: $IMAGE_FULL"

    step "Updating Container App with new image"
    TOOL_URL=$(echo "$OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('toolServiceUrl',{}).get('value',''))" 2>/dev/null || echo "")
    CA_NAME=$(echo "${TOOL_URL#https://}" | cut -d. -f1)
    if [[ -z "$CA_NAME" ]]; then
        CA_NAME=$(az containerapp list -g "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)
    fi

    az containerapp update \
        --name "$CA_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$IMAGE_FULL" \
        --output none
    ok "Container App updated to $IMAGE_FULL"
else
    warn "Skipping image build (--skip-image)"
fi

# ---------------------------------------------------------------------------
# Step 3: Seed database + grant MI permissions (optional)
# ---------------------------------------------------------------------------
# When -s/--seed-database is set, we also pass --grant-permissions so the
# Container App's managed identity (id-iq-tools-*) is created as a SQL
# user and granted the read/write roles it needs. Without this, every
# DB-dependent endpoint returns 503 "db unavailable".
# ---------------------------------------------------------------------------
if [[ "$SEED_DATABASE" == "true" ]]; then
    step "Seeding Azure SQL database (with MI permissions)"
    "$SCRIPT_DIR/seed-database.sh" -g "$RESOURCE_GROUP" --grant-permissions
    # Give the Container App a few seconds to pick up DB connectivity
    # after MI permissions are granted (token cache refresh)
    echo -e "  ${YELLOW}Waiting 10s for managed identity token propagation...${NC}"
    sleep 10
fi

# ---------------------------------------------------------------------------
# Step 4: Smoke test
# ---------------------------------------------------------------------------
step "Running smoke test"
"$SCRIPT_DIR/smoke-test.sh" -g "$RESOURCE_GROUP"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Deployment complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# Post-deploy: role assignment commands for Contributor-only deploys
# ---------------------------------------------------------------------------
if [[ "$SKIP_ROLE_ASSIGNMENTS" == "true" ]]; then
    echo ""
    echo -e "  ${YELLOW}RBAC ROLE ASSIGNMENTS WERE SKIPPED.${NC}"
    echo -e "  ${YELLOW}Ask an Owner or RBAC Administrator to run these 3 commands:${NC}"
    echo ""
    # Fetch principal IDs from deployment outputs
    _OUTPUTS=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name main \
        --query "properties.outputs" \
        --output json 2>/dev/null || echo "{}")
    _MI_TOOLS_PID=$(echo "$_OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('miToolsPrincipalId',{}).get('value','<miToolsPrincipalId>'))" 2>/dev/null || echo "<miToolsPrincipalId>")
    _MI_AGENT_PID=$(echo "$_OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('miAgentPrincipalId',{}).get('value','<miAgentPrincipalId>'))" 2>/dev/null || echo "<miAgentPrincipalId>")
    _ACR_NAME=$(echo "$_OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('acrLoginServer',{}).get('value','').split('.')[0])" 2>/dev/null || echo "<acrName>")
    _AI_NAME=$(echo "$_OUTPUTS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('aiServicesName',{}).get('value','<aiServicesName>'))" 2>/dev/null || echo "<aiServicesName>")
    _SUB_ID=$(az account show --query id -o tsv 2>/dev/null)
    _ACR_ID="/subscriptions/$_SUB_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ContainerRegistry/registries/$_ACR_NAME"
    _AI_ID="/subscriptions/$_SUB_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$_AI_NAME"

    echo "  # 1. AcrPull — let Container Apps pull images"
    echo "  az role assignment create --assignee-object-id $_MI_TOOLS_PID --assignee-principal-type ServicePrincipal --role 'AcrPull' --scope $_ACR_ID"
    echo ""
    echo "  # 2. Cognitive Services OpenAI User — tool service MI"
    echo "  az role assignment create --assignee-object-id $_MI_TOOLS_PID --assignee-principal-type ServicePrincipal --role 'Cognitive Services OpenAI User' --scope $_AI_ID"
    echo ""
    echo "  # 3. Cognitive Services OpenAI User — agent MI"
    echo "  az role assignment create --assignee-object-id $_MI_AGENT_PID --assignee-principal-type ServicePrincipal --role 'Cognitive Services OpenAI User' --scope $_AI_ID"
    echo ""
fi

STEP=1
echo "Next steps:"
if [[ "$SEED_DATABASE" == "false" ]]; then
    echo "  $STEP. Seed + grant MI permissions: ./scripts/deploy.sh -s --skip-bicep --skip-image"
    STEP=$((STEP + 1))
fi
if [[ "$SKIP_ROLE_ASSIGNMENTS" == "true" ]]; then
    echo "  $STEP. Create the 3 RBAC role assignments shown above (requires Owner or RBAC Admin)"
    STEP=$((STEP + 1))
fi
echo "  $STEP. Register Foundry agent: ./scripts/register-agent.sh -g $RESOURCE_GROUP"
STEP=$((STEP + 1))
echo "  $STEP. Open AI Foundry playground and test the agent"
echo ""
