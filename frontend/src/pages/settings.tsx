import { useEffect, useState } from "react";
import { ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { humanize, stateTone } from "../lib/format";
import type { IntegrationStatus, Principal } from "../types";

interface SettingsState { principal?: Principal; github?: IntegrationStatus; teams?: IntegrationStatus; failures: string[]; }

export function SettingsPage() {
  useDocumentTitle("Settings");
  const [state, setState] = useState<SettingsState>({ failures: [] });
  const [loading, setLoading] = useState(true);
  useEffect(() => { const controller = new AbortController(); Promise.allSettled([cloudWardApi.currentUser(controller.signal), cloudWardApi.githubIntegration(controller.signal), cloudWardApi.teamsIntegration(controller.signal)]).then(([principal, github, teams]) => { if (controller.signal.aborted) return; const failures: string[] = []; if (github.status === "rejected") failures.push("GitHub App status"); if (teams.status === "rejected") failures.push("Microsoft Teams status"); setState({ principal: principal.status === "fulfilled" ? principal.value : undefined, github: github.status === "fulfilled" ? github.value : undefined, teams: teams.status === "fulfilled" ? teams.value : undefined, failures }); setLoading(false); }); return () => controller.abort(); }, []);
  if (loading) return <div className="page"><LoadingPanel label="Loading settings" /></div>;
  return <div className="page"><header className="page-header"><div><p className="eyebrow">Control-plane configuration</p><h1>Settings</h1><p>Read-only integration and session status. Secret values never enter the browser.</p></div></header>{state.failures.length ? <ErrorNotice title="Some integration status is unavailable" message={state.failures.join(", ")} /> : null}<div className="settings-grid"><Panel title="Session and access"><dl className="fact-list settings-facts"><div><dt>Login</dt><dd>{state.principal?.login ?? "Unavailable"}</dd></div><div><dt>Role</dt><dd>{state.principal?.role ?? "Unavailable"}</dd></div><div><dt>Approval access</dt><dd>{state.principal?.role === "Viewer" ? "Read only" : "Approve and reject within policy"}</dd></div></dl></Panel><Panel title="Server-side integrations" description="Only safe readiness metadata is returned."><Integration name="GitHub App" value={state.github} /><Integration name="Microsoft Teams" value={state.teams} /></Panel><Panel title="Execution boundaries"><ul className="settings-list"><li>AI may diagnose and recommend, but never execute.</li><li>Risk and OPA remain authoritative.</li><li>Production changes require an approved GitOps pull request.</li><li>Incident Lab is fixed to labeled staging targets.</li></ul></Panel><Panel title="Secret handling"><ul className="settings-list"><li>OpenRouter keys remain server-side.</li><li>GitHub App private keys remain server-side.</li><li>Teams webhook URLs remain server-side.</li><li>Evidence is redacted before external model or notifier calls.</li></ul></Panel></div></div>;
}

function Integration({ name, value }: { name: string; value?: IntegrationStatus }) { const status = String(value?.status ?? (value?.configured || value?.enabled ? "CONFIGURED" : "NOT_CONFIGURED")); return <div className="integration-row"><div><strong>{name}</strong><small>{value?.message ?? "Configuration is managed by the backend environment."}</small></div><StatusBadge label={humanize(status)} tone={stateTone(status)} dot /></div>; }
