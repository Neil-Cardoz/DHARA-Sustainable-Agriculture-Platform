import { useEffect, useState } from "react";
import { api, type AdvisoryInteraction } from "../lib/api";

export default function AdvisoryPage() {
  const [interactions, setInteractions] = useState<AdvisoryInteraction[]>([]);

  useEffect(() => {
    api.advisoryInteractions(100).then(setInteractions);
  }, []);

  return (
    <>
      <h2>Advisory Interaction Log</h2>
      <p style={{ color: "var(--dhara-muted)", marginTop: -8 }}>
        Every WhatsApp, voice, and lamp exchange -- confidence and escalations included, for the audit trail.
      </p>
      {interactions.length === 0 ? (
        <p className="empty">No advisory interactions logged yet.</p>
      ) : (
        <table>
          <thead><tr><th>Time</th><th>Channel</th><th>Direction</th><th>Question / Prompt</th><th>Response</th><th>Confidence</th><th>Status</th></tr></thead>
          <tbody>
            {interactions.map((i) => (
              <tr key={i.id}>
                <td>{new Date(i.ts).toLocaleString()}</td>
                <td>{i.channel}</td>
                <td>{i.direction}</td>
                <td>{i.input_text ?? "-"}</td>
                <td>{i.response_text ?? "-"}</td>
                <td>{i.confidence != null ? i.confidence.toFixed(2) : "-"}</td>
                <td>
                  {i.escalated_to_human ? (
                    <span className="badge escalated">escalated</span>
                  ) : (
                    <span className="badge resolved">answered</span>
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
