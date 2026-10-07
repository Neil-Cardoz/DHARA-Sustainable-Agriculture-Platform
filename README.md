# DHARA — Sustainable Agriculture Platform

An energy-aware control and advisory platform for smallholder irrigation, storage,
and market access. This is the software implementation of the architecture in
`DHARA — Sustainable Agriculture Platform.pdf`, built on Azure.

## What's here

```
packages/dhara_shared/      Shared domain: data models, FAO-56 water balance,
                             energy optimiser, frame codec, degradation ladder
services/api/                Core FastAPI backend (Azure Container Apps)
services/ingestion/          IoT Hub -> Postgres telemetry worker (Azure Container Apps,
                             direct azure-eventhub SDK consumer -- see docs/SETUP.md's
                             war story for why this isn't a Functions trigger)
services/decision-engine/    Irrigation control loop, energy arbitration,
                             savings ledger (Azure Functions, Flex Consumption)
services/advisory-bot/       WhatsApp + voice farmer advisory (Azure Container Apps)
services/edge-simulator/     Simulates Tier 0-2 field hardware against real IoT Hub
apps/operator-console/       React dashboard for the FPO/ESCO (Static Web Apps)
infra/                       Bicep infrastructure-as-code for the whole platform
docs/                        Setup, architecture, secrets guide, user manual
```

## Start here

| I want to... | Read |
|---|---|
| Understand the design | `docs/ARCHITECTURE.md` |
| Deploy this from scratch | `docs/SETUP.md` |
| Know where a secret/credential comes from | `docs/azure-requirements.md` |
| See it working in 5 minutes (already deployed) | `docs/QUICKSTART.md` |
| Learn how to actually use it (farmer/operator/agronomist/admin) | `docs/MANUAL.md` |
| Present this live to an audience | `docs/script.md` |

## Status of this deployment

Resource group `dhara-platform-rg`, subscription "Azure for Students", region
`centralindia` (+ `koreacentral` for Azure OpenAI, `eastasia` for the operator
console — see `docs/azure-requirements.md` §1 for why). Deployed and verified
working end-to-end against real Azure IoT Hub, Postgres, Container Apps,
Functions, Communication Services, and Azure OpenAI: the edge simulator's
telemetry flows through `ingestion` into Postgres, and `decision-engine` reads it
back and produces real irrigation decisions with computed depths — the full
sense→estimate→decide→actuate loop, confirmed against live data, not just a
smoke test.

Two things need action outside this codebase before the farmer-facing WhatsApp/voice
channels are live in the real world (not blockers to anything else — see
`docs/azure-requirements.md` §5): a Meta Business verification for WhatsApp, and
purchasing an India phone number for outbound calls.
