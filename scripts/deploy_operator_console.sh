#!/usr/bin/env bash
# Builds the operator console and deploys it to the Azure Static Web App
# created by infra/main.bicep.
set -euo pipefail

RG="dhara-platform-rg"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONSOLE_DIR="$ROOT_DIR/apps/operator-console"

API_URL=$(az deployment group show -g "$RG" -n main --query "properties.outputs.apiUrl.value" -o tsv)
SWA_NAME=$(az deployment group show -g "$RG" -n main --query "properties.outputs.staticWebAppName.value" -o tsv)

echo "API_URL=$API_URL"
echo "VITE_API_BASE_URL=$API_URL" > "$CONSOLE_DIR/.env.production"

echo "Installing dependencies and building..."
(cd "$CONSOLE_DIR" && npm install && npm run build)

DEPLOY_TOKEN=$(az staticwebapp secrets list -g "$RG" -n "$SWA_NAME" --query "properties.apiKey" -o tsv)

echo "Deploying to Static Web App $SWA_NAME ..."
npx --yes @azure/static-web-apps-cli deploy "$CONSOLE_DIR/dist" \
  --deployment-token "$DEPLOY_TOKEN" \
  --env production

echo "Done. Console URL:"
az staticwebapp show -g "$RG" -n "$SWA_NAME" --query "defaultHostname" -o tsv
