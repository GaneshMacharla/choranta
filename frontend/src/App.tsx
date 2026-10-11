import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { AppLayout } from './components/layout/AppLayout';
import { LoginPage } from './pages/LoginPage';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { OverviewPage } from './pages/OverviewPage';
import { ClientsPage } from './pages/ClientsPage';
import { ClientDetailPage } from './pages/ClientDetailPage';
import { AgentsPage } from './pages/AgentsPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { TestLabPage } from './pages/TestLabPage';
import { TelephonyPage } from './pages/TelephonyPage';
import { CallsPage } from './pages/CallsPage';
import { ToolsPage } from './pages/ToolsPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { IntegrationsPage } from './pages/IntegrationsPage';
import { ProvidersPage } from './pages/ProvidersPage';
import { UsagePage } from './pages/UsagePage';
import { LogsPage } from './pages/LogsPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage } from './pages/NotFoundPage';

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            {/* Public Login Route */}
            <Route path="/login" element={<LoginPage />} />

            {/* Protected Internal Routes */}
            <Route element={<AppLayout />}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/clients" element={<ClientsPage />} />
              <Route path="/clients/:id" element={<ClientDetailPage />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/agents/:id" element={<AgentDetailPage />} />
              <Route path="/test-lab" element={<TestLabPage />} />
              <Route path="/telephony" element={<TelephonyPage />} />
              <Route path="/calls" element={<CallsPage />} />

              {/* Internal Operation Modules */}
              <Route path="/tools" element={<ToolsPage />} />
              <Route path="/knowledge" element={<KnowledgePage />} />
              <Route path="/integrations" element={<IntegrationsPage />} />
              <Route path="/providers" element={<ProvidersPage />} />
              <Route path="/ai-providers" element={<Navigate to="/providers" replace />} />
              <Route path="/usage" element={<UsagePage />} />
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

