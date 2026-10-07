import { useEffect, useState } from "react";
import { api, type LedgerSummary } from "../lib/api";

export default function LedgerPage() {
  const [summary, setSummary] = useState<LedgerSummary | null>(null);

  useEffect(() => {
    api.ledgerSummary().then(setSummary);
  }, []);

  return (
    <>
      <h2>Savings Verification Ledger</h2>
      <p style={{ color: "var(--dhara-muted)", marginTop: -8 }}>
        What a discom, carbon buyer, or PMKSY audit can check every claim against.
      </p>
      {!summary ? (
        <p className="loading">Loading...</p>
      ) : (
        <div className="card-grid">
          <div className="stat-card">
            <div className="value">{summary.entries}</div>
            <div className="label">Ledger periods closed</div>
          </div>
          <div className="stat-card">
            <div className="value">{summary.total_water_saved_m3.toLocaleString()}</div>
            <div className="label">m³ water saved vs. baseline</div>
          </div>
          <div className="stat-card">
            <div className="value">{summary.total_energy_saved_kwh.toLocaleString()}</div>
            <div className="label">kWh energy saved vs. baseline</div>
          </div>
          <div className="stat-card">
            <div className="value">{summary.total_avoided_tco2e.toFixed(2)}</div>
            <div className="label">tCO2e avoided</div>
          </div>
        </div>
      )}
    </>
  );
}
