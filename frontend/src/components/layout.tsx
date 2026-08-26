import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { cloudWardApi } from "../lib/api";
import type { Principal } from "../types";

const navigation = [
  { to: "/", label: "Overview", description: "Control plane", end: true },
  { to: "/incidents", label: "Incidents", description: "Evidence and decisions", end: false },
  { to: "/security", label: "Security", description: "Runtime detections", end: false },
  { to: "/finops", label: "FinOps", description: "Cost recommendations", end: false },
  { to: "/approvals", label: "Approvals", description: "Operator decisions", end: false },
  { to: "/clusters", label: "Clusters", description: "Connected inventory", end: false },
  { to: "/services", label: "Services", description: "Managed workloads", end: false },
  { to: "/audit", label: "Audit Log", description: "Control-plane record", end: false },
  { to: "/incident-lab", label: "Incident Lab", description: "Bounded scenarios", end: false },
  { to: "/settings", label: "Settings", description: "Integration status", end: false },
];

export function Layout() {
  const [principal, setPrincipal] = useState<Principal>();
  const [signingOut, setSigningOut] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const controller = new AbortController();
    cloudWardApi.currentUser(controller.signal).then(setPrincipal).catch(() => {
      if (!controller.signal.aborted) setPrincipal(undefined);
    });
    return () => controller.abort();
  }, []);

  async function signOut() {
    setSigningOut(true);
    try {
      await cloudWardApi.logout();
      navigate("/login", { replace: true });
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="CloudWard overview">
          <span className="brand__mark" aria-hidden="true">CW</span>
          <span><strong>CloudWard</strong><small>Reliability control plane</small></span>
        </Link>

        <nav className="primary-nav" aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
            >
              <span><strong>{item.label}</strong><small>{item.description}</small></span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__boundary">
          <span className="boundary-indicator" aria-hidden="true" />
          <div><strong>OPA policy boundary</strong><small>Every proposed action is evaluated before execution</small></div>
        </div>
        <div className="sidebar__environment"><span>Environment</span><strong>Local operations</strong></div>
      </aside>

      <div className="app-column">
        <header className="topbar">
          <Link to="/" className="mobile-brand">CloudWard</Link>
          <div className="session">
          {principal ? (
            <>
              <span className="session__identity">
                <strong>{principal.login}</strong>
                <small>{principal.role}</small>
              </span>
              <button type="button" className="button button--quiet" onClick={signOut} disabled={signingOut}>
                {signingOut ? "Signing out…" : "Sign out"}
              </button>
            </>
          ) : (
            <span className="session__identity"><strong>Session unavailable</strong><small>Authentication required</small></span>
          )}
          </div>
        </header>

        <main id="main-content" className="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
