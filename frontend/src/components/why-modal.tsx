export interface WhyContext {
  title: string;
  verdict: string;
  verdictTone?: "good" | "warn" | "bad";
  reasons: string[];
  mitigations?: string[];
  ruleName?: string;
  finalScore?: string;
}

export function WhyModal({
  context,
  onClose,
}: {
  context: WhyContext | null;
  onClose: () => void;
}) {
  if (!context) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()} style={{ width: "min(100%, 480px)" }}>
        <div className="modal-dialog__header">
          <div>
            <span className="eyebrow">Explainability Engine</span>
            <h2>{context.title}</h2>
          </div>
          <button type="button" className="button button--quiet" onClick={onClose}>✕</button>
        </div>
        <div className="modal-dialog__body">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "14px", padding: "10px 14px", background: "var(--canvas)", border: "1px solid var(--line)", borderRadius: "6px" }}>
            <span style={{ fontSize: "12px", color: "var(--muted)" }}>Evaluated State</span>
            <strong style={{ fontSize: "13px", color: context.verdictTone === "bad" ? "var(--red)" : context.verdictTone === "warn" ? "var(--amber)" : "var(--green)" }}>
              {context.verdict}
            </strong>
          </div>

          <div style={{ marginBottom: "14px" }}>
            <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "8px" }}>
              Contributing Factors
            </div>
            <ul style={{ margin: 0, paddingLeft: "18px", color: "var(--ink-2)", fontSize: "12px", display: "grid", gap: "6px" }}>
              {context.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>

          {context.mitigations && context.mitigations.length > 0 ? (
            <div style={{ marginBottom: "14px" }}>
              <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "8px" }}>
                Risk Reducers & Mitigations
              </div>
              <ul style={{ margin: 0, paddingLeft: "18px", color: "var(--green)", fontSize: "12px", display: "grid", gap: "4px" }}>
                {context.mitigations.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {context.ruleName ? (
            <div style={{ padding: "8px 10px", background: "var(--canvas)", border: "1px solid var(--line)", borderRadius: "4px", fontSize: "11px", color: "var(--muted)" }}>
              <span style={{ color: "var(--faint)" }}>Policy rule: </span>
              <code style={{ color: "var(--signal)" }}>{context.ruleName}</code>
            </div>
          ) : null}

          {context.finalScore ? (
            <div style={{ marginTop: "12px", display: "flex", justifyContent: "space-between", alignItems: "baseline", borderTop: "1px solid var(--line)", paddingTop: "10px" }}>
              <span style={{ fontSize: "12px", color: "var(--muted)" }}>Calculated Risk Score</span>
              <strong style={{ fontFamily: "var(--mono)", fontSize: "1.2rem", color: "#fff" }}>
                {context.finalScore}
              </strong>
            </div>
          ) : null}
        </div>
        <div className="modal-dialog__footer">
          <button type="button" className="button button--secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
