import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/use-document-title";

export function NotFoundPage() {
  useDocumentTitle("Not found");
  return (
    <div className="not-found">
      <p className="eyebrow">404 · Route not found</p>
      <h1>This operational view does not exist.</h1>
      <p>Return to the control-plane overview or inspect the incident register.</p>
      <Link className="button button--primary" to="/">Return to overview</Link>
    </div>
  );
}
