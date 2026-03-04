#!/usr/bin/env bash
# Quick prerequisite check for WSL
echo "=== WSL Environment Check ==="
echo "az CLI:   $(az version 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["azure-cli"])' 2>/dev/null || echo 'NOT FOUND')"
echo "curl:     $(curl --version 2>/dev/null | head -1 | cut -d' ' -f1-2 || echo 'NOT FOUND')"
echo "python3:  $(python3 --version 2>/dev/null || echo 'NOT FOUND')"
echo "uv:       $(uv --version 2>/dev/null || echo 'NOT FOUND')"
echo ""
echo "=== Azure Account ==="
az account show --query "{name:name, id:id}" -o table 2>/dev/null || echo "NOT LOGGED IN - run: az login"
echo ""
echo "=== RG Status ==="
EXISTS=$(az group exists --name rg-iq-lab-dev 2>/dev/null)
echo "rg-iq-lab-dev exists: $EXISTS"
