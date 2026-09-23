import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { cloudWardApi } from "../lib/api";
import { normalizedCheck } from "../lib/format";
import type { HealthResponse, Principal } from "../types";
import { CommandPalette } from "./command-palette";
import { Icon, type IconName } from "./icon";
import { SystemStatusModal } from "./system-status-modal";

const navigationGroups = [
  {
    label: "OPERATIONS",
    items: [
      { to: "/", label: "Overview", description: "Current operating picture", icon: "overview", end: true },
      { to: "/incidents", label: "Incidents", description: "Evidence and response", icon: "incidents", end: false },
      { to: "/approvals", label: "Approvals", description: "Operator review queue", icon: "approvals", end: false },
    ],
  },
  {
    label: "INTELLIGENCE",
    items: [
      { to: "/reliability", label: "Reliability", description: "Workload health", icon: "reliability", end: false },
      { to: "/security", label: "Security", description: "Runtime threat posture", icon: "security", end: false },
      { to: "/finops", label: "FinOps", description: "Cost and rightsizing", icon: "finops", end: false },
    ],
  },
  {
    label: "PLATFORM",
    items: [
      { to: "/infrastructure", label: "Infrastructure", description: "Nodes and capacity", icon: "infrastructure", end: false },
      { to: "/deployments", label: "Deployments", description: "GitOps delivery", icon: "deployments", end: false },
      { to: "/observability", label: "Observability", description: "Telemetry pipeline", icon: "observability", end: false },
    ],
  },
  {
    label: "GOVERNANCE",
    items: [
      { to: "/audit", label: "Audit log", description: "Immutable decision records", icon: "audit", end: false },
      { to: "/incident-lab", label: "Incident lab", description: "Controlled simulations", icon: "lab", end: false },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      { to: "/settings", label: "Settings", description: "Policies and integrations", icon: "settings", end: false },
    ],
  },
] satisfies ReadonlyArray<{ label: string; items: ReadonlyArray<{ to: string; label: string; description: string; icon: IconName; end: boolean }> }>;

function routeMatches(pathname: string, item: { to: string; end: boolean }) {
  return item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(`${item.to}/`);
}

