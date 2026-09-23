export interface ActionPreviewData {
  title: string;
  target: string;
  fromVersion?: string;
  toVersion?: string;
  expectedEffect: string;
  risk: "LOW" | "MEDIUM" | "HIGH";
  reversible: boolean;
  approvalRequired: boolean;
  rationale?: string;
}

export function ActionPreviewModal({
  preview,
  onConfirm,
  onCancel,
  loading,
}: {
  preview: ActionPreviewData | null;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}) {
  if (!preview) return null;

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-dialog__header">
          <div>
            <span className="eyebrow" style={{ color: "var(--amber)" }}>Governance Clearance</span>
            <h2>ACTION PREVIEW</h2>
          </div>
          <button type="button" className="button button--quiet" onClick={onCancel}>✕</button>
        </div>
        <div className="modal-dialog__body">
          <div style={{ marginBottom: "16px" }}>
            <h3 style={{ margin: "0 0 4px", fontSize: "1.1rem", color: "#fff" }}>
              {preview.title}
            </h3>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: "12px" }}>
              Autonomous remediation proposal staged by CloudWard. Review impact boundaries before execution.
            </p>
          </div>

          <div className="action-preview-table">
            <div className="action-preview-row">
              <strong>Target Workload</strong>
              <span>{preview.target}</span>
            </div>
            {preview.fromVersion ? (
              <div className="action-preview-row">
                <strong>Current Version</strong>
                <span style={{ color: "var(--red)" }}>{preview.fromVersion}</span>
              </div>
            ) : null}
            {preview.toVersion ? (
              <div className="action-preview-row">
                <strong>Target Version</strong>
                <span style={{ color: "var(--green)" }}>{preview.toVersion}</span>
              </div>
            ) : null}
            <div className="action-preview-row">
              <strong>Expected Effect</strong>
              <span>{preview.expectedEffect}</span>
            </div>
            <div className="action-preview-row">
              <strong>Calculated Risk</strong>
              <span style={{ color: preview.risk === "HIGH" ? "var(--red)" : preview.risk === "MEDIUM" ? "var(--amber)" : "var(--green)", fontWeight: 600 }}>
                {preview.risk}
              </span>
            </div>
            <div className="action-preview-row">
              <strong>Reversible</strong>
              <span style={{ color: "var(--green)" }}>
                {preview.reversible ? "✓ Yes" : "✕ No"}
              </span>
            </div>
            <div className="action-preview-row">
              <strong>Policy Approval</strong>
              <span style={{ color: "var(--amber)" }}>
                {preview.approvalRequired ? "Required by OPA policy" : "Automated"}
              </span>
            </div>
          </div>

          {preview.rationale ? (
            <div style={{ marginTop: "14px", padding: "10px 12px", background: "var(--canvas)", borderLeft: "3px solid var(--signal)", borderRadius: "4px", fontSize: "11.5px", color: "var(--muted)" }}>
              <strong style={{ color: "#fff", display: "block", marginBottom: "2px" }}>Operator Context</strong>
              {preview.rationale}
            </div>
          ) : null}
        </div>
        <div className="modal-dialog__footer">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={loading}>
            Cancel
          </button>
          <button type="button" className="button button--primary" onClick={onConfirm} disabled={loading} style={{ background: "var(--green)", borderColor: "var(--green)" }}>
            {loading ? "Executing via GitOps…" : "Review & Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}
