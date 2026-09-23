import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/layout";
import { IncidentDetailPage } from "./pages/incident-detail";
import { IncidentsPage } from "./pages/incidents";
import { AuthCallbackPage, LoginPage } from "./pages/login";
import { NotFoundPage } from "./pages/not-found";
import { OverviewPage } from "./pages/overview";
import { IncidentLabPage } from "./pages/incident-lab";
import { SecurityPage } from "./pages/security";
import { ApprovalsPage } from "./pages/approvals";
import { AuditPage } from "./pages/audit";
import { ClustersPage } from "./pages/clusters";
import { FinOpsPage } from "./pages/finops";
import { ServicesPage } from "./pages/services";
import { SettingsPage } from "./pages/settings";
import { ObservabilityPage } from "./pages/observability";
import { DeploymentsPage } from "./pages/deployments";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route path="auth/callback" element={<AuthCallbackPage />} />
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="reliability" element={<ServicesPage />} />
        <Route path="services" element={<Navigate to="/reliability" replace />} />
        <Route path="security" element={<SecurityPage />} />
        <Route path="finops" element={<FinOpsPage />} />
        <Route path="infrastructure" element={<ClustersPage />} />
        <Route path="clusters" element={<Navigate to="/infrastructure" replace />} />
        <Route path="deployments" element={<DeploymentsPage />} />
        <Route path="gitops" element={<Navigate to="/deployments" replace />} />
        <Route path="observability" element={<ObservabilityPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="incident-lab" element={<IncidentLabPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
