#!/usr/bin/env bash
# Packages and deploys one Azure Functions service (ingestion or decision-engine).
#
# Vendors dhara_shared as a plain sibling package (Oryx's remote build only
# installs requirements.txt -- it has no access to packages/dhara_shared on
# the local filesystem, so we copy it in rather than fight a relative
# editable-install path across a deployment boundary).
#
# Uses Azure Functions Core Tools (`func azure functionapp publish --build
# remote`), NOT `az functionapp deployment source config-zip`: the latter
# reported success but silently produced zero indexed functions in testing
# against a Linux Consumption Python app -- func core tools' remote-build
# path is the one that actually works reliably.
#
# Usage: scripts/deploy_function.sh <ingestion|decision-engine> <function-app-name>
set -euo pipefail

SERVICE="$1"
FUNC_APP_NAME="$2"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_DIR="$(mktemp -d)"

command -v func >/dev/null 2>&1 || {
  echo "Azure Functions Core Tools not found. Install with: npm install -g azure-functions-core-tools@4" >&2
  exit 1
}

echo "Staging $SERVICE in $STAGE_DIR ..."
cp -r "$ROOT_DIR/services/$SERVICE/." "$STAGE_DIR/"
cp -r "$ROOT_DIR/packages/dhara_shared/dhara_shared" "$STAGE_DIR/dhara_shared"

# dhara_shared's config.py needs pydantic-settings; the rest of what these
# workers import (frame_codec, water_balance, energy_optimizer, weather,
# shelf_life) is stdlib + httpx, already in each service's requirements.txt.
grep -q "pydantic-settings" "$STAGE_DIR/requirements.txt" || echo "pydantic-settings>=2.3" >> "$STAGE_DIR/requirements.txt"

find "$STAGE_DIR" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
rm -f "$STAGE_DIR/Dockerfile" "$STAGE_DIR/Dockerfile.local" "$STAGE_DIR/local_runner.py"

echo "Deploying to $FUNC_APP_NAME (remote build)..."
(cd "$STAGE_DIR" && func azure functionapp publish "$FUNC_APP_NAME" --python --build remote)

rm -rf "$STAGE_DIR"
echo "Done. Verify with: az functionapp function list -g dhara-platform-rg -n $FUNC_APP_NAME --query '[].name' -o tsv"
