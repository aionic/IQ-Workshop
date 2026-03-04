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
    echo "  --skip-bicep                Skip Bicep deployment"
    echo "  --skip-image                Skip image build + container update"
    echo "  -s, --seed-database         Seed database after deployment"
    echo "  -h, --help                  Show this help"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -g|--resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
        -l|--location)       LOCATION="$2"; shift 2 ;;
        -p|--parameters)     PARAMETER_FILE="$2"; shift 2 ;;
        -t|--image-tag)      IMAGE_TAG="$2"; shift 2 ;;
        --skip-bicep)        SKIP_BICEP=true; shift ;;
        --skip-image)        SKIP_IMAGE=true; shift ;;
        -s|--seed-database)  SEED_DATABASE=true; shift ;;
        -h|--help)           usage ;;
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
# Step 1: Bicep deployment
# ---------------------------------------------------------------------------
if [[ "$SKIP_BICEP" == "false" ]]; then
    step "Deploying Bicep infrastructure"
    echo "  Template:   $BICEP_FILE"
    echo "  Parameters: $PARAMETER_FILE"
    echo "  RG:         $RESOURCE_GROUP"

    DEPLOYMENT=$(az deployment group create \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "$BICEP_FILE" \
        --parameters "$PARAMETER_FILE" \
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
        "$API_TOOLS_DIR" >/dev/null 2>&1
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
# Step 3: Seed database (optional)
# ---------------------------------------------------------------------------
if [[ "$SEED_DATABASE" == "true" ]]; then
    step "Seeding Azure SQL database"
    "$SCRIPT_DIR/seed-database.sh" -g "$RESOURCE_GROUP"
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
echo "Next steps:"
echo "  1. Grant MI permissions: ./scripts/seed-database.sh -g $RESOURCE_GROUP --grant-permissions"
echo "  2. Register Foundry agent: ./scripts/register-agent.sh -g $RESOURCE_GROUP"
echo "  3. Open AI Foundry playground and test the agent"
echo ""
