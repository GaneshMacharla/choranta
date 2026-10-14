import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { AppLayout } from './components/layout/AppLayout';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { OverviewPage } from './pages/OverviewPage';
import { ClientsPage } from './pages/ClientsPage';
import { ClientDetailPage } from './pages/ClientDetailPage';
import { AgentsPage } from './pages/AgentsPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { AgentCreateWizardPage } from './pages/AgentCreateWizardPage';
import { TelephonyPage } from './pages/TelephonyPage';
import { CallsPage } from './pages/CallsPage';
import { ToolsPage } from './pages/ToolsPage';
import { IntegrationsPage } from './pages/IntegrationsPage';
import { ProvidersPage } from './pages/ProvidersPage';
import { UsagePage } from './pages/UsagePage';
import { PlansPage } from './pages/PlansPage';
import { CampaignsPage, CampaignDetailPage, InstantOutboundPage, InstantOutboundDetailPage } from './pages/CampaignsPage';
import { AgentRequestsPage } from './pages/AgentRequestsPage';
import { VerificationsPage } from './pages/VerificationsPage';
import { PortalVerificationPage } from './pages/portal/PortalVerificationPage';
import { PortalEmployeesPage } from './pages/portal/PortalEmployeesPage';
import { LogsPage } from './pages/LogsPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { PortalLayout } from './components/portal/PortalLayout';
import { PortalDashboardPage } from './pages/portal/PortalDashboardPage';
import { PortalCallsPage } from './pages/portal/PortalCallsPage';
import { PortalBillingPage } from './pages/portal/PortalBillingPage';
import { PortalInventoryPage } from './pages/portal/PortalInventoryPage';
import { PortalCoursesPage } from './pages/portal/PortalCoursesPage';
import { PortalNumbersPage } from './pages/portal/PortalNumbersPage';
import { PortalPlansPage } from './pages/portal/PortalPlansPage';
import {
  PortalCampaignsPage,
  PortalCampaignDetailPage,
  PortalInstantOutboundPage,
  PortalInstantOutboundDetailPage,
} from './pages/portal/PortalCampaignsPage';
import { PortalIntegrationsPage } from './pages/portal/PortalIntegrationsPage';

/** Old Test Lab links open the agent's Tests step (or the AI Employees list). */
function TestLabRedirect() {
  const [searchParams] = useSearchParams();
  const agentId = searchParams.get('agentId');
  return <Navigate to={agentId ? `/agents/${agentId}?tab=tests` : '/agents'} replace />;
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            {/* Public Landing & Marketing */}
            <Route path="/" element={<LandingPage />} />
            <Route path="/landing" element={<LandingPage />} />

            {/* Public Login Route */}
            <Route path="/login" element={<LoginPage />} />

            {/* Client portal (CLIENT accounts only) */}
            <Route path="/portal" element={<PortalLayout />}>
              <Route index element={<PortalDashboardPage />} />
              <Route path="calls" element={<PortalCallsPage />} />
              <Route path="employees" element={<PortalEmployeesPage />} />
              <Route path="verification" element={<PortalVerificationPage />} />
              <Route path="campaigns" element={<PortalCampaignsPage />} />
              <Route path="campaigns/:id" element={<PortalCampaignDetailPage />} />
              <Route path="instant-outbound" element={<PortalInstantOutboundPage />} />
              <Route path="instant-outbound/:id" element={<PortalInstantOutboundDetailPage />} />
              <Route path="integrations" element={<PortalIntegrationsPage />} />
              <Route path="plans" element={<PortalPlansPage />} />
              <Route path="numbers" element={<PortalNumbersPage />} />
              <Route path="billing" element={<PortalBillingPage />} />
              <Route path="inventory" element={<PortalInventoryPage />} />
              <Route path="courses" element={<PortalCoursesPage />} />
            </Route>

            {/* Protected Internal Routes */}
            <Route element={<AppLayout />}>
              <Route path="/overview" element={<OverviewPage />} />
              <Route path="/dashboard" element={<Navigate to="/overview" replace />} />
              <Route path="/clients" element={<ClientsPage />} />
              <Route path="/clients/:id" element={<ClientDetailPage />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/agents/new" element={<AgentCreateWizardPage />} />
              <Route path="/agent-requests" element={<AgentRequestsPage />} />
              <Route path="/verifications" element={<VerificationsPage />} />
              <Route path="/agents/:id" element={<AgentDetailPage />} />
              {/* Testing now lives in each AI Employee's final "Tests" step */}
              <Route path="/test-lab" element={<TestLabRedirect />} />
              <Route path="/telephony" element={<TelephonyPage />} />
              <Route path="/calls" element={<CallsPage />} />
              <Route path="/campaigns" element={<CampaignsPage />} />
              <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
              <Route path="/instant-outbound" element={<InstantOutboundPage />} />
              <Route path="/instant-outbound/:id" element={<InstantOutboundDetailPage />} />

              {/* Internal Operation Modules */}
              <Route path="/tools" element={<ToolsPage />} />
              {/* Knowledge bases now live on each client's page */}
              <Route path="/knowledge" element={<Navigate to="/clients" replace />} />
              <Route path="/integrations" element={<IntegrationsPage />} />
              <Route path="/providers" element={<ProvidersPage />} />
              <Route path="/ai-providers" element={<Navigate to="/providers" replace />} />
              <Route path="/usage" element={<UsagePage />} />
              <Route path="/plans" element={<PlansPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/errors" element={<Navigate to="/logs" replace />} />

              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;

