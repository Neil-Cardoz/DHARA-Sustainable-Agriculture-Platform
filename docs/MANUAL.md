# DHARA Platform — User Manual

This is the day-to-day operating manual, written for the four people who actually
touch this system: the farmer, the FPO operator, the agronomist, and the person who
keeps the platform running. If you want to understand *why* it's built this way, read
`docs/ARCHITECTURE.md` instead; this document is about *how to use it*.

---

## For the farmer

You interact with DHARA through whichever of these is easiest for you — none of them
require a smartphone.

### The pump box (three lamps)
- **Green** — water now. Press the button below the lamps; the pump runs the
  recommended amount and stops itself.
- **Amber** — wait, soil is still wet enough.
- **Red** — call for service (a sensor or valve needs attention).

You never need to read a number off anything. The box has already done the FAO-56
water-balance calculation for you.

### The morning phone call (any handset, no smartphone needed)
Around 6:40 AM, if irrigation is needed, you'll get a call. It says *why* before
*what*: e.g. "soil at 30 centimetres has dropped to 41%, no rain expected for four
days" — then "your tomato plot needs 18 millimetres today." Press **1** to start the
pump remotely, **2** to hear it again, **9** to talk to a person at your FPO.

### WhatsApp
Ask a question by typing or sending a voice note, in your own language. If you send a
photo of an affected leaf, it's forwarded along with your question. Two outcomes:
- A direct answer, with the reasoning included (not just an instruction).
- "I am not certain from what you sent — passing this to the agronomist at your FPO;
  they will follow up before noon." This is deliberate: a wrong answer once loses your
  trust for a season, so the system says "I don't know" rather than guessing.

### What if nothing responds?
The pump box's lamps still work even with the cloud, the village gateway, or the
soil probe down — the degradation ladder (see `docs/ARCHITECTURE.md`) means it falls
back through progressively simpler schedules, but it never stops watering. If the box
itself is dead, there's a manual bypass valve at the pump — ask your FPO operator to
show you where it is at commissioning.

---

## For the FPO operator (the console)

Open the console URL your DHARA administrator gave you (see
`docs/azure-requirements.md` if you're setting this up for the first time).

### Dashboard
Your cluster at a glance: number of farms, device health (how many boxes are
healthy/degraded/offline), and cold-room occupancy.

### Plots
Every farmer in your cluster. Click one to see:
- Their active crop and growth stage
- The latest irrigation decision and why it was made (`reason_code` — e.g.
  `REFILL_THRESHOLD_CROSSED`, `CAPPED_BY_SEASONAL_ALLOCATION`,
  `SEASONAL_ALLOCATION_EXHAUSTED`)
- Their remaining seasonal water allocation
- Device health for their specific hardware
- Every irrigation event, and whether it's been **verified** (the flow meter's
  actual measurement matched the intended volume) — this is the number that backs
  any savings claim you make to a discom or buyer.

### Cold Storage
Every lot currently in the shared cold room, sorted by **predicted remaining shelf
life** — not by how long it's been sitting there. A lot that had a door-open event
and warmed up moves to the top of the dispatch queue automatically. Dispatch the
ones at the top first.

### Energy
The six-step solar priority order running for your cluster, refreshed every 15
minutes: crop-critical irrigation first, then cold-room pulldown, then tank fill
(capped at the season's allocation — this is what stops free solar from becoming
wasted water), then thermal store, then battery, then grid export.

### Advisory Log
Every WhatsApp/voice/lamp interaction across your cluster, with a confidence score
and whether it was escalated to a human. **Check the escalated ones daily** — that's
your agronomist's queue.

### Savings Ledger
The auditable weekly comparison of actual metered water/energy against the
architecture's stated baseline, in water (m³), energy (kWh), and avoided CO2e. This
is what you'd hand to a discom or carbon-credit buyer, or use to support a PMKSY
subsidy claim.

---

## For the agronomist

You get pulled in when the advisory bot's confidence drops below the threshold
(currently 0.72) — the Advisory Log page shows `escalated: true` rows. Common
triggers: a pest/disease question the model can't diagnose from text alone (photos
aren't run through an image classifier in this build — see
`docs/ARCHITECTURE.md`'s hardening list), or a question genuinely outside
irrigation/storage/basic agronomy.

Follow up directly with the farmer (their phone number is on the plot detail page).
There's no in-app reply tool yet — that's a natural next feature once WhatsApp
Advanced Messaging is live (see `docs/azure-requirements.md` §5).

---

## For the platform administrator

### Day-to-day
- **Logs**: for the `api`/`advisory-bot`/`ingestion` Container Apps, `az
  containerapp logs show -n <app> -g dhara-platform-rg --follow`. For
  `decision-engine` (Flex Consumption Functions doesn't support CLI log
  streaming), query its own Application Insights resource instead — Flex
  Consumption apps get a dedicated one, separate from the platform's main
  `dhara-appi-<suffix>` (`az monitor app-insights component show -g
  dhara-platform-rg` lists all of them):
  ```bash
  az monitor app-insights query -g dhara-platform-rg -a <decision-func-name> \
    --analytics-query "AppTraces | where TimeGenerated > ago(15m) | order by TimeGenerated desc | take 30"
  ```
- **Adding a new cluster/farm**: extend `services/edge-simulator/provision_devices.py`
  or POST directly to `/clusters`, `/plots`, `/devices` on the API — see the
  OpenAPI docs at `https://<api-fqdn>/docs` (FastAPI generates this automatically).
- **Rotating a secret**: `docs/azure-requirements.md` has the exact command for
  every credential.
- **Scaling up**: `docs/azure-requirements.md` §11.

### Weekly
- Check the Savings Ledger closed correctly (`CloseLedgerPeriod` runs Mondays 03:00).
- Skim the Advisory Log for escalation volume — a spike usually means either a real
  agronomic event (pest outbreak, unusual weather) or the confidence threshold needs
  retuning for your crop mix.

### Before every "who's using this" conversation
Re-read `docs/ARCHITECTURE.md`'s "Known hardening items" list. This is a pilot-scoped
build: the console has no sign-in yet, and WhatsApp/voice need a Meta Business
verification and a purchased phone number that no amount of infrastructure-as-code
can get you — budget real calendar time for those, not engineering time.
