# Setup Guide

This walks through deploying DHARA from zero, on Azure, exactly as this reference
deployment was built -- including the two real problems hit along the way and how
they were fixed, so a future deploy (or a fresh one in a different subscription)
doesn't have to rediscover them. Windows/Git Bash commands; adapt trivially for
macOS/Linux.

## Prerequisites

- **Azure CLI** (`az`), logged in: `az login`, then `az account set --subscription "<name-or-id>"`
- **Docker Desktop**, running (`docker info` should succeed) -- used for the `api`,
  `advisory-bot`, and `ingestion` container images, and for running the edge
  simulator (its `azure-iot-device`/`azure-iot-hub` dependency, `uamqp`, has no
  prebuilt wheel for very new local Python versions; running it in the
  `python:3.12-slim`-based Docker image sidesteps that entirely)
- **Python 3.12+** (for local scripts; the deployed services all pin 3.12 in Docker/Functions regardless of your local version)
- **Node.js 18+** and npm (operator console)
- **Bicep CLI**: `az bicep install`
- **Azure Functions Core Tools**: `npm install -g azure-functions-core-tools@4`
  (used to deploy `decision-engine` -- see the note in step 9 on why
  `az functionapp deployment source config-zip` is not used)
- **Azure CLI extensions**, installed on first use or up front:
  `az extension add --name azure-iot --yes`, `az extension add --name communication --yes`

Check which regions your subscription allows before you start (some student/sponsored
subscriptions restrict this):
```bash
az policy assignment list --query "[?displayName=='Allowed resource deployment regions']"
```

---

## 1. Clone and generate secrets

```bash
cd "DHARA"   # repo root
mkdir -p .secrets

python -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(24)))" > .secrets/postgres_admin_password.txt
python -c "import secrets; print(secrets.token_hex(32))" > .secrets/api_shared_secret.txt
python -c "import secrets,string; print(''.join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(8)))" > .secrets/unique_suffix.txt
```

## 2. Create the resource group

```bash
az group create --name dhara-platform-rg --location centralindia
```

## 3. Register resource providers (first time on a subscription only)

```bash
for p in Microsoft.Devices Microsoft.DBforPostgreSQL Microsoft.App Microsoft.Communication \
         Microsoft.ContainerRegistry Microsoft.OperationalInsights Microsoft.Insights \
         Microsoft.KeyVault Microsoft.Storage Microsoft.Web Microsoft.ManagedIdentity; do
  az provider register -n $p --wait
done
```

## 4. Deploy the Container Registry first (chicken-and-egg with the images)

```bash
SUFFIX=$(cat .secrets/unique_suffix.txt)
az deployment group create \
  --resource-group dhara-platform-rg \
  --template-file infra/acr-only.bicep \
  --parameters prefix=dhara uniqueSuffix=$SUFFIX
```
Note the `acrLoginServer` output.

## 5. Build and push the three service images

Azure for Students subscriptions disallow ACR Tasks (`az acr build` fails with
`TasksOperationsNotAllowed`), so build locally and push:
```bash
ACR_NAME="dhara<suffix>"   # from step 4's output, no dashes
az acr login --name $ACR_NAME

docker build -f services/api/Dockerfile -t $ACR_NAME.azurecr.io/dhara-api:v1 .
docker push $ACR_NAME.azurecr.io/dhara-api:v1

docker build -f services/advisory-bot/Dockerfile -t $ACR_NAME.azurecr.io/dhara-advisory-bot:v1 .
docker push $ACR_NAME.azurecr.io/dhara-advisory-bot:v1

docker build -f services/ingestion/Dockerfile -t $ACR_NAME.azurecr.io/dhara-ingestion:v1 .
docker push $ACR_NAME.azurecr.io/dhara-ingestion:v1
```

## 6. Check Azure OpenAI model availability in your allowed regions

Model availability and deprecation status shift over time. Before deploying, check
which of your allowed regions currently supports `GlobalStandard` for a current
non-deprecating model:
```bash
az rest --method get --url "https://management.azure.com/subscriptions/<sub-id>/providers/Microsoft.CognitiveServices/locations/<region>/models?api-version=2023-05-01" \
  | grep -A20 '"name": "gpt-4.1-mini"'
```
Update `openAiLocation` and the model name/version in `infra/main.bicep`'s
`openAiDeployment` resource if needed. No Azure OpenAI access at all? Deploy with
`deployOpenAi=false` (see `docs/azure-requirements.md` §6).

## 7. Deploy everything else

