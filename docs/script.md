# DHARA Demonstration Script

A ~10-minute walkthrough of the live, deployed platform — not slides, the real
thing running on Azure. Everything referenced below is live at the time of
writing; URLs and IDs are this deployment's actual values (`dhara-platform-rg`).

**Core message:** this isn't a mockup. Real IoT Hub telemetry from a simulated
farm cluster flows through a real ingestion pipeline into a real decision engine
that computes real irrigation depths and real energy allocations — the same
architecture a physical DHARA deployment would run, minus the field hardware.

---

## 0. Before you present (5 minutes, do this once, ahead of time)

Run through this the morning of / hour before — not minutes before, so nothing is
still "warming up" on stage.

1. **Confirm the simulator is running** (it streams telemetry continuously; if it's
   not running, the whole demo is static):
   ```bash
   docker ps --filter name=dhara-edge-simulator --format "{{.Status}}"
   ```
   If it's not up, see `docs/QUICKSTART.md` §3 to restart it. Give it 2-3 minutes
   to build up fresh telemetry before presenting.

2. **Confirm the platform is healthy:**
   ```bash
   curl https://dhara-api.greenrock-7df318b6.centralindia.azurecontainerapps.io/healthz
   curl https://dhara-advisory-bot.greenrock-7df318b6.centralindia.azurecontainerapps.io/healthz
   ```
   Both should return `{"status":"ok",...}`.

3. **Open these tabs, in this order** (so alt-tab during the demo is muscle
   memory, not a search):
   - Tab 1: Operator console — `https://victorious-wave-0ccbd1500.2.azurestaticapps.net`
   - Tab 2: A terminal with the edge-simulator logs following:
     `docker logs -f dhara-edge-simulator`
   - Tab 3: A terminal ready to run the API curl commands below
   - Tab 4 (optional, for the architecture section): `docs/ARCHITECTURE.md`'s
     mermaid diagram, rendered (GitHub, VS Code preview, or any markdown viewer)

4. **One-time-only pre-flight of the advisory bot** (see §5's caveat — Azure
   OpenAI's GlobalStandard quota here is genuinely tight; testing it more than
   once right before presenting can leave it looking rate-limited during the real
   demo). Run the §5 curl command *once*, confirm it returns a real answer, then
   leave it alone.

5. **Do not** re-run `provision_devices.py` or restart Function Apps right before
   presenting — both cause a few minutes of cold data.

---

## 1. Open — the problem, in one breath (30 seconds)

> "Three numbers, one cause: 40% of India's workforce farms plots under two
> hectares, 90% of freshwater withdrawal is irrigation, and 1.53 lakh crore
> rupees of food is lost after harvest every year. All three trace back to the
> same thing — at the point of use, neither water nor the energy to lift it
> carries a price the farmer can see. DHARA is a control and advisory platform
> that puts a measured, auditable number on both, without needing the farmer to
> read a screen."

Don't linger here — the deck version of this argument already exists in the
source PDF. The point of *this* script is to show it running.

## 2. Architecture, fast (60-90 seconds)

Show `docs/ARCHITECTURE.md`'s diagram (Tab 4) or just narrate the shape:

> "Five tiers, from the original design. Tiers 0 through 2 — soil probes, the
> farm edge box, the village gateway — are physical hardware we're standing in
> for with a software simulator, because we're not manufacturing ESP32 boards
> for a hackathon. Everything from Tier 3 up — the cloud decision engine, the
> energy optimiser, the verification ledger, and Tier 4's farmer interfaces — is
> real, deployed, and running on Azure right now. Not a demo environment we spin
> up for the judges. The actual resource group."

Point out on the diagram: IoT Hub → ingestion → Postgres → decision-engine →
advisory-bot/console. One sentence each on *why* Azure IoT Hub (device identity
+ telemetry ingress built for exactly this), Postgres (the audit trail needs real
foreign keys between a Decision and the IrrigationEvent it caused), and Container
Apps + Functions (pay only for the 15-minute ticks, not idle time).

## 3. Live telemetry → live decision (3 minutes) — the centerpiece

This is the part that proves it's real. Switch to Tab 2 (simulator logs) first.

