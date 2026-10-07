# Azure Requirements & Secrets Guide

This document explains **every credential DHARA needs, exactly where it comes from in
Azure, and how to rotate or regenerate it.** It exists so that a year from now, when a
key expires or you deploy to a second cluster, you don't have to reverse-engineer the
`.env` file.

If you deployed with `scripts/export-env.sh` (see `docs/SETUP.md`), all of this was
already pulled out of Azure into `.env` for you automatically. This document is the
reference for when you need to do it by hand: rotating a key, moving to a new
subscription, or setting up a second environment (staging, another cluster, etc.).

> **Never commit `.env`.** It contains live credentials. `.gitignore` already excludes
> it. The only file safe to commit is `.env.example` (placeholders only).

---

## 0. What actually holds the secrets in production

`.env` is for **local development and for the one-time bootstrap of Container
Apps/Function Apps secrets during deployment.** In the deployed platform, the real
source of truth is:

- **Azure Key Vault** (`dhara-kv-xxxxxxxx`) — every secret Bicep creates is also
  written here. Use `az keyvault secret show` to read one; use Key Vault references
  (`@Microsoft.KeyVault(...)`) in Container App / Function App settings for anything
  you rotate after first deploy, instead of editing `.env` and redeploying.
- **Container App secrets** (`api-shared-secret`, `acs-connection-string`, etc.) —
  set at deploy time by `infra/main.bicep`. Rotate with
  `az containerapp secret set --name <app> --resource-group dhara-platform-rg --secrets <name>=<value>`.
- **Function App settings** — same idea, via `az functionapp config appsettings set`.

---

## 1. Resource Group & Subscription

| Item | Value for this deployment |
|---|---|
| Subscription | Azure for Students (`588d02dc-...`) |
| Resource group | `dhara-platform-rg` |
| Primary region | `centralindia` |
| Allowed regions (subscription policy) | `centralindia`, `southeastasia`, `koreacentral`, `eastasia`, `malaysiawest` |

**Why the region split:** this specific subscription has an `Allowed resource
deployment regions` policy. Most resources live in `centralindia` (closest to the
farmer base). Azure OpenAI's `GlobalStandard` SKU for the model we use was only
available (at deployment time) in `koreacentral` among the allowed regions, and Azure
Static Web Apps only in `eastasia`. If you deploy into a subscription **without** this
restriction, you can collapse everything to one region by changing `openAiLocation`
and `staticWebAppLocation` in `infra/main.bicep`.

Check your own subscription's restriction (if any) before you deploy:
```bash
az policy assignment list --query "[?displayName=='Allowed resource deployment regions']"
```
If nothing comes back, you have no such restriction — pick regions freely.

---

## 2. Database — Azure Database for PostgreSQL Flexible Server

- **Resource:** `dhara-pg-<suffix>` (Burstable `Standard_B1ms`)
- **Secret:** `DATABASE_URL` — includes the admin password.
- **Where the password comes from:** generated once by you before first deploy
  (`.secrets/postgres_admin_password.txt`, see `docs/SETUP.md`), passed to Bicep as
  the `postgresAdminPassword` secure parameter. Azure never generates this for you.
- **To rotate:**
  ```bash
  az postgres flexible-server update -g dhara-platform-rg -n <server-name> -p "<new-password>"
  ```
  then update `.env` and the `api`/`advisory-bot` Container App secrets.
- **Firewall:** `AllowAzureServices` (0.0.0.0-0.0.0.0, the documented Azure
  convention for "allow Azure-internal traffic") is the only rule. If you need to run
  `psql` from your laptop, add your IP:
  ```bash
  az postgres flexible-server firewall-rule create -g dhara-platform-rg -n <server-name> \
    --rule-name my-ip --start-ip-address <your-ip> --end-ip-address <your-ip>
  ```

---

## 3. Azure IoT Hub — device identity and telemetry ingress