export function Layout() {
  const [principal, setPrincipal] = useState<Principal>();
  const [shellHealth, setShellHealth] = useState<HealthResponse>();
  const [healthChecked, setHealthChecked] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [statusModalOpen, setStatusModalOpen] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try {
      const saved = localStorage.getItem("cloudward-theme");
      if (saved === "light" || saved === "dark") return saved;
      return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    } catch {
      return "dark";
    }
  });
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("cloudward-theme", theme);
    } catch {
      // Theme persistence is optional in restricted browser contexts.
    }
  }, [theme]);

  function toggleTheme() {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }

  const activeGroup = navigationGroups.find((group) =>
    group.items.some((item) => routeMatches(location.pathname, item))
  );
  const activeItem = activeGroup?.items.find((item) => routeMatches(location.pathname, item));

  useEffect(() => {
    const controller = new AbortController();
    cloudWardApi.currentUser(controller.signal).then(setPrincipal).catch(() => {
      if (!controller.signal.aborted) setPrincipal(undefined);
    });
    cloudWardApi.health(controller.signal)
      .then(setShellHealth)
      .catch(() => { if (!controller.signal.aborted) setShellHealth(undefined); })
      .finally(() => { if (!controller.signal.aborted) setHealthChecked(true); });
    return () => controller.abort();
  }, []);

  const healthState = normalizedCheck(shellHealth?.status ?? shellHealth?.healthy);
  const healthLabel = !healthChecked
    ? "Checking status"
    : healthState.tone === "good"
      ? "System healthy"
      : healthState.tone === "bad" || healthState.tone === "warn"
        ? "Needs attention"
        : "Status unavailable";

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
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
        <Link to="/" className="brand sidebar-brand" aria-label="CloudWard overview">
          <span className="sidebar-brand__mark" aria-hidden="true"><Icon name="shield" /></span>
          <span className="sidebar-brand__copy">
            <strong>CloudWard</strong>
            <small>Operations control</small>
          </span>
        </Link>

        <nav className="primary-nav" aria-label="Primary navigation">
          {navigationGroups.map((group) => (
            <section className="nav-group" aria-labelledby={`nav-${group.label.toLowerCase().replace(/\s+/g, "-")}`} key={group.label}>
              <h2 className="nav-label" id={`nav-${group.label.toLowerCase().replace(/\s+/g, "-")}`}>{group.label}</h2>
              <div className="nav-group__links">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
                  >
                    <span className="nav-link__icon" aria-hidden="true"><Icon name={item.icon} /></span>
                    <span className="nav-link__copy">
                      <strong>{item.label}</strong>
                      <small className="visually-hidden">{item.description}</small>
                    </span>
                  </NavLink>
                ))}
              </div>
            </section>
          ))}
        </nav>

        <div className="sidebar__footer">
          <button type="button" className="sidebar__environment" onClick={() => setStatusModalOpen(true)}>
            <span className={`sidebar__environment-icon sidebar__environment-icon--${healthState.tone}`}><Icon name="shield" /></span>
            <span><strong>Control plane</strong><small><i data-tone={healthState.tone} aria-hidden="true" />{healthLabel}</small></span>
          </button>
          <p>OPA policy enforced</p>
        </div>
      </aside>

      <div className="app-column">
        <header className="topbar">
          <div className="topbar__left">
            <Link to="/" className="mobile-brand" aria-label="CloudWard overview">CW</Link>
            <div className="topbar__context" aria-label="Current location">
              <span>{activeGroup?.label ?? "Operations"}</span>
              <strong>{activeItem?.label ?? "Overview"}</strong>
            </div>
          </div>

          <button
            type="button"
            className="topbar__search-trigger"
            onClick={() => setPaletteOpen(true)}
            aria-label="Open command palette"
          >
            <Icon name="search" />
            <span>Search or jump to…</span>
            <kbd>⌘K</kbd>
          </button>

          <div className="topbar__utilities">
            <button
              type="button"
              className="theme-toggle-btn"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? (
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="4"/>
                  <path d="M12 2v2"/>
                  <path d="M12 20v2"/>
                  <path d="m4.93 4.93 1.41 1.41"/>
                  <path d="m17.66 17.66 1.41 1.41"/>
                  <path d="M2 12h2"/>
                  <path d="M20 12h2"/>
                  <path d="m6.34 17.66-1.41 1.41"/>
                  <path d="m19.07 4.93-1.41 1.41"/>
                </svg>
              ) : (
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
                </svg>
              )}
            </button>

            <button
              type="button"
              className="topbar__status-pill"
              data-tone={healthState.tone}
              onClick={() => setStatusModalOpen(true)}
              title="Click to view detailed system health"
            >
              <span className={`health-dot health-dot--${healthState.tone}`} aria-hidden="true" />
              <span>{healthLabel}</span>
            </button>

            <div className="session">
              {principal ? (
                <>
                  <span className="session__identity">
                    <span className="session__avatar" aria-hidden="true">{principal.login.slice(0, 1).toUpperCase()}</span>
                    <span><strong>{principal.login}</strong><small>{principal.role}</small></span>
                  </span>
                  <button type="button" className="button button--quiet session__signout" onClick={signOut} disabled={signingOut}>
                    {signingOut ? "Signing out…" : "Sign out"}
                  </button>
                </>
              ) : (
                <span className="session__identity session__identity--unavailable"><strong>Guest</strong><small>Viewer</small></span>
              )}
            </div>
          </div>
        </header>

        <main id="main-content" className="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <SystemStatusModal open={statusModalOpen} onClose={() => setStatusModalOpen(false)} />
    </div>
  );
}
