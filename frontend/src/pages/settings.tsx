import { useEffect, useState } from "react";
import { ErrorNotice, LoadingPanel } from "../components/panel";
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
  if (loading) return <div className="page integration-settings"><LoadingPanel label="Loading settings" /></div>;
  return (
    <div className="page integration-settings">
      <header className="page-header integration-settings__masthead">
        <div><p className="eyebrow">Control-plane configuration</p><h1>Settings</h1><p>Read-only connection and access posture. Configuration remains with the server; secrets never enter this browser.</p></div>
        <span className="integration-settings__mode">Read-only view</span>
      </header>

      {state.failures.length ? <ErrorNotice title="Some integration status is unavailable" message={state.failures.join(", ")} /> : null}

      <div className="integration-settings__layout">
        <aside className="settings-identity" aria-labelledby="settings-identity-title">
          <p className="section-index">Current session</p>
          <h2 id="settings-identity-title">Access identity</h2>
          <dl>
            <div><dt>Login</dt><dd>{state.principal?.login ?? "Unavailable"}</dd></div>
            <div><dt>Role</dt><dd>{state.principal?.role ?? "Unavailable"}</dd></div>
            <div><dt>Approval access</dt><dd>{state.principal?.role === "Viewer" ? "Read only" : "Approve and reject within policy"}</dd></div>
          </dl>
        </aside>

        <main className="settings-register">
          <section className="settings-register__section" aria-labelledby="settings-connections-title">
            <header><div><p className="section-index">01 / Connections</p><h2 id="settings-connections-title">Server-side integrations</h2></div><p>Safe readiness metadata only</p></header>
            <div className="settings-connections"><Integration name="GitHub App" purpose="Source context and reviewed change proposals" value={state.github} /><Integration name="Microsoft Teams" purpose="Operator notifications and decision requests" value={state.teams} /></div>
          </section>

          <section className="settings-register__section" aria-labelledby="settings-boundaries-title">
            <header><div><p className="section-index">02 / Authority</p><h2 id="settings-boundaries-title">Execution boundaries</h2></div><p>Non-negotiable control-plane rules</p></header>
            <ol className="settings-rules"><li><span>01</span><p><strong>AI is advisory</strong>It may diagnose and recommend, but never execute.</p></li><li><span>02</span><p><strong>Policy is authoritative</strong>Risk scoring and OPA remain in the execution path.</p></li><li><span>03</span><p><strong>Production is reviewable</strong>Changes require an approved GitOps pull request.</p></li><li><span>04</span><p><strong>The lab stays in staging</strong>Only explicitly labeled demonstration targets are eligible.</p></li></ol>
          </section>

          <section className="settings-register__section" aria-labelledby="settings-secrets-title">
            <header><div><p className="section-index">03 / Data handling</p><h2 id="settings-secrets-title">Secret boundary</h2></div><p>Never exposed to the client</p></header>
            <dl className="settings-secret-register"><div><dt>OpenRouter credentials</dt><dd>Server-side only</dd></div><div><dt>GitHub App private key</dt><dd>Server-side only</dd></div><div><dt>Teams webhook URL</dt><dd>Server-side only</dd></div><div><dt>External evidence</dt><dd>Redacted before model or notifier calls</dd></div></dl>
          </section>
        </main>
      </div>
    </div>
  );
}

function Integration({ name, purpose, value }: { name: string; purpose: string; value?: IntegrationStatus }) {
  const status = String(value?.status ?? (value?.configured || value?.enabled ? "CONFIGURED" : "NOT_CONFIGURED"));
  return <article className="settings-connection"><div className="settings-connection__name"><span aria-hidden="true">↗</span><div><h3>{name}</h3><p>{purpose}</p></div></div><div className="settings-connection__status"><StatusBadge label={humanize(status)} tone={stateTone(status)} dot /><small>{value?.message ?? "Configuration is managed by the backend environment."}</small></div></article>;
}