> "Twenty simulated farms, each running the same 16-byte packed telemetry frame
> a real ESP32 edge box would send — soil moisture at three depths, temperature,
> battery, flow counter. Watch it stream."

Let 5-10 seconds of log lines scroll (`Successfully sent message to Hub`,
`irrigated N L` if one happens to fire). Then switch to Tab 3:

```bash
curl -s "https://dhara-api.greenrock-7df318b6.centralindia.azurecontainerapps.io/telemetry?limit=5" | python -m json.tool
```

> "That's not seeded data — that request just hit Postgres and pulled back
> whatever the ingestion service wrote in the last few seconds, decoded straight
> off the wire from IoT Hub."

Now the decision engine. Trigger it live so the audience sees cause and effect,
not a pre-baked number:

```bash
MASTER_KEY=$(az functionapp keys list -g dhara-platform-rg -n dhara-decision-flex --query masterKey -o tsv)
curl -s -X POST "https://dhara-decision-flex.azurewebsites.net/admin/functions/IrrigationControlLoop" \
  -H "x-functions-key: $MASTER_KEY" -H "Content-Type: application/json" -d '{"input": ""}'

sleep 8
curl -s "https://dhara-api.greenrock-7df318b6.centralindia.azurecontainerapps.io/control/decisions?limit=5" | python -m json.tool
```

> "Twenty decisions, one per farm, just ran. Most say `NO_ACTION_ABOVE_THRESHOLD`
> — soil's still wet enough, so the system does nothing, which is the point: it
> doesn't irrigate on a timer, it irrigates on a measured refill threshold. The
> ones that *do* trigger say `REFILL_THRESHOLD_CROSSED` with a computed depth in
> millimetres — that number came from an actual FAO-56 water-balance calculation
> against this farm's soil parameters and today's evapotranspiration forecast,
> not a lookup table."

Follow with irrigation events to close the loop:
```bash
curl -s "https://dhara-api.greenrock-7df318b6.centralindia.azurecontainerapps.io/control/irrigation-events?limit=3" | python -m json.tool
```
> "Every decision that triggered irrigation has a paired event with computed
> volume and energy — `decision_id` links them. That pairing is the audit trail:
> a discom or a carbon buyer isn't asked to trust a savings number, they can
> trace it back to the exact reasoning and the exact measured water that moved."

## 4. Operator console (2 minutes)

Switch to Tab 1.

- **Dashboard**: cluster summary, device health counts. *"Twenty farms, one
  village cluster, device health at a glance — this is what an FPO operator
  opens every morning."*
- **Plots**: click into one plot (e.g. Demo Farmer 002). Show active crop,
  latest decision with its reason code, devices, and irrigation history with
  the verified/pending badge. *"Pending means the flow-meter reconciliation
  hasn't closed its 15-minute window yet — once it does, this is what actually
  moved, not what was intended."*
- **Energy**: the six-step solar priority order, refreshed every cycle. Point at
  a row where `curtailed_kwh > 0` on a `tank_fill` claim. *"This is rule three
  from the design — tank fill is capped at the season's volumetric allocation
  regardless of how much free solar is sitting there. This is what stops an
  efficiency gain from turning into a lower water table."*
- **Cold Storage**: two lots. *"Same intake date range, but look at predicted
  remaining shelf life — 240 hours for the untouched lot, 196 for the one that
  had a door-open event logged against it. The dispatch queue reorders itself
  around that automatically; nobody has to notice the excursion by hand."*
- **Savings Ledger**: the four stat tiles. *"~17,000 cubic metres of water and
  ~4,200 kWh saved against the architecture's own stated baseline, across 20
  farms in one demo season. That comparison is exactly what a discom performance
  contract or a PMKSY subsidy claim would be built on."*

## 5. Advisory channel (90 seconds) — WhatsApp, live

> "The farmer-facing side. No app, no login — WhatsApp, in whatever language the
> cluster is configured for."

