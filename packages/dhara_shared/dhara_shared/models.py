"""DHARA core data model.

Mirrors the entity set from the DHARA architecture submission ("Sixteen bytes
on the radio, seven entities in the store"): Plot, CropCycle, Device, Reading,
Decision, IrrigationEvent, StorageLot -- plus the operational tables needed to
run a multi-tenant cloud platform on top of them (FPOCluster, DeviceCommand,
AdvisoryInteraction, SavingsLedgerEntry, Operator).

Decision and IrrigationEvent are the audit pair: every litre moved is
traceable to the reasoning that asked for it (input_hash + reason_code +
model_version on Decision; decision_id foreign key on IrrigationEvent).
"""
from datetime import datetime, date
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def _uuid() -> UUID:
    return uuid4()


class DeviceType(str, Enum):
    soil_probe = "soil_probe"
    flow_meter = "flow_meter"
    energy_meter = "energy_meter"
    valve = "valve"
    edge_controller = "edge_controller"
    gateway = "gateway"
    pump_box = "pump_box"


class DeviceHealth(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    fault = "fault"
    offline = "offline"


class IrrigationSource(str, Enum):
    solar = "solar"
    grid = "grid"
    battery = "battery"
    manual = "manual"


class DegradationLevel(str, Enum):
    """The degradation ladder (L0-L4). No rung stops the water."""

    L0_nominal = "L0"          # cloud-optimised schedule, full precision
    L1_cloud_down = "L1"       # cluster runs cached model on stored forecast (~90%)
    L2_cluster_down = "L2"     # edge box runs its own water balance on local sensors (~75%)
    L3_sensor_fault = "L3"     # crop-calendar fallback schedule, service call raised (~50%)
    L4_edge_dead = "L4"        # mechanical bypass; farmer pumps by hand, advice by voice call


class FPOCluster(SQLModel, table=True):
    """A village cluster served by one LoRaWAN gateway / aggregation point (Tier 2)."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    name: str
    district: str
    state: str
    centroid_lat: float
    centroid_lon: float
    seasonal_volumetric_allocation_m3: float = Field(
        description="Cluster-level aquifer allocation cap used by rule 3 of the energy/water priority order"
    )
    cold_room_capacity_kg: float = 5000.0
    cold_room_pv_kwp: float = 5.0
    thermal_store_capacity_kwh_equiv: float = 15.0   # phase-change ice bank, sized to carry the cold room overnight
    battery_capacity_kwh: float = 2.0                 # controller/radio/gateway battery only, not irrigation
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Plot(SQLModel, table=True):
    """A single farmer's field. Geometry kept simple (centroid + area) for the pilot."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    cluster_id: UUID = Field(foreign_key="fpocluster.id", index=True)
    farmer_name: str
    farmer_phone_e164: str
    centroid_lat: float
    centroid_lon: float
    area_ha: float
    soil_texture: str = "loam"
    field_capacity_pct: float = 32.0     # theta_fc, volumetric %
    wilting_point_pct: float = 14.0      # theta_wp, volumetric %
    farmer_profile: str = "A"            # A = irrigated horticulture, B = irrigated field crops, C = rainfed/advisory-only
    seasonal_volumetric_cap_m3: float = 6500.0  # per-plot cap enforced regardless of solar surplus
    seasonal_volumetric_used_m3: float = 0.0
    solar_pump_capacity_kw: float = 3.0  # PM-KUSUM solar pump nameplate, financed separately from the platform
    pumping_head_m: float = 40.0
    pump_wire_to_water_efficiency: float = 0.35
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CropCycle(SQLModel, table=True):
    id: UUID = Field(default_factory=_uuid, primary_key=True)
    plot_id: UUID = Field(foreign_key="plot.id", index=True)
    crop: str
    variety: Optional[str] = None
    sowing_date: date
    stage: str = "initial"  # initial | development | mid_season | late_season
    kc_curve: dict = Field(default_factory=dict, sa_column=Column(JSON))  # {"initial":0.5,"development":0.8,...}
    seasonal_eto_mm: float = 450.0
    status: str = "active"  # active | harvested | failed


class Device(SQLModel, table=True):
    id: UUID = Field(default_factory=_uuid, primary_key=True)
    plot_id: Optional[UUID] = Field(default=None, foreign_key="plot.id", index=True)
    cluster_id: Optional[UUID] = Field(default=None, foreign_key="fpocluster.id", index=True)
    device_type: DeviceType
    hardware_id: str = Field(index=True, unique=True, description="IoT Hub deviceId")
    firmware_version: str = "0.1.0"
    last_seen: Optional[datetime] = None
    battery_mv: Optional[int] = None
    health_state: DeviceHealth = DeviceHealth.offline
    degradation_level: DegradationLevel = DegradationLevel.L0_nominal
    tamper_flag: bool = False


class Reading(SQLModel, table=True):
    id: UUID = Field(default_factory=_uuid, primary_key=True)
    device_id: UUID = Field(foreign_key="device.id", index=True)
    ts: datetime = Field(index=True)
    metric: str = Field(index=True)   # moisture_15cm | moisture_30cm | moisture_60cm | soil_temp_c | flow_l | pressure_kpa | energy_wh | battery_mv
    value: float
    quality_flag: str = "ok"          # ok | suspect | interpolated | stale


class Decision(SQLModel, table=True):
    """One output of the 15-minute sense -> estimate -> decide -> actuate -> verify loop."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    plot_id: UUID = Field(foreign_key="plot.id", index=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    input_hash: str = Field(description="SHA-256 of the sensed+forecast inputs used, for replayability")
    depth_mm: float
    window_start: datetime
    window_end: datetime
    reason_code: str
    model_version: str
    degradation_level: DegradationLevel = DegradationLevel.L0_nominal
    confidence: float = 1.0


class IrrigationEvent(SQLModel, table=True):
    """The audit partner of Decision: what actually moved, measured, not modelled."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    plot_id: UUID = Field(foreign_key="plot.id", index=True)
    decision_id: Optional[UUID] = Field(default=None, foreign_key="decision.id")
    ts_start: datetime
    ts_end: Optional[datetime] = None
    volume_m3: float = 0.0
    energy_kwh: float = 0.0
    source: IrrigationSource = IrrigationSource.solar
    verified: bool = False
    verification_delta_pct: Optional[float] = None  # measured vs intended volume


class StorageLot(SQLModel, table=True):
    id: UUID = Field(default_factory=_uuid, primary_key=True)
    cluster_id: UUID = Field(foreign_key="fpocluster.id", index=True)
    plot_id: Optional[UUID] = Field(default=None, foreign_key="plot.id")
    crop: str
    mass_kg: float
    intake_ts: datetime
    thermal_history: list = Field(default_factory=list, sa_column=Column(JSON))  # [{"ts":..., "temp_c":...}]
    predicted_shelf_life_hours: Optional[float] = None
    dispatched_ts: Optional[datetime] = None
    dispatched_to: Optional[str] = None


class DeviceCommand(SQLModel, table=True):
    """Cloud-to-device command log (setpoints sent down via IoT Hub)."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    device_id: UUID = Field(foreign_key="device.id", index=True)
    decision_id: Optional[UUID] = Field(default=None, foreign_key="decision.id")
    ts: datetime = Field(default_factory=datetime.utcnow)
    command: str  # e.g. "irrigate", "stop", "set_lamp"
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    acked: bool = False
    acked_ts: Optional[datetime] = None


class AdvisoryInteraction(SQLModel, table=True):
    """Every farmer-facing advisory exchange (WhatsApp / voice call / lamp), for the audit trail."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    plot_id: Optional[UUID] = Field(default=None, foreign_key="plot.id", index=True)
    channel: str  # whatsapp | voice_call | pump_box_lamp | operator_console
    ts: datetime = Field(default_factory=datetime.utcnow)
    direction: str  # inbound | outbound
    language: str = "hi"
    input_text: Optional[str] = None
    input_photo_url: Optional[str] = None
    response_text: Optional[str] = None
    confidence: Optional[float] = None
    model_version: Optional[str] = None
    escalated_to_human: bool = False
    resolved: bool = False


class SavingsLedgerEntry(SQLModel, table=True):
    """The verification ledger a discom, carbon buyer, or PMKSY audit can check against."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    plot_id: UUID = Field(foreign_key="plot.id", index=True)
    period_start: date
    period_end: date
    baseline_water_m3: float
    actual_water_m3: float
    baseline_energy_kwh: float
    actual_energy_kwh: float
    grid_emission_factor_tco2_per_mwh: float = 0.710
    avoided_tco2e: float = 0.0
    verified: bool = False
    verified_by: Optional[str] = None


class EnergyArbitrationLog(SQLModel, table=True):
    """One cluster-level run of the fixed six-step solar priority order."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    cluster_id: UUID = Field(foreign_key="fpocluster.id", index=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    available_solar_kwh: float
    allocations: list = Field(default_factory=list, sa_column=Column(JSON))  # [{"claim_type":..., "allocated_kwh":...}]
    exported_to_feeder_kwh: float = 0.0
    unallocated_kwh: float = 0.0


class Operator(SQLModel, table=True):
    """FPO / ESCO console user."""

    id: UUID = Field(default_factory=_uuid, primary_key=True)
    cluster_id: UUID = Field(foreign_key="fpocluster.id")
    name: str
    email: str = Field(unique=True, index=True)
    entra_object_id: Optional[str] = None
    role: str = "operator"  # operator | admin | agronomist
