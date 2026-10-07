"""Core of the DHARA cloud decision engine.

Implements, at cluster/cloud scale (L0 on the degradation ladder), the same
five-step loop each edge box runs locally when it is on its own (L2):
sense -> estimate -> decide -> actuate -> verify -- plus the cluster-level
energy/storage optimiser and the shelf-life dispatch queue.
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from azure.iot.hub import IoTHubRegistryManager
from azure.iot.hub.models import CloudToDeviceMethod
from dhara_shared.energy_optimizer import EnergyClaim, EnergyClaimType, arbitrate
from dhara_shared.shelf_life import predict_remaining_shelf_life_hours
from dhara_shared.water_balance import (
    DEFAULT_KC_CURVES,
    SoilParams,
    WaterBalanceInput,
    compute_water_balance,
)
from dhara_shared.weather import estimate_available_solar_kwh, fetch_forecast

MODEL_VERSION = "decision-engine-0.1.0"

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")
IOT_HUB_CONNECTION_STRING = os.environ.get("IOT_HUB_CONNECTION_STRING")
INTERVAL_MINUTES = int(os.environ.get("CONTROL_LOOP_INTERVAL_MINUTES", "15"))
ADVISORY_BOT_URL = os.environ.get("ADVISORY_BOT_URL", "http://localhost:8100")

_registry_manager = None


def _registry() -> "IoTHubRegistryManager | None":
    global _registry_manager
    if IOT_HUB_CONNECTION_STRING is None:
        return None
    if _registry_manager is None:
        _registry_manager = IoTHubRegistryManager(IOT_HUB_CONNECTION_STRING)
    return _registry_manager


def _client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_URL, headers={"X-API-Key": API_KEY}, timeout=20)


def _avg_metric(readings: list[dict], metric: str) -> float | None:
    vals = [r["value"] for r in readings if r["metric"] == metric]
    return sum(vals) / len(vals) if vals else None


def run_irrigation_cycle() -> None:
    """One tick of the 15-minute control loop, for every active plot."""
    with _client() as client:
        clusters = client.get("/clusters").json()
        for cluster in clusters:
            plots = client.get("/plots", params={"cluster_id": cluster["id"]}).json()
            forecast = None
            try:
                forecast = fetch_forecast(cluster["centroid_lat"], cluster["centroid_lon"], days=1)
            except Exception:
                logging.exception("weather forecast fetch failed for cluster %s; using probe-only estimate", cluster["id"])

            for plot in plots:
                try:
                    _run_plot_cycle(client, plot, forecast)
                except Exception:
                    logging.exception("irrigation cycle failed for plot %s", plot["id"])


def _run_plot_cycle(client: httpx.Client, plot: dict, forecast) -> None:
    dashboard = client.get(f"/plots/{plot['id']}/dashboard").json()
    cycle = dashboard.get("active_crop_cycle")
    if not cycle:
        return  # nothing sown, nothing to schedule

    devices = dashboard["devices"]
    readings = dashboard["recent_readings"]

    controller = next((d for d in devices if d["device_type"] == "edge_controller"), None)
    if controller is None:
        logging.warning("plot %s has no edge_controller device registered", plot["id"])
        return

    m15 = _avg_metric(readings, "moisture_15cm")
    m30 = _avg_metric(readings, "moisture_30cm")
    m60 = _avg_metric(readings, "moisture_60cm")
    measured_moisture = next((v for v in [m30, m15, m60] if v is not None), None)

    if measured_moisture is None:
        logging.info("plot %s has no recent soil readings; skipping cycle (device offline path handled by degradation ladder)", plot["id"])
        return

    eto = forecast[0].eto_mm if forecast else 4.5  # conservative reference-crop fallback
    kc_curve = cycle.get("kc_curve") or DEFAULT_KC_CURVES.get(cycle["crop"].lower(), {"mid_season": 1.0})
    kc = kc_curve.get(cycle["stage"], list(kc_curve.values())[0])

    wb_input = WaterBalanceInput(
        soil=SoilParams(
            field_capacity_pct=plot["field_capacity_pct"],
            wilting_point_pct=plot["wilting_point_pct"],
        ),
        kc=kc,
        eto_mm_per_day=eto,
        measured_moisture_pct=measured_moisture,
        field_application_efficiency=0.85,
    )
    result = compute_water_balance(wb_input)

    input_payload = {
        "plot_id": plot["id"],
        "moisture": measured_moisture,
        "eto": eto,
        "kc": kc,
        "field_capacity_pct": plot["field_capacity_pct"],
        "wilting_point_pct": plot["wilting_point_pct"],
    }
    input_hash = hashlib.sha256(json.dumps(input_payload, sort_keys=True).encode()).hexdigest()

    now = datetime.now(timezone.utc)
    reason_code = "NO_ACTION_ABOVE_THRESHOLD"
    depth_mm = 0.0

    remaining_allocation_m3 = max(
        0.0, plot["seasonal_volumetric_cap_m3"] - plot["seasonal_volumetric_used_m3"]
    )
    area_m2 = plot["area_ha"] * 10_000

    if result.refill_threshold_crossed:
        max_allowed_mm = (remaining_allocation_m3 / area_m2) * 1000 if area_m2 else 0.0
        depth_mm = min(result.recommended_depth_mm, max_allowed_mm)
        reason_code = "REFILL_THRESHOLD_CROSSED" if depth_mm >= result.recommended_depth_mm else "CAPPED_BY_SEASONAL_ALLOCATION"
        if depth_mm <= 0:
            reason_code = "SEASONAL_ALLOCATION_EXHAUSTED"

    decision = client.post(
        "/control/decisions",
        json={
            "plot_id": plot["id"],
            "ts": now.isoformat(),
            "input_hash": input_hash,
            "depth_mm": round(depth_mm, 2),
            "window_start": now.isoformat(),
            "window_end": (now + timedelta(minutes=INTERVAL_MINUTES)).isoformat(),
            "reason_code": reason_code,
            "model_version": MODEL_VERSION,
            "degradation_level": "L0",
            "confidence": 0.95,
        },
    ).json()

    if depth_mm <= 0:
        return

    volume_m3 = round(depth_mm / 1000 * area_m2, 3)
    lift_kwh = round(
        (volume_m3 * 9.81 * plot["pumping_head_m"]) / (3600 * plot["pump_wire_to_water_efficiency"]), 3
    )

    _send_irrigate_command(controller["hardware_id"], depth_mm, volume_m3, decision["id"])

    client.post(
        f"/devices/{controller['id']}/commands",
        json={
            "device_id": controller["id"],
            "decision_id": decision["id"],
            "ts": now.isoformat(),
            "command": "irrigate",
            "payload": {"depth_mm": depth_mm, "volume_m3": volume_m3, "duration_min": INTERVAL_MINUTES},
            "acked": False,
        },
    )

    client.post(
        "/control/irrigation-events",
        json={
            "plot_id": plot["id"],
            "decision_id": decision["id"],
            "ts_start": now.isoformat(),
            "volume_m3": volume_m3,
            "energy_kwh": lift_kwh,
            "source": "solar",
            "verified": False,
        },
    )


def _send_irrigate_command(device_hardware_id: str, depth_mm: float, volume_m3: float, decision_id: str) -> None:
    registry = _registry()
    if registry is None:
        logging.info("IOT_HUB_CONNECTION_STRING not set; skipping real C2D send (dev/demo mode) for %s", device_hardware_id)
        return
    try:
        registry.send_c2d_message(
            device_hardware_id,
            json.dumps({
                "command": "irrigate",
                "depth_mm": depth_mm,
                "volume_m3": volume_m3,
                "decision_id": decision_id,
            }),
        )
    except Exception:
        logging.exception("failed to send C2D irrigate command to %s", device_hardware_id)


def verify_irrigation_events() -> None:
    """Step 5 of the control loop: reconcile intended volume against the flow
    meter's measured cumulative counter. This is what makes the savings claim
    auditable, and what a discom or carbon buyer is actually paying for.
    """
    with _client() as client:
        events = client.get("/control/irrigation-events", params={"limit": 200}).json()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=INTERVAL_MINUTES)

        for event in events:
            if event["verified"]:
                continue
            ts_start = datetime.fromisoformat(event["ts_start"])
            if ts_start.tzinfo is None:
                ts_start = ts_start.replace(tzinfo=timezone.utc)
            if ts_start > cutoff:
                continue  # window not closed yet

            devices = client.get("/devices", params={"plot_id": event["plot_id"]}).json()
            controller = next((d for d in devices if d["device_type"] == "edge_controller"), None)
            if not controller:
                continue

            window_end = ts_start + timedelta(minutes=INTERVAL_MINUTES)
            readings = client.get(
                "/telemetry",
                params={
                    "device_id": controller["id"],
                    "metric": "flow_l_cumulative",
                    "since": ts_start.isoformat(),
                    "limit": 50,
                },
            ).json()
            readings = [r for r in readings if r["ts"] <= window_end.isoformat()]
            if len(readings) < 2:
                continue

            readings.sort(key=lambda r: r["ts"])
            measured_litres = max(0.0, readings[-1]["value"] - readings[0]["value"])
            measured_m3 = measured_litres / 1000.0
            intended_m3 = event["volume_m3"]
            delta_pct = round(100 * (measured_m3 - intended_m3) / intended_m3, 1) if intended_m3 else 0.0

            client.patch(
                f"/control/irrigation-events/{event['id']}",
                json={"verified": True, "verification_delta_pct": delta_pct, "volume_m3": measured_m3},
            )

            plot = client.get(f"/plots/{event['plot_id']}").json()
            client.patch(
                f"/plots/{event['plot_id']}",
                json={"seasonal_volumetric_used_m3": plot["seasonal_volumetric_used_m3"] + measured_m3},
            )


def run_energy_arbitration() -> None:
    """Cluster-level solar priority order: crop-critical irrigation, cold room,
    tank fill (capped), thermal store, battery, export/curtail.
    """
    with _client() as client:
        clusters = client.get("/clusters").json()
        for cluster in clusters:
            try:
                _arbitrate_cluster(client, cluster)
            except Exception:
                logging.exception("energy arbitration failed for cluster %s", cluster["id"])


def _arbitrate_cluster(client: httpx.Client, cluster: dict) -> None:
    forecast = fetch_forecast(cluster["centroid_lat"], cluster["centroid_lon"], days=1)
    radiation = forecast[0].shortwave_radiation_mj_m2 if forecast else 18.0

    plots = client.get("/plots", params={"cluster_id": cluster["id"]}).json()
    plot_solar_kwh = sum(
        estimate_available_solar_kwh(radiation, p["solar_pump_capacity_kw"], INTERVAL_MINUTES) for p in plots
    )
    cold_room_solar_kwh = estimate_available_solar_kwh(radiation, cluster["cold_room_pv_kwp"], INTERVAL_MINUTES)
    available = round(plot_solar_kwh + cold_room_solar_kwh, 3)

    recent_decisions = client.get("/control/decisions", params={"limit": len(plots) or 1}).json()
    irrigating_plot_ids = {d["plot_id"] for d in recent_decisions if d["depth_mm"] > 0}

    claims: list[EnergyClaim] = []
    for plot in plots:
        if plot["id"] in irrigating_plot_ids:
            claims.append(
                EnergyClaim(
                    claim_type=EnergyClaimType.crop_critical_irrigation,
                    plot_or_asset_id=plot["id"],
                    requested_kwh=estimate_available_solar_kwh(radiation, plot["solar_pump_capacity_kw"], INTERVAL_MINUTES),
                )
            )

    claims.append(
        EnergyClaim(
            claim_type=EnergyClaimType.cold_room_pulldown,
            plot_or_asset_id=str(cluster["id"]),
            requested_kwh=min(cold_room_solar_kwh, 3.0),
        )
    )
    for plot in plots:
        remaining_m3 = max(0.0, plot["seasonal_volumetric_cap_m3"] - plot["seasonal_volumetric_used_m3"])
        kwh_per_m3 = (9.81 * plot["pumping_head_m"]) / (3600 * plot["pump_wire_to_water_efficiency"])
        claims.append(
            EnergyClaim(
                claim_type=EnergyClaimType.tank_fill,
                plot_or_asset_id=plot["id"],
                requested_kwh=1.0,
                remaining_allocation_kwh=remaining_m3 * kwh_per_m3,
            )
        )
    claims.append(
        EnergyClaim(
            claim_type=EnergyClaimType.thermal_store_charge,
            plot_or_asset_id=str(cluster["id"]),
            requested_kwh=cluster["thermal_store_capacity_kwh_equiv"] * 0.1,
        )
    )
    claims.append(
        EnergyClaim(
            claim_type=EnergyClaimType.battery_topup,
            plot_or_asset_id=str(cluster["id"]),
            requested_kwh=cluster["battery_capacity_kwh"] * 0.1,
        )
    )
    claims.append(
        EnergyClaim(
            claim_type=EnergyClaimType.grid_export,
            plot_or_asset_id=str(cluster["id"]),
            requested_kwh=10_000,  # absorb whatever is left, capped naturally by `available`
        )
    )

    result = arbitrate(available, claims)

    client.post(
        "/energy/arbitration-logs",
        json={
            "cluster_id": cluster["id"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "available_solar_kwh": available,
            "allocations": [
                {
                    "claim_type": a.claim_type.value,
                    "plot_or_asset_id": a.plot_or_asset_id,
                    "allocated_kwh": a.allocated_kwh,
                    "curtailed_kwh": a.curtailed_kwh,
                }
                for a in result.allocations
            ],
            "exported_to_feeder_kwh": result.exported_to_feeder_kwh,
            "unallocated_kwh": result.unallocated_kwh,
        },
    )


def run_shelf_life_update() -> None:
    """Recompute predicted_shelf_life_hours for every active storage lot and
    reorder the dispatch queue implicitly (the API's list endpoint already
    sorts by intake_ts; the console re-sorts by predicted life ascending).
    """
    with _client() as client:
        lots = client.get("/storage-lots", params={"active_only": True}).json()
        for lot in lots:
            remaining = predict_remaining_shelf_life_hours(lot["crop"], lot["thermal_history"])
            client.patch(f"/storage-lots/{lot['id']}", json={"predicted_shelf_life_hours": remaining})


def send_daily_voice_advisories() -> None:
    """Rung 2 of the farmer interface: an outbound voice call carrying the
    morning's irrigation recommendation, for farmers without a smartphone.
    """
    with _client() as client:
        plots = client.get("/plots").json()
        with httpx.Client(base_url=ADVISORY_BOT_URL, timeout=30) as advisory:
            for plot in plots:
                try:
                    advisory.post("/outbound/voice-advisory", params={"plot_id": plot["id"]})
                except Exception:
                    logging.exception("failed to trigger voice advisory for plot %s", plot["id"])


def close_ledger_period(period_days: int = 7) -> None:
    """Weekly job: compare actual metered water/energy against the stated
    architecture baseline for each plot and write an auditable ledger entry.
    """
    GRID_EMISSION_FACTOR_TCO2_PER_MWH = 0.710  # CEA baseline v21.0, FY25

    with _client() as client:
        plots = client.get("/plots").json()
        period_end = datetime.now(timezone.utc).date()
        period_start = period_end - timedelta(days=period_days)

        for plot in plots:
            events = client.get(
                "/control/irrigation-events", params={"plot_id": plot["id"], "limit": 1000}
            ).json()
            actual_water_m3 = sum(e["volume_m3"] for e in events if e["verified"])
            actual_energy_kwh = sum(e["energy_kwh"] for e in events if e["verified"])

            # Baseline from the architecture's stated assumptions: 450mm ETo, 0.45 field
            # efficiency, +20% over-application from blind scheduling (scaled to the period).
            area_ha = plot["area_ha"]
            baseline_water_m3 = (450 / 1000) * area_ha * 10_000 * (1 / 0.45) * 1.20 * (period_days / 120)
            kwh_per_m3 = (9.81 * plot["pumping_head_m"]) / (3600 * plot["pump_wire_to_water_efficiency"])
            baseline_energy_kwh = baseline_water_m3 * kwh_per_m3

            avoided_mwh = max(0.0, baseline_energy_kwh - actual_energy_kwh) / 1000
            avoided_tco2e = round(avoided_mwh * GRID_EMISSION_FACTOR_TCO2_PER_MWH, 4)

            client.post(
                "/ledger",
                json={
                    "plot_id": plot["id"],
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "baseline_water_m3": round(baseline_water_m3, 2),
                    "actual_water_m3": round(actual_water_m3, 2),
                    "baseline_energy_kwh": round(baseline_energy_kwh, 2),
                    "actual_energy_kwh": round(actual_energy_kwh, 2),
                    "grid_emission_factor_tco2_per_mwh": 0.710,
                    "avoided_tco2e": avoided_tco2e,
                    "verified": True,
                    "verified_by": "decision-engine-auto",
                },
            )