```bash
PG_PASSWORD=$(cat .secrets/postgres_admin_password.txt)
SUFFIX=$(cat .secrets/unique_suffix.txt)
API_SECRET=$(cat .secrets/api_shared_secret.txt)

az deployment group create \
  --resource-group dhara-platform-rg \
  --template-file infra/main.bicep \
  --parameters prefix=dhara uniqueSuffix=$SUFFIX \
               postgresAdminPassword="$PG_PASSWORD" \
               apiSharedSecret="$API_SECRET" \
               imageTag=v1 deployOpenAi=true
```
Takes 15-25 minutes (PostgreSQL and the Container Apps environment are the slow
parts). Creates: Log Analytics, App Insights, a user-assigned managed identity, Key
Vault, Storage, PostgreSQL Flexible Server, IoT Hub (with a dedicated
`ingestion-consumer` consumer group and its fallback route explicitly enabled --
see the war story below), Container Apps environment + the `api`, `advisory-bot`,
and `ingestion` apps, one Flex Consumption Function App (`decision-engine`),
Communication Services, Speech, Azure OpenAI/AIServices, and the Static Web App shell.

## 8. Pull every live secret into `.env`

```bash
bash scripts/export-env.sh
```

## 9. Deploy the decision-engine Function App's code

```bash
DECISION_NAME=$(az deployment group show -g dhara-platform-rg -n main --query properties.outputs.decisionFunctionAppName.value -o tsv)
bash scripts/deploy_function.sh decision-engine "$DECISION_NAME"
```
This uses Azure Functions Core Tools (`func azure functionapp publish --build
remote`), not `az functionapp deployment source config-zip` -- the latter reported
`Deployment successful` while silently indexing zero functions in earlier testing,
with no error surfaced anywhere. Always check the final "Functions in `<app>`:"
output lists what you expect:
```bash
az functionapp function list -g dhara-platform-rg -n "$DECISION_NAME" --query "[].name" -o tsv
```
(`ingestion` needs no separate code deployment step -- its image already has
`consumer.py` baked in from step 5; `docker build` + `az containerapp update
--image ...` is how you ship a new version of it later.)

## 10. Set up Microsoft Entra ID for the operator console

```bash
APP_JSON=$(az ad app create --display-name "DHARA Operator Console" \
  --sign-in-audience AzureADMyOrg -o json)
APP_ID=$(echo "$APP_JSON" | python -c "import json,sys; print(json.load(sys.stdin)['appId'])")
APP_OBJECT_ID=$(echo "$APP_JSON" | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "$APP_ID" > .secrets/entra_app_id.txt

SWA_HOST=$(az deployment group show -g dhara-platform-rg -n main --query properties.outputs.staticWebAppDefaultHostname.value -o tsv)

az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/$APP_OBJECT_ID" \
  --headers "Content-Type=application/json" \
  --body "{\"spa\": {\"redirectUris\": [\"http://localhost:5173\", \"https://$SWA_HOST\"]}, \"identifierUris\": [\"api://$APP_ID\"]}"

SCOPE_ID=$(python -c "import uuid; print(uuid.uuid4())")
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/$APP_OBJECT_ID" \
  --headers "Content-Type=application/json" \
  --body "{\"api\": {\"oauth2PermissionScopes\": [{\"id\": \"$SCOPE_ID\", \"adminConsentDescription\": \"Allows the operator console to access DHARA cluster data.\", \"adminConsentDisplayName\": \"Access DHARA as operator\", \"userConsentDescription\": \"Allow the app to access DHARA cluster data on your behalf.\", \"userConsentDisplayName\": \"Access DHARA as operator\", \"value\": \"access_as_operator\", \"type\": \"User\", \"isEnabled\": true}]}}"

az ad sp create --id $APP_ID
```
Re-run `bash scripts/export-env.sh` afterwards. See `docs/azure-requirements.md` §8
for the admin-consent caveat in a managed tenant.

## 11. Seed demo farms and start the edge simulator

Run this via Docker, not local `pip install` -- see the Prerequisites note on `uamqp`:
```bash
docker build -f services/edge-simulator/Dockerfile -t dhara-edge-simulator:local .

docker run --rm --env-file .env \
  -v "//$(pwd -W 2>/dev/null || pwd)/services/edge-simulator:/app/services/edge-simulator" \
  dhara-edge-simulator:local \
  python provision_devices.py --farms 20 --cluster-name "Niphad Demo Cluster" \
    --district Nashik --state Maharashtra --lat 20.0859 --lon 73.9862

docker run -d --name dhara-edge-simulator --env-file .env -e SIMULATOR_TICK_SECONDS=60 \
  -v "//$(pwd -W 2>/dev/null || pwd)/services/edge-simulator:/app/services/edge-simulator" \
  dhara-edge-simulator:local python simulator.py
```
**On Windows Git Bash specifically:** prefix any Docker command whose arguments
contain a path starting with `/` (a bind mount, or a resource ID passed to `az`)
with `MSYS_NO_PATHCONV=1`, or use the double-leading-slash form shown above --
otherwise Git Bash's automatic POSIX-to-Windows path conversion mangles it and the
mount silently fails or points somewhere unexpected. This bit us twice during
setup (a mount that silently used an empty directory, and an `az resource show`
call that mangled its own resource ID into a `C:\Program Files\Git\...` path).

