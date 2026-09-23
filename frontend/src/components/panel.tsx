import type { ReactNode } from "react";

interface PanelProps {
  title?: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  description?: string;
}

export function Panel({ title, eyebrow, action, children, className = "", description }: PanelProps) {
  return (
    <section className={`panel ${className}`}>
      {title || eyebrow || action ? (
        <header className="panel__header">
          <div className="panel__heading">
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            {title ? <h2>{title}</h2> : null}
            {description ? <p className="panel__description">{description}</p> : null}
          </div>
          {action ? <div className="panel__actions">{action}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__marker" aria-hidden="true" />
      <div className="empty-state__copy"><strong>{title}</strong><p>{detail}</p></div>
    </div>
  );
}

export function LoadingPanel({ label = "Loading operational data" }: { label?: string }) {
  return (
    <div className="loading-panel" role="status">
      <span className="loading-panel__rule" aria-hidden="true" />
      <span className="loading-panel__label">{label}</span>
    </div>
  );
}

export function ErrorNotice({
  title = "Control plane unavailable",
  message,
  retry,
}: {
  title?: string;
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-notice" role="alert">
      <span className="error-notice__mark" aria-hidden="true">!</span>
      <div className="error-notice__copy">
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      {retry ? (
        <button type="button" className="button button--secondary" onClick={retry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
