import { NavLink, Route, Routes } from "react-router-dom";
import { ClusterProvider, useCluster } from "./lib/ClusterContext";
import DashboardPage from "./pages/DashboardPage";
import PlotsPage from "./pages/PlotsPage";
import PlotDetailPage from "./pages/PlotDetailPage";
import StoragePage from "./pages/StoragePage";
import AdvisoryPage from "./pages/AdvisoryPage";
import LedgerPage from "./pages/LedgerPage";
import EnergyPage from "./pages/EnergyPage";

function ClusterSwitcher() {
  const { clusters, clusterId, setClusterId } = useCluster();
  if (clusters.length <= 1) return null;
  return (
    <select value={clusterId ?? ""} onChange={(e) => setClusterId(e.target.value)} style={{ marginBottom: 16, padding: 6 }}>
      {clusters.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

export default function App() {
  return (
    <ClusterProvider>
      <div className="app-shell">
        <aside className="sidebar">
          <h1>DHARA</h1>
          <p>Operator Console</p>
          <nav>
            <NavLink to="/" end>Dashboard</NavLink>
            <NavLink to="/plots">Plots</NavLink>
            <NavLink to="/storage">Cold Storage</NavLink>
            <NavLink to="/energy">Energy</NavLink>
            <NavLink to="/advisory">Advisory Log</NavLink>
            <NavLink to="/ledger">Savings Ledger</NavLink>
          </nav>
        </aside>
        <main className="main-content">
          <ClusterSwitcher />
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/plots" element={<PlotsPage />} />
            <Route path="/plots/:plotId" element={<PlotDetailPage />} />
            <Route path="/storage" element={<StoragePage />} />
            <Route path="/energy" element={<EnergyPage />} />
            <Route path="/advisory" element={<AdvisoryPage />} />
            <Route path="/ledger" element={<LedgerPage />} />
          </Routes>
        </main>
      </div>
    </ClusterProvider>
  );
}