## 12. Deploy the operator console

```bash
bash scripts/deploy_operator_console.sh
```

## 13. Verify end-to-end

```bash
curl https://<api-fqdn>/healthz
curl https://<advisory-bot-fqdn>/healthz
curl https://<api-fqdn>/telemetry?limit=5      # should show real readings within ~1 minute
curl https://<api-fqdn>/control/decisions?limit=5   # populates on decision-engine's next 15-min tick, or trigger it manually (below)
```
To force an immediate decision-engine run instead of waiting for its timer:
```bash
MASTER_KEY=$(az functionapp keys list -g dhara-platform-rg -n "$DECISION_NAME" --query masterKey -o tsv)
curl -X POST "https://$DECISION_NAME.azurewebsites.net/admin/functions/IrrigationControlLoop" \
  -H "x-functions-key: $MASTER_KEY" -H "Content-Type: application/json" -d '{"input": ""}'
```

---

## War story: why ingestion is a Container App, not a Function App

The original design (and this repo's first cut) used an Azure Functions Event Hub
trigger for ingestion, the textbook approach for "consume IoT Hub telemetry." It
never fired a single execution, across:

1. Legacy Y1 Consumption, first deployment
2. The same Y1 Consumption app, deleted and recreated fresh (in case of corrupted state)
3. Flex Consumption (`az functionapp flex-migration start`), default consumer group
4. Flex Consumption again, with a dedicated consumer group and an explicit
   always-ready instance (`az functionapp scale config always-ready set`)

Every configuration showed a healthy host, a correctly indexed function, and a
listener that successfully claimed all 4 Event Hub partitions -- but zero
executions, for over an hour of continuous message traffic. Microsoft Q&A searches
turned up a documented, reproducible "0 running workers indefinitely" pattern for
brand-new Linux Consumption apps, which pointed the investigation at the hosting
plan. It wasn't the hosting plan.

**The actual fault:** `az iot hub show`'s routing config revealed
`"fallbackRoute": {"isEnabled": false}` with `"routes": []`. Declaring a custom
`eventHubEndpoints` block on the IoT Hub resource in Bicep -- done to set
`partitionCount` -- left the hub without its default fallback route enabled.
Device messages were being accepted (ingress metrics looked completely healthy,
`az iot hub monitor-events` connected fine) but routed nowhere: no Function
trigger, no direct SDK consumer, not even Microsoft's own CLI monitoring tool ever
saw a message, because there was genuinely nothing to route to the built-in Event
Hub-compatible endpoint. Every symptom pointed at the consumer side; the fault was
upstream of all of them.

The fix is one line, now explicit in `infra/main.bicep`:
```bicep
routing: {
  fallbackRoute: {
    name: '$fallback'
    source: 'DeviceMessages'
    condition: 'true'
    endpointNames: ['events']
    isEnabled: true
  }
}
```

By the time this was found, ingestion had already been rebuilt as
`services/ingestion/consumer.py` -- a plain Python loop against the
`azure-eventhub` SDK, run as a Container App. It needs no Functions-specific
scale-controller behaviour to reason about, and it kept the useful side discovery
that a Function App's Event Hub trigger and a separate SDK consumer contend for
the same consumer group's epoch-based lock if both are pointed at it (hence the
dedicated `ingestion-consumer` consumer group `infra/main.bicep` now creates).
`decision-engine`'s timer triggers were never affected by any of this -- they ran
correctly on both Consumption and Flex throughout -- so it stayed a Function App.

## Local development

```bash
docker compose up --build
```
Brings up Postgres + `api` + `advisory-bot` + `decision-engine` (as a plain-Python
loop, not the Functions runtime) locally, all still calling real Azure services
(OpenAI, Speech, ACS, IoT Hub) per `.env`. `ingestion` isn't in docker-compose --
run it the same way as production, pointed at the real IoT Hub:
```bash
docker build -f services/ingestion/Dockerfile -t dhara-ingestion:local .
docker run --rm --env-file .env dhara-ingestion:local
```

For the operator console:
```bash
cd apps/operator-console
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env
npm run dev
```