- **Resource:** `dhara-iothub-<suffix>` (S1 Standard, capacity 1)
- **Secrets:**
  - `IOT_HUB_CONNECTION_STRING` — the `iothubowner` policy connection string. Full
    rights: registry read/write, service (C2D messages), device connect.
    ```bash
    az iot hub connection-string show -n <hub-name> --policy-name iothubowner
    ```
  - `IOT_HUB_EVENTHUB_COMPATIBLE_ENDPOINT` — the **built-in Event Hub-compatible
    endpoint**, a different thing from the connection string above. This is what the
    `ingestion` Container App's `azure-eventhub` client actually connects to
    (device telemetry lands here, not in the main service endpoint).
    ```bash
    az iot hub show -n <hub-name> --query properties.eventHubEndpoints.events.endpoint -o tsv
    az iot hub show -n <hub-name> --query properties.eventHubEndpoints.events.path -o tsv
    az iot hub policy show --hub-name <hub-name> --name iothubowner --query primaryKey -o tsv
    ```
    Assemble as: `Endpoint=<endpoint>;SharedAccessKeyName=iothubowner;SharedAccessKey=<key>;EntityPath=<path>`
- **`IOT_HUB_EVENTHUB_CONSUMER_GROUP`** — `ingestion-consumer`, a dedicated
  consumer group `infra/main.bicep` creates (not `$Default`). Event Hub-compatible
  consumer groups use epoch-based locking: a second reader on the same consumer
  group (another instance of `ingestion`, a leftover `az iot hub monitor-events`
  session, or anything else) will fight it for the lock and neither will receive
  reliably. Give any new consumer its own consumer group:
  ```bash
  az iot hub consumer-group create --hub-name <hub-name> --name <new-name>
  ```
- ⚠️ **The fallback route must be enabled, or nothing reaches the endpoint above at
  all.** `infra/main.bicep` sets this explicitly now, but if you ever hand-edit the
  IoT Hub's `eventHubEndpoints` (e.g. changing `partitionCount`), verify routing
  didn't get reset:
  ```bash
  az iot hub show -n <hub-name> --query "properties.routing.fallbackRoute"
  # isEnabled must be true. If false:
  az iot hub update -n <hub-name> --set properties.routing.fallbackRoute.isEnabled=true
  ```
  When this is disabled, device messages are still accepted by the hub (ingress
  metrics look completely healthy, devices get their PUBACK) but are routed
  nowhere — no consumer of any kind, Functions trigger or plain SDK client, will
  ever see them, and there is no error anywhere to point at the cause. This cost
  real debugging time in this deployment; see `docs/SETUP.md`'s war story for the
  full trail if you hit the same symptom.
- **Per-device credentials** (one per simulated or real edge box) are generated by
  `services/edge-simulator/provision_devices.py`, which calls
  `IoTHubRegistryManager.create_device_with_sas()` for you. You do not hand-create
  these. Real hardware in the field gets provisioned the same way at commissioning
  time (or via DPS if you move to zero-touch provisioning at scale — see §11).
- **Rotate the service key** (`iothubowner`):
  ```bash
  az iot hub policy renew-key --hub-name <hub-name> --name iothubowner --renew-key Primary
  ```

---

## 4. Azure Storage — advisory photos, firmware, Function App state

- **Resource:** `dhara<suffix>` storage account (Standard_LRS)
- **Secret:** `STORAGE_ACCOUNT_CONNECTION_STRING`
  ```bash
  az storage account show-connection-string -n <storage-name> -g dhara-platform-rg
  ```
- **Containers created by Bicep:** `advisory-photos` (leaf/pest photos sent over
  WhatsApp), `firmware` (OTA images for the edge controller).
- This same account also backs the `ingestion` and `decision-engine` Function Apps
  (`AzureWebJobsStorage` app setting) — do not delete it thinking it's unused.

---

## 5. Azure Communication Services — WhatsApp + voice

- **Resource:** `dhara-acs-<suffix>` (data location: India)
- **Secret:** `ACS_CONNECTION_STRING`
  ```bash
  az communication list-key -n <acs-name> -g dhara-platform-rg --query primaryConnectionString -o tsv
  ```
