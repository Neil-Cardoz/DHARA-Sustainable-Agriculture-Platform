import { useEffect, useState } from "react";
import { api, type StorageLot } from "../lib/api";
import { useCluster } from "../lib/ClusterContext";

export default function StoragePage() {
  const { clusterId } = useCluster();
  const [lots, setLots] = useState<StorageLot[]>([]);

  useEffect(() => {
    if (!clusterId) return;
    api.storageLots(clusterId).then((ls) =>
      setLots([...ls].sort((a, b) => (a.predicted_shelf_life_hours ?? 999) - (b.predicted_shelf_life_hours ?? 999)))
    );
  }, [clusterId]);

  return (
    <>
      <h2>Cold Storage Dispatch Queue</h2>
      <p style={{ color: "var(--dhara-muted)", marginTop: -8 }}>
        Sorted by predicted remaining shelf life -- a lot that warmed during a door-open event moves to the top automatically.
      </p>
      {lots.length === 0 ? (
        <p className="empty">No active storage lots.</p>
      ) : (
        <table>
          <thead><tr><th>Crop</th><th>Mass (kg)</th><th>Intake</th><th>Predicted remaining life</th></tr></thead>
          <tbody>
            {lots.map((l) => (
              <tr key={l.id}>
                <td>{l.crop}</td>
                <td>{l.mass_kg}</td>
                <td>{new Date(l.intake_ts).toLocaleString()}</td>
                <td>
                  {l.predicted_shelf_life_hours != null ? (
                    <span className={`badge ${l.predicted_shelf_life_hours < 24 ? "fault" : l.predicted_shelf_life_hours < 72 ? "degraded" : "healthy"}`}>
                      {l.predicted_shelf_life_hours.toFixed(0)} h
                    </span>
                  ) : (
                    "-"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
