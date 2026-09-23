import { useEffect, useMemo, useState } from "react";
import { cloudWardApi } from "../lib/api";
import { humanize, normalizedCheck } from "../lib/format";
import type { HealthResponse, Tone } from "../types";

export function SystemStatusModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [health, setHealth] = useState<HealthResponse>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    cloudWardApi.health(controller.signal)
      .then((value) => { setHealth(value); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) { setHealth(undefined); setFailed(true); } })
    return () => controller.abort();
  }, [open]);

  const subsystems = useMemo(() => {
    const checks = health?.dependencies ?? health?.checks ?? {};
    return Object.entries(checks).map(([name, value]) => {
      const status = normalizedCheck(value);
      const latency = value && typeof value === "object" && "latency_ms" in value && typeof value.latency_ms === "number"
        ? `${value.latency_ms.toFixed(1)} ms`
        : undefined;
      return { name: humanize(name), ...status, latency };
    });
  }, [health]);

  const apiState = normalizedCheck(health?.status ?? health?.healthy);
  const overallTone: Tone = failed ? "neutral" : apiState.tone;
  const loading = !health && !failed;
  const overallLabel = loading ? "Checking current evidence" : failed ? "Status unavailable" : apiState.label;
  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()} style={{ width: "min(100%, 640px)" }}>
        <div className="modal-dialog__header">
          <div>
            <h2 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span className={`health-dot health-dot--${overallTone}`} />
              CloudWard System Status
            </h2>
            <p style={{ margin: "2px 0 0", color: "var(--muted)", fontSize: "11.5px" }}>
              {overallLabel}. Only dependencies returned by the readiness API are shown.
            </p>
          </div>
          <button type="button" className="button button--quiet" onClick={onClose}>✕</button>
        </div>
        <div className="modal-dialog__body">
          <div className="system-status-grid">
            {subsystems.map((sub) => (
              <div key={sub.name} className="system-status-item">
                <div>
                  <strong>{sub.name}</strong>
                  <div style={{ color: "var(--faint)", fontSize: "10px", marginTop: "1px" }}>
                    Readiness dependency{sub.latency ? ` · ${sub.latency}` : ""}
                  </div>
                </div>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <span className={`health-dot health-dot--${sub.tone}`} />
                  <small data-tone={sub.tone} style={{ fontSize: "11px", fontWeight: 500 }}>{sub.label}</small>
                </span>
              </div>
            ))}
            {!loading && !subsystems.length ? <p className="quiet-copy">No dependency checks were returned.</p> : null}
          </div>
        </div>
        <div className="modal-dialog__footer">
          <span style={{ fontSize: "11px", color: "var(--faint)", marginRight: "auto" }}>
            Refreshed when this panel is opened
          </span>
          <button type="button" className="button button--secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
