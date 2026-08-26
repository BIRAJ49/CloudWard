import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
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
        <div className="login-brand"><span className="brand__mark" aria-hidden="true">CW</span><span><strong>CloudWard</strong><small>Reliability control plane</small></span></div>
        <div>
          <p className="eyebrow">Operator access</p>
          <h1>Sign in to the control plane</h1>
          <p>Inspect incident evidence and policy-bounded remediation records.</p>
        </div>
        <ul className="login-principles">
          <li><strong>Deterministic runbooks</strong><span>No arbitrary command execution</span></li>
          <li><strong>OPA authorization</strong><span>Policy remains the final authority</span></li>
          <li><strong>Verified outcomes</strong><span>Every decision and action is audited</span></li>
        </ul>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-panel__body">
          <p className="eyebrow">CloudWard access</p>
          <h2 id="login-title">Continue with GitHub</h2>
          <p>GitHub establishes your identity. CloudWard applies the assigned Viewer, Operator, or Admin role to each request.</p>

          {error ? <ErrorNotice title="Sign-in failed" message={error} /> : null}

          <a className="button button--primary button--full" href={`${API_BASE_URL}/auth/github/login`}>
            Continue with GitHub
          </a>

          {developmentLoginEnabled ? (
            <div className="dev-login">
              <div className="dev-login__header"><strong>Development access</strong><span>Local environment only</span></div>
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

          <p className="login-footnote">Authentication establishes identity. Backend RBAC authorizes every operation.</p>
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
        <span className="brand__mark" aria-hidden="true">CW</span>
        <p className="eyebrow">GitHub authentication</p>
        <h1>Session established</h1>
        <p>Your identity has been accepted. Authorization remains enforced on every control-plane request.</p>
        <a className="button button--primary" href="/">Open overview</a>
      </section>
    </main>
  );
}
