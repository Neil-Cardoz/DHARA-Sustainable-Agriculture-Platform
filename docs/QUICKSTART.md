# Quickstart

You've run through `docs/SETUP.md` once (or someone gave you a running deployment
plus the `.env` it produced). This is "how do I see it working in five minutes."

## 1. Is everything up?

```bash
curl https://<api-fqdn>/healthz        # {"status":"ok","environment":"production"}
curl https://<advisory-bot-fqdn>/healthz
```

## 2. Seed a demo cluster (if no plots exist yet)

Run via Docker, not local `pip install` — `azure-iot-device`'s `uamqp` dependency
has no prebuilt wheel for newer local Python versions:
```bash
docker build -f services/edge-simulator/Dockerfile -t dhara-edge-simulator:local .

docker run --rm --env-file .env \
  -v "//$(pwd -W 2>/dev/null || pwd)/services/edge-simulator:/app/services/edge-simulator" \
  dhara-edge-simulator:local \
  python provision_devices.py --farms 20 --cluster-name "Niphad Demo Cluster" \
    --district Nashik --state Maharashtra --lat 20.0859 --lon 73.9862
```
This creates one FPO cluster, 20 farmer plots (random 0.8-1.6 ha, tomato/onion/
chickpea), one edge-controller device per plot, and one village gateway — both in
the DHARA database (via the API) and as real device identities in Azure IoT Hub.
It writes `services/edge-simulator/devices.json` (on your host, via the volume
mount) with each device's connection string.

## 3. Start the simulator

```bash
docker run -d --name dhara-edge-simulator --env-file .env -e SIMULATOR_TICK_SECONDS=60 \
  -v "//$(pwd -W 2>/dev/null || pwd)/services/edge-simulator:/app/services/edge-simulator" \
  dhara-edge-simulator:local python simulator.py
```
Leave it running (`docker logs -f dhara-edge-simulator` to watch). Each simulated farm box:
- publishes a real 16-byte packed telemetry frame to IoT Hub once per tick
  (`SIMULATOR_TICK_SECONDS`, default 60s = one "simulated" 15-minute cycle, sped up
  for demo purposes; set it to 900 for real-time pacing)
- depletes soil moisture over time (a simplified ET draw-down)
- listens for the cloud's irrigation command and replenishes moisture + increments
  its flow counter when told to irrigate

Within ~1-2 minutes you should see log lines like:
```
INFO:root:device dhara-edge-0007 connected
INFO:root:dhara-edge-0003 irrigated 850.0 L
```

## 4. Watch the decision engine work

The decision engine (an Azure Function on Flex Consumption, e.g. `dhara-decision-flex`)
runs automatically every 15 minutes. To see it react faster during a demo, trigger
it manually via its admin API (Flex Consumption/Linux apps don't support
`az functionapp function invoke` or `az functionapp log tail`):
```bash
DECISION_NAME=dhara-decision-flex   # or your deployment's actual name
MASTER_KEY=$(az functionapp keys list -g dhara-platform-rg -n "$DECISION_NAME" --query masterKey -o tsv)
curl -X POST "https://$DECISION_NAME.azurewebsites.net/admin/functions/IrrigationControlLoop" \
  -H "x-functions-key: $MASTER_KEY" -H "Content-Type: application/json" -d '{"input": ""}'
```
Then check for a result:
```bash
curl https://<api-fqdn>/control/decisions?limit=5
```
To watch its own logs, query Application Insights instead of the CLI's log
streaming (unsupported on this hosting plan):
```bash
az monitor app-insights query -g dhara-platform-rg -a <decision-func-name> \
  --analytics-query "AppTraces | where TimeGenerated > ago(15m) | order by TimeGenerated desc | take 30"
```
(Flex Consumption Function Apps get their own dedicated Application Insights
resource, separate from the platform's main `dhara-appi-<suffix>` — check
`az monitor app-insights component show -g dhara-platform-rg` if you're not sure
which one to query.)

## 5. Open the operator console

```
https://<static-web-app-hostname>
```
You should see:
- **Dashboard** — the Niphad Demo Cluster, device counts, cold-room utilisation
- **Plots** — all 20 demo farms; click one to see its devices, latest decision, and
  irrigation events (initially "pending" until the verify step closes the window)
- **Energy** — arbitration log once `EnergyArbitration` has run at least once
- **Advisory Log** — empty until a WhatsApp/voice interaction happens (see below)
- **Savings Ledger** — empty until the weekly `CloseLedgerPeriod` job runs (Mondays
  03:00, or invoke it manually the same way as step 4)

## 6. Try the advisory bot without a real WhatsApp number

Meta Business verification (needed for real WhatsApp) takes 1-3 weeks — see
`docs/azure-requirements.md` §5. In the meantime, exercise the same code path
directly:
```bash
curl -X POST https://<advisory-bot-fqdn>/webhooks/eventgrid \
  -H "Content-Type: application/json" \
  -d '[{
    "eventType": "Microsoft.Communication.AdvancedMessageReceived",
    "data": {
      "from": "+919000000001",
      "content": "My tomato leaves are curling, what should I do?",
      "contentType": "text"
    }
  }]'
```
Then check the Advisory Log page in the console -- you should see the question, the
model's answer (or an escalation, if confidence was low), in under a few seconds.

## 7. Trigger an outbound voice advisory manually

```bash
PLOT_ID=$(curl -s https://<api-fqdn>/plots | python -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
curl -X POST "https://<advisory-bot-fqdn>/outbound/voice-advisory?plot_id=$PLOT_ID"
```
This requires a real ACS phone number to actually ring anything (see
`docs/azure-requirements.md` §5, step 1) — without one it will fail at the
`create_call` step, which is expected until that's provisioned.

## What "done" looks like for a real pilot

Per the architecture's own Phase 0 gate: before claiming any savings number, you need
a full season of **paired control-plot metering** — this simulator is for exercising
the software, not for generating a real savings claim. See
`docs/ARCHITECTURE.md` and the source PDF's "Deployment and scale-up" section for the
four-phase rollout (Instrument → Prove → Contract → Scale).