- **What Bicep does NOT and cannot automate** (Meta/telecom-side steps, portal-only):
  1. **Buy a phone number** for voice calls: Azure Portal → your Communication
     Services resource → *Phone numbers* → *Get*. For India, outbound-only toll-free
     or local numbers require submitting business documentation for regulatory
     approval (typically 1-5 business days). Put the number in
     `ACS_SENDER_PHONE_NUMBER`.
  2. **Set up WhatsApp Business (Advanced Messaging)**: Azure Portal → your
     Communication Services resource → *Advanced Messaging* → *WhatsApp* → connect a
     WhatsApp Business Account you (or your FPO/NGO partner) register with Meta at
     [business.facebook.com](https://business.facebook.com). This requires a Meta
     Business verification (identity documents, a real business, a website) —
     **budget 1-3 weeks** and treat it as a Phase 0/1 workstream, not a blocker to
     everything else. Once connected, copy the *Channel Registration ID* into
     `ACS_WHATSAPP_CHANNEL_REGISTRATION_ID`.
  3. **Wire the Event Grid subscription**: Portal → your Communication Services
     resource → *Events* → *+ Event Subscription* → Event type
     `Advanced Message Received` (and, on your ACS/telephony resource,
     `Incoming Call`) → Endpoint type *Web Hook* → URL:
     `https://<advisory-bot-fqdn>/webhooks/eventgrid`. Azure will call this URL once
     immediately to validate it (the handler in `services/advisory-bot/app/main.py`
     already answers that handshake).
- **Until steps 1-3 are done:** the advisory-bot's WhatsApp/voice code paths are
  fully implemented and will run the moment real events arrive, but nothing will
  reach them. Test in the meantime by POSTing synthetic Event Grid payloads at
  `/webhooks/eventgrid`, or use the operator console's dashboards, which need none
  of this.

---

## 6. Azure OpenAI (advisory NLU)

- **Resource:** `dhara-openai-<suffix>`, kind `AIServices`, region `koreacentral`
  (see §1 for why). Deployment name: `dhara-advisory-gpt`, model `gpt-4.1-mini`.
- **Secrets:** `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`
  ```bash
  az cognitiveservices account show -n <openai-name> -g dhara-platform-rg --query properties.endpoint -o tsv
  az cognitiveservices account keys list -n <openai-name> -g dhara-platform-rg --query key1 -o tsv
  ```
- **If your subscription has no Azure OpenAI access at all:** redeploy with
  `deployOpenAi=false` and leave `AZURE_OPENAI_*` blank — the advisory-bot's
  `nlu.get_advisory_response()` catches the failure and returns confidence `0.0`,
  which the confidence gate (§ARCHITECTURE.md) routes straight to a human agronomist.
  The platform degrades gracefully; it does not crash.
- **Why `gpt-4.1-mini` and not `gpt-4o-mini`:** at deployment time, `gpt-4o-mini`'s
  `GlobalStandard` SKU had entered "deprecating" status in `koreacentral` and Azure
  rejected new deployments of it. Check current model availability before you deploy
  a second time — Azure's model catalog changes over months, not years:
  ```bash
  az rest --method get --url "https://management.azure.com/subscriptions/<sub-id>/providers/Microsoft.CognitiveServices/locations/<region>/models?api-version=2023-05-01"
  ```
- **Quota note:** each subscription gets a small number of "OpenAI"-kind Cognitive
  Services accounts per region (often just 1). This deployment deliberately uses the
  newer unified **"AIServices"** kind instead, which has much higher account quota
  and hosts the same OpenAI model deployments.

---

## 7. Azure AI Speech (voice IVR)

- **Resource:** `dhara-speech-<suffix>` (S0 Standard), region `centralindia`.
- **Secrets:** `SPEECH_KEY`, `SPEECH_REGION`
  ```bash
  az cognitiveservices account keys list -n <speech-name> -g dhara-platform-rg --query key1 -o tsv
  ```
- In the current build, outbound-call text-to-speech is generated inline by Azure
  Communication Services' Call Automation `TextSource` (it calls Cognitive Services
  Speech internally, given a voice name) — see `services/advisory-bot/app/voice.py`.
  The standalone Speech resource is provisioned for future use (e.g., transcribing
  inbound WhatsApp voice notes with the Speech SDK directly) and is the one to use if
  you outgrow Call Automation's built-in TTS.

---

## 8. Microsoft Entra ID — operator console sign-in