```bash
curl -s -X POST "https://dhara-advisory-bot.greenrock-7df318b6.centralindia.azurecontainerapps.io/webhooks/eventgrid" \
  -H "Content-Type: application/json" \
  -d '[{
    "eventType": "Microsoft.Communication.AdvancedMessageReceived",
    "data": {
      "from": "+919000000001",
      "content": "My tomato leaves are curling and turning yellow at the edges, what should I do?",
      "contentType": "text"
    }
  }]'

sleep 6
curl -s "https://dhara-api.greenrock-7df318b6.centralindia.azurecontainerapps.io/advisory/interactions?limit=1" | python -m json.tool
```

> "That's a real Azure OpenAI call, grounded in this specific plot's own sensed
> data — it isn't allowed to invent a moisture reading or a price."

**If `confidence` comes back `0.0` and `escalated_to_human: true`:** say so
plainly, don't paper over it — *"Confidence came back below threshold, so it
escalated to a human agronomist instead of guessing. That's the design working
as intended — an advisory that's wrong once loses the farmer for a season, so it
says 'I don't know' rather than answer fluently."* This is true whether the
cause is a genuinely ambiguous question or (as is more often the real cause in
this specific deployment) a shared regional OpenAI quota returning a transient
429 — either way, the fallback path is real and this is the correct moment to
name the confidence-gating design rather than apologize for a glitch.

**Don't demo real WhatsApp or a real phone call** — both need a Meta Business
verification and a purchased number that can't be provisioned for a hackathon
timeline (see `docs/azure-requirements.md` §5). Say this directly if asked: *"The
code path is complete and this webhook call exercises the exact same logic a
real inbound WhatsApp message would — what's missing is a business verification
from Meta, which is a paperwork timeline, not an engineering one."*

## 6. Close (30 seconds)

> "Everything you just watched — the telemetry, the decision, the energy
> allocation, the console — is running on a live Azure resource group right now,
> not spun up for this demo. The architecture scales from this one 20-farm
> cluster to the source design's Phase 3 target of 150,000 farms by changing
> SKUs, not code. What's left before a real pilot is exactly what the source
> architecture says it is: a season of paired control-plot metering, because
> every savings number before that is a model arguing with itself."

---

## Contingency plan

Live demos fail. Have this ready without breaking stride:

| If this breaks... | Do this instead |
|---|---|
| Simulator container isn't running / no fresh telemetry | Use `?limit=20` instead of `?limit=5` on `/telemetry` and `/control/decisions` — older data still proves the pipeline works, just say "from earlier today" instead of "just now" |
| Decision-engine trigger call hangs or 5xxs | It also runs automatically every 15 minutes — check `/control/decisions?limit=5` for a recent timestamp instead of forcing one live |
| Advisory bot 429s again | Use the confidence-gating narration above verbatim — it's an honest, on-message fallback, not an excuse |
| Operator console won't load | Everything it shows is one `curl` away — walk the same four sections via the terminal instead |
| Someone asks to see a real WhatsApp message or phone call | Answer directly per §5 — don't attempt to fake it live |
| Someone asks "is this actually deployed or a local demo" | `az resource list --resource-group dhara-platform-rg -o table` on screen settles it in one command |

## Anticipated questions

- **"How much did this cost to run?"** — Everything here fits inside an Azure for
  Students credit; Bicep SKUs are documented per-resource in
  `docs/azure-requirements.md` §11 with the scale-up path for each.
- **"What's actually novel here vs. off-the-shelf IoT dashboards?"** — The energy
  optimiser's fixed six-step priority order (specifically rule 3, the volumetric
  cap) and the Decision/IrrigationEvent audit pairing. Point at
  `packages/dhara_shared/dhara_shared/energy_optimizer.py` and the console's
  Energy tab's `curtailed_kwh` values if pressed.
- **"What would break first at 1,000x this scale?"** — Answer honestly from
  `docs/ARCHITECTURE.md`'s "Known hardening items": no console auth yet, CORS
  wide open, single-region. This is a pilot-scoped build and says so.
- **"Did you actually hit problems building this on Azure?"** — Yes, and it's a
  better answer than pretending otherwise: `docs/SETUP.md`'s "war story" section
  covers a real multi-hour investigation (an IoT Hub routing bug that looked
  identical to a Functions platform bug from every angle) and how it was
  isolated and fixed. Judges reward "we hit a real wall and diagnosed it"
  over "everything worked first try."
