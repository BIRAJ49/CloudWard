import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/use-document-title";

export function NotFoundPage() {
  useDocumentTitle("Not found");
  return (
    <div className="not-found">
      <div className="not-found__code" aria-hidden="true">404</div>
      <div className="not-found__copy">
        <p className="eyebrow">Route not found</p>
        <h1>No operational view exists at this address.</h1>
        <p>The route may have moved, or your access link may be incomplete.</p>
        <div className="not-found__actions">
          <Link className="button button--primary" to="/">Return to overview</Link>
          <Link className="button button--quiet" to="/incidents">Open incident register</Link>
        </div>
      </div>
    </div>
  );
}
