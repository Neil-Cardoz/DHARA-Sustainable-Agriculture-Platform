"""FAO-56 style root-zone water balance, corrected by the measured soil probe.

This is step 2 ("Estimate") and step 3 ("Decide") of the irrigation control
loop that runs every 15 minutes on the edge box (and identically in the cloud
decision engine when L0/L1 have full connectivity). The correction step
(measured vs modelled) is what "re-tunes the soil parameters, so cheap probes
stay honest" per the architecture's control-loop diagram.
"""
from dataclasses import dataclass


@dataclass
class SoilParams:
    field_capacity_pct: float   # theta_fc, volumetric %
    wilting_point_pct: float    # theta_wp, volumetric %
    root_depth_mm: float = 400.0
    readily_available_fraction: float = 0.5  # depletion fraction p, FAO-56 Table 22 default


@dataclass
class WaterBalanceInput:
    soil: SoilParams
    kc: float                       # crop coefficient for current growth stage
    eto_mm_per_day: float           # reference evapotranspiration (forecast or measured)
    measured_moisture_pct: float    # current probe reading, volumetric %
    rainfall_mm_since_last: float = 0.0
    field_application_efficiency: float = 0.90  # drip ~0.90, furrow/flood ~0.45


@dataclass
class WaterBalanceResult:
    etc_mm_per_day: float
    taw_mm: float          # total available water in root zone
    raw_mm: float          # readily available water (management allowed depletion threshold)
    current_available_mm: float
    depletion_mm: float
    refill_threshold_crossed: bool
    recommended_depth_mm: float   # gross depth to apply, corrected for application efficiency
    recommended_net_mm: float     # net depth the crop actually needs


def compute_water_balance(inp: WaterBalanceInput) -> WaterBalanceResult:
    soil = inp.soil
    etc = inp.kc * inp.eto_mm_per_day

    taw = (soil.field_capacity_pct - soil.wilting_point_pct) / 100.0 * soil.root_depth_mm
    raw = soil.readily_available_fraction * taw

    current_available = max(
        0.0,
        (inp.measured_moisture_pct - soil.wilting_point_pct) / 100.0 * soil.root_depth_mm,
    )
    depletion = max(0.0, taw - current_available)

    refill_crossed = depletion >= raw

    net_mm = 0.0
    if refill_crossed:
        # Bring the root zone back to field capacity, net of any recent rainfall.
        net_mm = max(0.0, taw - current_available - inp.rainfall_mm_since_last)

    gross_mm = net_mm / inp.field_application_efficiency if net_mm > 0 else 0.0

    return WaterBalanceResult(
        etc_mm_per_day=etc,
        taw_mm=taw,
        raw_mm=raw,
        current_available_mm=current_available,
        depletion_mm=depletion,
        refill_threshold_crossed=refill_crossed,
        recommended_depth_mm=round(gross_mm, 2),
        recommended_net_mm=round(net_mm, 2),
    )


def reconcile_probe_drift(
    modelled_depletion_mm: float,
    measured_volume_applied_m3: float,
    plot_area_ha: float,
) -> float:
    """Correction step of the control loop: gap between measured and modelled water,
    expressed as an mm bias to feed back into the next cycle's soil parameters.

    Returns the bias in mm (positive => probe reads wetter than reality).
    """
    applied_mm_equivalent = (measured_volume_applied_m3 * 1000.0) / (plot_area_ha * 10_000.0) * 1000.0
    return round(applied_mm_equivalent - modelled_depletion_mm, 3)


# Default Kc curves by stage for a small reference-crop library.
# Configuration, not architecture -- swapping a crop swaps this table, the deck's own framing.
DEFAULT_KC_CURVES = {
    "tomato": {"initial": 0.6, "development": 0.85, "mid_season": 1.15, "late_season": 0.80},
    "onion": {"initial": 0.7, "development": 0.85, "mid_season": 1.05, "late_season": 0.85},
    "cotton": {"initial": 0.35, "development": 0.75, "mid_season": 1.15, "late_season": 0.65},
    "wheat": {"initial": 0.4, "development": 0.75, "mid_season": 1.15, "late_season": 0.35},
    "sugarcane": {"initial": 0.4, "development": 0.85, "mid_season": 1.25, "late_season": 0.75},
    "chickpea": {"initial": 0.4, "development": 0.7, "mid_season": 1.0, "late_season": 0.35},
}
