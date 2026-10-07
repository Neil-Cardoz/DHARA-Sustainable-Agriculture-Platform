import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Plot } from "../lib/api";
import { useCluster } from "../lib/ClusterContext";

export default function PlotsPage() {
  const { clusterId } = useCluster();
  const [plots, setPlots] = useState<Plot[]>([]);

  useEffect(() => {
    if (!clusterId) return;
    api.plots(clusterId).then(setPlots);
  }, [clusterId]);

  return (
    <>
      <h2>Plots</h2>
      {plots.length === 0 ? (
        <p className="empty">No plots yet -- run the edge-simulator's provisioning script to seed demo farms.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Farmer</th>
              <th>Phone</th>
              <th>Area (ha)</th>
              <th>Profile</th>
              <th>Seasonal allocation used</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {plots.map((p) => (
              <tr key={p.id}>
                <td>{p.farmer_name}</td>
                <td>{p.farmer_phone_e164}</td>
                <td>{p.area_ha}</td>
                <td>{p.farmer_profile}</td>
                <td>
                  {p.seasonal_volumetric_used_m3.toFixed(1)} / {p.seasonal_volumetric_cap_m3} m³
                </td>
                <td><Link className="link" to={`/plots/${p.id}`}>View</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
