import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useCluster } from "../lib/ClusterContext";

export default function DashboardPage() {
  const { clusterId } = useCluster();
  const [summary, setSummary] = useState<any>(null);

  useEffect(() => {
    if (!clusterId) return;
    api.clusterSummary(clusterId).then(setSummary);
  }, [clusterId]);

  if (!clusterId) return <p className="loading">Loading clusters...</p>;
  if (!summary) return <p className="loading">Loading cluster summary...</p>;

  return (
    <>
      <h2>{summary.cluster.name}</h2>
      <p style={{ color: "var(--dhara-muted)", marginTop: -8 }}>
        {summary.cluster.district}, {summary.cluster.state}
      </p>

      <div className="card-grid">
        <div className="stat-card">
          <div className="value">{summary.plot_count}</div>
          <div className="label">Farms in cluster</div>
        </div>
        <div className="stat-card">
          <div className="value">{summary.device_count}</div>
          <div className="label">Registered devices</div>
        </div>
        <div className="stat-card">
          <div className="value">{summary.cold_room_utilisation_pct}%</div>
          <div className="label">Cold room utilisation ({summary.cold_room_occupied_kg} / {summary.cold_room_capacity_kg} kg)</div>
        </div>
        <div className="stat-card">
          <div className="value">{summary.device_health.healthy ?? 0}</div>
          <div className="label">Healthy devices</div>
        </div>
      </div>

      <div className="section">
        <h3>Device health breakdown</h3>
        <table>
          <thead>
            <tr><th>State</th><th>Count</th></tr>
          </thead>
          <tbody>
            {Object.entries(summary.device_health).map(([state, count]) => (
              <tr key={state}>
                <td><span className={`badge ${state}`}>{state}</span></td>
                <td>{count as number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
