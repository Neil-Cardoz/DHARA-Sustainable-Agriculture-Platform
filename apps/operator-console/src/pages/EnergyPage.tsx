import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useCluster } from "../lib/ClusterContext";

export default function EnergyPage() {
  const { clusterId } = useCluster();
  const [logs, setLogs] = useState<any[]>([]);

  useEffect(() => {
    if (!clusterId) return;
    api.energyLogs(clusterId).then(setLogs);
  }, [clusterId]);

  return (
    <>
      <h2>Energy Arbitration</h2>
      <p style={{ color: "var(--dhara-muted)", marginTop: -8 }}>
        The six-step solar priority order: crop-critical irrigation, cold-room pulldown, tank fill (capped), thermal
        store, battery, grid export.
      </p>
      {logs.length === 0 ? (
        <p className="empty">No arbitration runs logged yet.</p>
      ) : (
        <table>
          <thead><tr><th>Time</th><th>Available solar (kWh)</th><th>Exported (kWh)</th><th>Unallocated (kWh)</th></tr></thead>
          <tbody>
            {logs.map((log) => (
              <tr key={log.id}>
                <td>{new Date(log.ts).toLocaleString()}</td>
                <td>{log.available_solar_kwh}</td>
                <td>{log.exported_to_feeder_kwh}</td>
                <td>{log.unallocated_kwh}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
