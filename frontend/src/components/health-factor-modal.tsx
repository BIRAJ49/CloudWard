import { Link } from "react-router-dom";

export type HealthCategory = "reliability" | "security" | "finops" | "automation";

interface FactorDetail {
  title: string;
  score: string;
  delta?: string;
  summary: string;
  factors: Array<{ status: "good" | "warn" | "bad"; text: string }>;
  evidenceLink: string;
  evidenceLabel: string;
}

const factorData: Record<HealthCategory, FactorDetail> = {
  reliability: {
    title: "Reliability Health Score",
    score: "98.7 / 100",
    delta: "↑ 2.4% this week",
    summary: "Evaluated from synthetic latency probes, service error budgets, and MTTR across 12 monitored workloads.",
    factors: [
      { status: "good", text: "No unresolved critical incidents" },
      { status: "good", text: "Global error rate below 0.1% threshold" },
      { status: "good", text: "99.96% overall multi-zone availability" },
      { status: "good", text: "Zero failed remediation workflows" },
      { status: "warn", text: "2 deployment warnings pending canary validation" },
    ],
    evidenceLink: "/reliability",
    evidenceLabel: "View Reliability Evidence",
  },
  security: {
    title: "Security Threat Posture",
    score: "100 / 100",
    delta: "Zero active threats",
    summary: "Continuously audited via Tetragon eBPF process sensors and Cilium network containment policies.",
    factors: [
      { status: "good", text: "Zero active uncontained threats" },
      { status: "good", text: "Tetragon kernel tracing sensor active on all nodes" },
      { status: "good", text: "Zero privilege escalation events in the last 24h" },
      { status: "good", text: "Cilium L7 egress network enforcement active" },
      { status: "good", text: "All container image digests signed & verified" },
    ],
    evidenceLink: "/security",
    evidenceLabel: "Open Security Center",
  },
  finops: {
    title: "FinOps Cost Efficiency",
    score: "$184 / month",
    delta: "↓ 8.2% cost reduction",
    summary: "CloudWard correlates Karpenter node allocation, OpenCost usage telemetry, and provisioned vs consumed CPU.",
    factors: [
      { status: "good", text: "7 rightsizing opportunities identified ($32/mo savings)" },
      { status: "good", text: "Karpenter consolidated 2 underutilized nodes" },
      { status: "good", text: "Spot instance coverage optimal at 33%" },
      { status: "warn", text: "staging/api idle resource headroom exceeds 50%" },
    ],
    evidenceLink: "/finops",
    evidenceLabel: "Inspect FinOps Ledger",
  },
  automation: {
    title: "Autonomous Action Reliability",
    score: "94% Success Rate",
    delta: "23 total automated actions",
    summary: "Tracking the accuracy and safety of CloudWard automated remediations, scale events, and policy actions.",
    factors: [
      { status: "good", text: "23 autonomous actions successfully completed" },
      { status: "good", text: "Zero automated regressions or unintended restarts" },
      { status: "good", text: "100% OPA policy decision verification before execution" },
      { status: "warn", text: "1 manual rollback required human operator approval" },
    ],
    evidenceLink: "/approvals",
    evidenceLabel: "Review Action Docket",
  },
};

export function HealthFactorModal({
  category,
  onClose,
}: {
  category: HealthCategory | null;
  onClose: () => void;
}) {
  if (!category) return null;
  const data = factorData[category];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-dialog__header">
          <div>
            <span className="eyebrow">Explainable Health Score</span>
            <h2>{data.title}</h2>
          </div>
          <button type="button" className="button button--quiet" onClick={onClose}>✕</button>
        </div>
        <div className="modal-dialog__body">
          <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "8px" }}>
            <span style={{ fontSize: "2rem", fontWeight: 700, fontFamily: "var(--mono)", color: "#fff" }}>
              {data.score}
            </span>
            {data.delta ? (
              <span style={{ fontSize: "11.5px", color: "var(--signal)", fontWeight: 500 }}>
                {data.delta}
              </span>
            ) : null}
          </div>
          <p style={{ margin: "0 0 16px", color: "var(--muted)", fontSize: "12px" }}>
            {data.summary}
          </p>

          <div style={{ borderTop: "1px solid var(--line)", paddingTop: "14px" }}>
            <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "10px" }}>
              Contributing Factors
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: "8px" }}>
              {data.factors.map((f, i) => (
                <li
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    padding: "8px 10px",
                    background: "var(--canvas)",
                    border: "1px solid var(--line)",
                    borderRadius: "6px",
                    fontSize: "12px",
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontWeight: 700,
                      color: f.status === "good" ? "var(--green)" : f.status === "warn" ? "var(--amber)" : "var(--red)",
                    }}
                  >
                    {f.status === "good" ? "✓" : f.status === "warn" ? "△" : "✕"}
                  </span>
                  <span style={{ color: "var(--ink)" }}>{f.text}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="modal-dialog__footer">
          <button type="button" className="button button--secondary" onClick={onClose}>
            Dismiss
          </button>
          <Link to={data.evidenceLink} className="button button--primary" onClick={onClose}>
            {data.evidenceLabel} →
          </Link>
        </div>
      </div>
    </div>
  );
}
