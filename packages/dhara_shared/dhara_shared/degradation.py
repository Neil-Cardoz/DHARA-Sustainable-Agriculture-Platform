"""The degradation ladder: each rung is a declared, tested operating mode, not
an error path discovered in the field. No rung stops the water.

  L0  nothing failed              cloud-optimised schedule, aware of forecast+solar   ~100%
  L1  backhaul to cloud down      cluster runs cached model on stored forecast        ~90%
  L2  cluster gateway down        edge box runs its own water balance on local sensors ~75%
  L3  soil probe failed/drifting  crop-calendar fallback schedule, raises service call ~50%
  L4  edge box dead               mechanical bypass; farmer pumps by hand, voice advice manual
"""
from dataclasses import dataclass
from enum import IntEnum


class Rung(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4


@dataclass(frozen=True)
class RungInfo:
    code: str
    description: str
    precision_target_pct: int | None  # None = "manual, still watered"


LADDER: dict[Rung, RungInfo] = {
    Rung.L0: RungInfo("L0", "Cloud-optimised schedule, aware of forecast and solar", 100),
    Rung.L1: RungInfo("L1", "Cluster runs the cached model on its stored forecast", 90),
    Rung.L2: RungInfo("L2", "Edge box runs its own water balance on local sensors", 75),
    Rung.L3: RungInfo("L3", "Falls back to the crop-calendar schedule, raises a service call", 50),
    Rung.L4: RungInfo("L4", "Mechanical bypass; farmer pumps by hand, advice by voice call", None),
}


def classify_rung(
    *,
    cloud_reachable: bool,
    cluster_gateway_reachable: bool,
    soil_probe_healthy: bool,
    edge_box_alive: bool,
) -> Rung:
    """Pure function mirroring the edge box's own fallback logic, so the cloud
    decision engine and the operator console agree on what state a plot is in.
    """
    if not edge_box_alive:
        return Rung.L4
    if not soil_probe_healthy:
        return Rung.L3
    if not cluster_gateway_reachable:
        return Rung.L2
    if not cloud_reachable:
        return Rung.L1
    return Rung.L0
