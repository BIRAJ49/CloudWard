import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

interface CommandItem {
  id: string;
  category: "Incidents" | "Services" | "Actions" | "Pages";
  title: string;
  subtitle?: string;
  to: string;
  action?: () => void;
}

const commandCatalog: CommandItem[] = [
  { id: "inc-1", category: "Incidents", title: "Open incident register", subtitle: "Evidence, decisions, and response", to: "/incidents" },
  { id: "srv-1", category: "Services", title: "Open reliability inventory", subtitle: "API-returned workload health", to: "/reliability" },
  { id: "act-1", category: "Actions", title: "Open Incident Lab", subtitle: "Launch controlled simulation", to: "/incident-lab" },
  { id: "act-2", category: "Actions", title: "Review approvals", subtitle: "Operator decision queue", to: "/approvals" },
  { id: "act-3", category: "Actions", title: "Inspect Audit Trail", subtitle: "Review chronological decision records", to: "/audit" },
  { id: "pg-1", category: "Pages", title: "Overview", subtitle: "Operations Command Center", to: "/" },
  { id: "pg-2", category: "Pages", title: "Reliability", subtitle: "Workload health & SLA tracking", to: "/reliability" },
  { id: "pg-3", category: "Pages", title: "Security Center", subtitle: "Runtime threats & quarantine", to: "/security" },
  { id: "pg-4", category: "Pages", title: "FinOps", subtitle: "Cloud costs & optimization", to: "/finops" },
  { id: "pg-5", category: "Pages", title: "Infrastructure", subtitle: "AWS / EKS / Karpenter nodes", to: "/infrastructure" },
  { id: "pg-6", category: "Pages", title: "Deployments / GitOps", subtitle: "Argo CD & rollout status", to: "/deployments" },
  { id: "pg-7", category: "Pages", title: "Observability", subtitle: "Prometheus, Loki, Tempo telemetry", to: "/observability" },
  { id: "pg-8", category: "Pages", title: "Settings", subtitle: "OPA policies & cluster connections", to: "/settings" },
];

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const navigate = useNavigate();

  const filtered = commandCatalog.filter(
    (item) =>
      item.title.toLowerCase().includes(query.toLowerCase()) ||
      (item.subtitle && item.subtitle.toLowerCase().includes(query.toLowerCase())) ||
      item.category.toLowerCase().includes(query.toLowerCase())
  );

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (!open) return;
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1 < filtered.length ? prev + 1 : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 >= 0 ? prev - 1 : filtered.length - 1));
      } else if (e.key === "Enter" && filtered[selectedIndex]) {
        e.preventDefault();
        const target = filtered[selectedIndex];
        onClose();
        if (target.action) target.action();
        else navigate(target.to);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, filtered, selectedIndex, onClose, navigate]);

  if (!open) return null;

  const categories = Array.from(new Set(filtered.map((item) => item.category)));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="command-palette" onClick={(e) => e.stopPropagation()}>
        <div className="command-palette__search">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--muted)" }}>
            <circle cx="11" cy="11" r="8"/>
            <path d="m21 21-4.3-4.3"/>
          </svg>
          <input
            autoFocus
            type="text"
            placeholder="Search CloudWard (incidents, services, actions, pages)..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
          />
          <kbd style={{ fontSize: "10px", color: "var(--faint)", background: "var(--surface)", padding: "2px 6px", borderRadius: "4px" }}>ESC</kbd>
        </div>
        <div className="command-palette__results">
          {filtered.length === 0 ? (
            <p style={{ padding: "16px", color: "var(--faint)", textAlign: "center", margin: 0 }}>
              No matches found for &ldquo;{query}&rdquo;
            </p>
          ) : (
            categories.map((cat) => {
              const catItems = filtered.filter((item) => item.category === cat);
              return (
                <div key={cat}>
                  <div className="command-palette__group-title">{cat}</div>
                  {catItems.map((item) => {
                    const globalIdx = filtered.indexOf(item);
                    return (
                      <div
                        key={item.id}
                        className={`command-palette__item ${globalIdx === selectedIndex ? "is-selected" : ""}`}
                        onClick={() => {
                          onClose();
                          if (item.action) item.action();
                          else navigate(item.to);
                        }}
                      >
                        <div>
                          <strong>{item.title}</strong>
                          {item.subtitle ? <small style={{ display: "block", color: "var(--muted)", fontSize: "11px" }}>{item.subtitle}</small> : null}
                        </div>
                        <span className="command-palette__item-badge">{item.category}</span>
                      </div>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
