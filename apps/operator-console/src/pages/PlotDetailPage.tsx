import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";

export default function PlotDetailPage() {
  const { plotId } = useParams<{ plotId: string }>();
  const [dashboard, setDashboard] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    if (!plotId) return;
    api.plotDashboard(plotId).then(setDashboard);
    api.irrigationEvents(plotId).then(setEvents);
  }, [plotId]);

  if (!dashboard) return <p className="loading">Loading plot...</p>;

  const { plot, active_crop_cycle, devices, latest_decision, seasonal_allocation_remaining_m3 } = dashboard;

  return (
    <>
      <h2>{plot.farmer_name}</h2>
      <p style={{ color: "var(--dhara-muted)", marginTop: -8 }}>
        {plot.area_ha} ha &middot; profile {plot.farmer_profile} &middot; {plot.farmer_phone_e164}
      </p>

      <div className="card-grid">
        <div className="stat-card">
          <div className="value">{active_crop_cycle ? active_crop_cycle.crop : "-"}</div>
          <div className="label">Active crop ({active_crop_cycle?.stage ?? "n/a"})</div>
        </div>
        <div className="stat-card">
          <div className="value">{latest_decision ? `${latest_decision.depth_mm} mm` : "-"}</div>
          <div className="label">Latest decision ({latest_decision?.reason_code ?? "n/a"})</div>
        </div>
        <div className="stat-card">
          <div className="value">{seasonal_allocation_remaining_m3.toFixed(1)} m³</div>
          <div className="label">Seasonal allocation remaining</div>
        </div>
      </div>

      <div className="section">
        <h3>Devices</h3>
        <table>
          <thead><tr><th>Hardware ID</th><th>Type</th><th>Health</th><th>Degradation</th><th>Battery (mV)</th><th>Last seen</th></tr></thead>
          <tbody>
            {devices.map((d: any) => (
              <tr key={d.id}>
                <td>{d.hardware_id}</td>
                <td>{d.device_type}</td>
                <td><span className={`badge ${d.health_state}`}>{d.health_state}</span></td>
                <td>{d.degradation_level}</td>
                <td>{d.battery_mv ?? "-"}</td>
                <td>{d.last_seen ? new Date(d.last_seen).toLocaleString() : "never"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section">
        <h3>Irrigation events</h3>
        {events.length === 0 ? (
          <p className="empty">No irrigation events yet.</p>
        ) : (
          <table>
            <thead><tr><th>Start</th><th>Volume (m³)</th><th>Energy (kWh)</th><th>Source</th><th>Verified</th></tr></thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.ts_start).toLocaleString()}</td>
                  <td>{e.volume_m3.toFixed(2)}</td>
                  <td>{e.energy_kwh.toFixed(2)}</td>
                  <td>{e.source}</td>
                  <td>
                    {e.verified ? (
                      <span className="badge resolved">verified {e.verification_delta_pct ?? 0}%</span>
                    ) : (
                      <span className="badge degraded">pending</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
