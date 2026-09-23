import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowFillButton } from "../components/obsidian/arrow-fill-button";
import { DottedGrid } from "../components/obsidian/dotted-grid";
import { ErrorNotice } from "../components/panel";
import { useDocumentTitle } from "../hooks/use-document-title";
import { API_BASE_URL, cloudWardApi } from "../lib/api";
import type { Principal } from "../types";

export function LoginPage() {
  useDocumentTitle("Sign in");
  const navigate = useNavigate();
  const location = useLocation();
  const destination = (location.state as { from?: string } | null)?.from ?? "/";
  const [login, setLogin] = useState("local-operator");
  const [role, setRole] = useState<Principal["role"]>("Operator");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const developmentLoginEnabled = import.meta.env.VITE_DEV_LOGIN_ENABLED === "true";

  async function submitDevelopmentLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    try {
      await cloudWardApi.developmentLogin(login, role);
      navigate(destination, { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Development login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-context">
        <DottedGrid className="login-context__grid" />
        <div className="login-context__veil" aria-hidden="true" />
        <div className="login-brand">
          <span className="brand__mark" aria-hidden="true"><span>C</span><i /><span>W</span></span>
          <span className="brand__lockup"><strong>CloudWard</strong><small>Reliability operations</small></span>
        </div>
        <div className="login-context__statement">
          <p className="eyebrow">Operator console · Local</p>
          <h1>Know what changed.<br />Know who approved it.</h1>
          <p>CloudWard keeps incident evidence, policy decisions, and remediation outcomes in one accountable record.</p>
        </div>
        <dl className="login-register" aria-label="CloudWard control boundaries">
          <div><dt>Execution</dt><dd>Allowlisted runbooks only</dd></div>
          <div><dt>Authority</dt><dd>OPA policy and role controls</dd></div>
          <div><dt>Record</dt><dd>Evidence retained end to end</dd></div>
        </dl>
        <p className="login-context__edition">CloudWard / Local operator edition</p>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-panel__body">
          <header className="login-panel__header">
            <span className="login-panel__index" aria-hidden="true">01</span>
            <div><p className="eyebrow">Identity</p><h2 id="login-title">Continue with GitHub</h2></div>
          </header>
          <p className="login-panel__intro">Use your GitHub identity. Access is limited by the CloudWard role assigned to your account.</p>

          {error ? <ErrorNotice title="Sign-in failed" message={error} /> : null}

          <ArrowFillButton className="obsidian-arrow-button--full" href={`${API_BASE_URL}/auth/github/login`}>
            Continue with GitHub
          </ArrowFillButton>

          {developmentLoginEnabled ? (
            <div className="dev-login">
              <div className="dev-login__header"><strong>Development access</strong><span>Local only</span></div>
              <form onSubmit={submitDevelopmentLogin}>
                <label className="field">
                  <span>Local identity</span>
                  <input required pattern="[A-Za-z0-9-]+" maxLength={255} value={login} onChange={(event) => setLogin(event.target.value)} />
                </label>
                <label className="field">
                  <span>Role</span>
                  <select value={role} onChange={(event) => setRole(event.target.value as Principal["role"])}>
                    <option value="Viewer">Viewer</option>
                    <option value="Operator">Operator</option>
                    <option value="Admin">Admin</option>
                  </select>
                </label>
                <button className="button button--secondary button--full" type="submit" disabled={submitting}>
                  {submitting ? "Signing in…" : "Use development identity"}
                </button>
              </form>
            </div>
          ) : null}

          <p className="login-footnote"><span aria-hidden="true">■</span> Authentication identifies you; server-side RBAC authorizes each operation.</p>
        </div>
      </section>
    </main>
  );
}

export function AuthCallbackPage() {
  useDocumentTitle("Authentication complete");
  return (
    <main className="callback-page">
      <section className="callback-card">
        <header className="callback-card__brand"><span className="brand__mark" aria-hidden="true"><span>C</span><i /><span>W</span></span><strong>CloudWard</strong></header>
        <div className="callback-card__body">
          <p className="eyebrow">GitHub authentication</p>
          <h1>Session established</h1>
          <p>Your identity is confirmed. CloudWard will still authorize every control-plane request against your assigned role.</p>
          <a className="button button--primary" href="/"><span>Open overview</span><span aria-hidden="true">→</span></a>
        </div>
      </section>
    </main>
  );
}
