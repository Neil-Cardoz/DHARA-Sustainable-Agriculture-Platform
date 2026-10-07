"""Cluster-level solar energy arbitration.

Implements the fixed six-step priority order from the architecture ("Surplus
midday solar is spent in a fixed order, and irrigation is not the last claim
on it"). Rule 3 (tank fill capped at the season's volumetric allocation) is
the one that stops free energy from turning into wasted water -- it is
enforced here, not left to the caller.
"""
from dataclasses import dataclass, field
from enum import Enum


class EnergyClaimType(str, Enum):
    crop_critical_irrigation = "crop_critical_irrigation"
    cold_room_pulldown = "cold_room_pulldown"
    tank_fill = "tank_fill"
    thermal_store_charge = "thermal_store_charge"
    battery_topup = "battery_topup"
    grid_export = "grid_export"


@dataclass
class EnergyClaim:
    claim_type: EnergyClaimType
    plot_or_asset_id: str
    requested_kwh: float
    # Only used for tank_fill: how much of the seasonal volumetric cap remains, expressed in kWh-equivalent
    # of pumping still allowed this season. Caller computes this from Plot.seasonal_volumetric_cap_m3 -
    # Plot.seasonal_volumetric_used_m3 and the plot's kWh-per-m3 lift cost.
    remaining_allocation_kwh: float | None = None


@dataclass
class EnergyAllocation:
    claim_type: EnergyClaimType
    plot_or_asset_id: str
    allocated_kwh: float
    curtailed_kwh: float


PRIORITY_ORDER = [
    EnergyClaimType.crop_critical_irrigation,
    EnergyClaimType.cold_room_pulldown,
    EnergyClaimType.tank_fill,
    EnergyClaimType.thermal_store_charge,
    EnergyClaimType.battery_topup,
    EnergyClaimType.grid_export,
]


@dataclass
class ArbitrationResult:
    allocations: list[EnergyAllocation] = field(default_factory=list)
    unallocated_kwh: float = 0.0
    exported_to_feeder_kwh: float = 0.0


def arbitrate(available_solar_kwh: float, claims: list[EnergyClaim]) -> ArbitrationResult:
    """Allocate available solar surplus across claims in the fixed priority order.

    Tank-fill claims are hard-capped at `remaining_allocation_kwh` regardless of
    how much surplus solar is available -- this is what prevents an efficiency
    gain from being spent pumping more water rather than saving any.
    """
    remaining = available_solar_kwh
    result = ArbitrationResult()

    claims_by_type: dict[EnergyClaimType, list[EnergyClaim]] = {}
    for c in claims:
        claims_by_type.setdefault(c.claim_type, []).append(c)

    for claim_type in PRIORITY_ORDER:
        for claim in claims_by_type.get(claim_type, []):
            requested = claim.requested_kwh
            if claim_type == EnergyClaimType.tank_fill and claim.remaining_allocation_kwh is not None:
                requested = min(requested, max(0.0, claim.remaining_allocation_kwh))

            allocated = min(requested, remaining)
            curtailed = claim.requested_kwh - allocated
            remaining -= allocated

            if claim_type == EnergyClaimType.grid_export:
                result.exported_to_feeder_kwh += allocated
            else:
                result.allocations.append(
                    EnergyAllocation(
                        claim_type=claim_type,
                        plot_or_asset_id=claim.plot_or_asset_id,
                        allocated_kwh=round(allocated, 4),
                        curtailed_kwh=round(curtailed, 4),
                    )
                )

    result.unallocated_kwh = round(remaining, 4)
    return result
