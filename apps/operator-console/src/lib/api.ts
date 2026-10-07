const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export interface Cluster {
  id: string;
  name: string;
  district: string;
  state: string;
  centroid_lat: number;
  centroid_lon: number;
  cold_room_capacity_kg: number;
}

export interface Plot {
  id: string;
  cluster_id: string;
  farmer_name: string;
  farmer_phone_e164: string;
  area_ha: number;
  farmer_profile: string;
  seasonal_volumetric_cap_m3: number;
  seasonal_volumetric_used_m3: number;
}

export interface Device {
  id: string;
  hardware_id: string;
  device_type: string;
  health_state: string;
  degradation_level: string;
  battery_mv: number | null;
  last_seen: string | null;
}

export interface Decision {
  id: string;
  ts: string;
  depth_mm: number;
  reason_code: string;
  degradation_level: string;
  confidence: number;
}

export interface IrrigationEvent {
  id: string;
  ts_start: string;
  volume_m3: number;
  energy_kwh: number;
  source: string;
  verified: boolean;
  verification_delta_pct: number | null;
}

export interface StorageLot {
  id: string;
  crop: string;
  mass_kg: number;
  intake_ts: string;
  predicted_shelf_life_hours: number | null;
  dispatched_ts: string | null;
}

export interface AdvisoryInteraction {
  id: string;
  channel: string;
  ts: string;
  direction: string;
  input_text: string | null;
  response_text: string | null;
  confidence: number | null;
  escalated_to_human: boolean;
}

export interface LedgerSummary {
  entries: number;
  total_water_saved_m3: number;
  total_energy_saved_kwh: number;
  total_avoided_tco2e: number;
}

export const api = {
  clusters: () => request<Cluster[]>("/clusters"),
  clusterSummary: (id: string) => request<any>(`/clusters/${id}/summary`),
  plots: (clusterId?: string) => request<Plot[]>(`/plots${clusterId ? `?cluster_id=${clusterId}` : ""}`),
  plotDashboard: (id: string) => request<any>(`/plots/${id}/dashboard`),
  devices: (clusterId?: string) => request<Device[]>(`/devices${clusterId ? `?cluster_id=${clusterId}` : ""}`),
  decisions: (plotId: string) => request<Decision[]>(`/control/decisions?plot_id=${plotId}`),
  irrigationEvents: (plotId: string) => request<IrrigationEvent[]>(`/control/irrigation-events?plot_id=${plotId}`),
  storageLots: (clusterId: string) => request<StorageLot[]>(`/storage-lots?cluster_id=${clusterId}`),
  advisoryInteractions: (limit = 50) => request<AdvisoryInteraction[]>(`/advisory/interactions?limit=${limit}`),
  ledgerSummary: () => request<LedgerSummary>("/ledger/summary"),
  energyLogs: (clusterId: string) => request<any[]>(`/energy/arbitration-logs?cluster_id=${clusterId}`),
};