- **App registration:** "DHARA Operator Console" — created via `az ad app create`
  (see `docs/SETUP.md` for the exact commands used). Values needed:
  - `ENTRA_TENANT_ID` — `az account show --query tenantId -o tsv`
  - `ENTRA_API_CLIENT_ID` — the app's `appId`
    ```bash
    az ad app list --display-name "DHARA Operator Console" --query "[0].appId" -o tsv
    ```
- **Exposed API scope:** `api://<appId>/access_as_operator`
- **Known limitation, please read:** creating this app registration does **not**
  require tenant-admin rights, but *granting tenant-wide admin consent* does — and in
  a university/organisation tenant you are unlikely to be a Global Admin. Two ways
  forward:
  1. **Per-user consent (default, needs no admin):** the first time each operator
     signs in, Entra ID shows a normal OAuth consent screen for the
     `access_as_operator` scope. They approve once; that's it. This works out of the
     box unless your tenant has disabled user consent entirely.
  2. **Admin consent (optional, faster rollout):** if you *are* an admin, or can ask
     one, grant consent once for everyone:
     Portal → Entra ID → App registrations → DHARA Operator Console → API
     permissions → *Grant admin consent for `<tenant>`*.
- **Current wiring status:** the app registration and API scope exist and are
  production-ready to use. The React operator console (`apps/operator-console`) does
  **not yet call MSAL to sign in** — it currently talks to the API's read-only `GET`
  endpoints directly, which are intentionally left open for the pilot (see
  `docs/ARCHITECTURE.md`, "Known hardening items"). Wiring `@azure/msal-react` into
  `apps/operator-console` and enforcing `validate_entra_token()` (already implemented
  in `packages/dhara_shared/dhara_shared/auth.py`) on every route is the top item on
  that list before you put real farmer data behind this console on the open
  internet.

---

## 9. Application Insights / Log Analytics

- **Resource:** `dhara-appi-<suffix>` / `dhara-log-<suffix>`
- **Secret:** `APPLICATIONINSIGHTS_CONNECTION_STRING`
  ```bash
  az monitor app-insights component show -g dhara-platform-rg -a <appi-name> --query connectionString -o tsv
  ```
- No manual setup needed beyond this — every service already reads it from `.env` /
  its Container App or Function App settings and reports traces/logs/metrics
  automatically.

---

## 10. Container Registry & images

- **Resource:** `dhara-acr-<suffix>` (Basic, admin user enabled for simplicity).
- **Credentials:** used only by Container Apps to pull images; not something your
  services need at runtime. Three images are built from this repo -- `dhara-api`,
  `dhara-advisory-bot`, `dhara-ingestion` -- each the same pattern to update:
  ```bash
  az acr login --name <acr-name>
  docker build -f services/api/Dockerfile -t <acr-name>.azurecr.io/dhara-api:v2 .
  docker push <acr-name>.azurecr.io/dhara-api:v2
  az containerapp update -n dhara-api -g dhara-platform-rg --image <acr-name>.azurecr.io/dhara-api:v2
  ```
- **Note on this subscription specifically:** `az acr build` (cloud build via ACR
  Tasks) is disallowed on Azure for Students
  (`TasksOperationsNotAllowed`). Build locally with Docker Desktop and `docker push`
  instead, as above.

---

## 11. Scaling beyond the pilot

None of the above needs to change architecturally to go from 1 cluster (100 farms) to
1,000 clusters (150,000 farms, per the architecture's Phase 3) — only SKUs do:

| Resource | Pilot SKU | Scale-up path |
|---|---|---|
| PostgreSQL | Burstable B1ms | Scale to General Purpose D-series, or shard by cluster |
| IoT Hub | S1, 1 unit (400k msgs/day) | Add units, or move to S2/S3 |
| Container Apps | 0-3 replicas, 0.5 vCPU | Raise `maxReplicas`, add vCPU/memory |
| OpenAI | GlobalStandard, capacity 10 | Raise deployment capacity; consider Provisioned Throughput for guaranteed latency at high volume |
| Static Web App | Free tier | Standard tier for custom domain + higher SLA |

Everything is stateless except Postgres, so horizontal scaling of the API/advisory-bot
Container Apps is a one-line `az containerapp update --max-replicas` away.
