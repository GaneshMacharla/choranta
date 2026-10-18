import React, { useState } from 'react';
import { ShieldCheck, Server, Database, Key, FlaskConical, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Card } from '../components/common/Card';
import { Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { request } from '../services/api';
import { PricingSettingsCard } from '../components/settings/PricingSettingsCard';
import { CarrierCostCheckCard } from '../components/settings/CarrierCostCheckCard';

export const SettingsPage: React.FC = () => {
  const { user } = useAuth();
  const [mockMessage, setMockMessage] = useState<string | null>(null);
  const [isMockActionRunning, setIsMockActionRunning] = useState(false);

  const runMockAction = async (action: 'seed' | 'reset') => {
    setIsMockActionRunning(true);
    setMockMessage(null);
    try {
      const result = await request<{ label: string }>(`/mock/${action}`, { method: 'POST' });
      setMockMessage(result.label);
    } catch (error: any) {
      setMockMessage(error.message || 'Mock environment action failed.');
    } finally {
      setIsMockActionRunning(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="pb-2 border-b border-[#1a1e2b]">
        <h1 className="text-xl font-bold tracking-tight text-slate-100 flex items-center gap-2">
          Internal Settings
        </h1>
        <p className="text-xs text-slate-400 mt-0.5">
          Internal platform configuration and current operator session details
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card
          title="Mock Environment"
          subtitle="Safe, deterministic data and providers for local development"
        >
          <div className="space-y-4 text-xs">
            <div className="flex items-center gap-2 rounded border border-amber-700/50 bg-amber-950/25 p-3 text-amber-300">
              <FlaskConical className="h-4 w-4 shrink-0" />
              <span className="font-semibold">MOCK ENVIRONMENT - NO EXTERNAL PROVIDER CALLS</span>
            </div>
            <p className="leading-relaxed text-slate-400">
              Seeded clients, agents, versions, simulated numbers, and completed calls are persisted in the current
              database with <span className="font-mono text-amber-300">mock_</span> identifiers.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="primary" onClick={() => runMockAction('seed')} isLoading={isMockActionRunning}>
                <FlaskConical className="mr-1.5 h-3.5 w-3.5" /> Seed mock data
              </Button>
              <Button size="sm" variant="secondary" onClick={() => runMockAction('reset')} isLoading={isMockActionRunning}>
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Reset mock data
              </Button>
            </div>
            {mockMessage && <p className="font-mono text-[11px] text-[#00df8f]">{mockMessage}</p>}
          </div>
        </Card>

        {/* Operator Profile */}
        <Card
          title="Operator Session"
          subtitle="Authenticated internal personnel profile"
        >
          <div className="space-y-4 text-xs">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-[#00df8f]/15 border border-[#00df8f]/30 flex items-center justify-center text-sm font-semibold text-[#00df8f]">
                {user?.name?.charAt(0) || 'O'}
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-200">{user?.name}</div>
                <div className="text-slate-400 font-mono">{user?.email}</div>
              </div>
            </div>

            <div className="pt-3 border-t border-[#102d38] space-y-2">
              <div className="flex justify-between">
                <span className="text-slate-500">Access Level:</span>
                <Badge variant={user?.role === 'ADMIN' ? 'green' : 'gray'}>
                  {user?.role}
                </Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Account Status:</span>
                <Badge variant="green" dot>{user?.status || 'ACTIVE'}</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">User ID:</span>
                <span className="font-mono text-slate-400">{user?.id}</span>
              </div>
            </div>
          </div>
        </Card>

        {/* System Architecture */}
        <Card
          title="Platform Architecture"
          subtitle="Choranta internal system environment"
        >
          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between p-2.5 rounded bg-[#06141a] border border-[#143c49]">
              <div className="flex items-center gap-2.5">
                <Server className="h-4 w-4 text-[#00df8f]" />
                <span className="text-slate-300">FastAPI Orchestrator</span>
              </div>
              <span className="font-mono text-[11px] text-[#00df8f]">Online &bull; v0.1.0</span>
            </div>

            <div className="flex items-center justify-between p-2.5 rounded bg-[#06141a] border border-[#143c49]">
              <div className="flex items-center gap-2.5">
                <Database className="h-4 w-4 text-[#00df8f]" />
                <span className="text-slate-300">Supabase PostgreSQL Schema</span>
              </div>
              <span className="font-mono text-[11px] text-[#00df8f]">Connected &amp; Synchronized</span>
            </div>

            <div className="flex items-center justify-between p-2.5 rounded bg-[#06141a] border border-[#143c49]">
              <div className="flex items-center gap-2.5">
                <ShieldCheck className="h-4 w-4 text-[#22d3ee]" />
                <span className="text-slate-300">Authentication</span>
              </div>
              <span className="font-mono text-[11px] text-slate-400">JWT Token Security (PBKDF2)</span>
            </div>
          </div>
        </Card>

        {user?.role === 'ADMIN' && <PricingSettingsCard />}
        {user?.role === 'ADMIN' && <CarrierCostCheckCard />}
      </div>

      {/* Security Notice */}
      <div className="rounded-lg border border-[#143c49] bg-[#091b22] p-4 text-xs text-slate-400 flex items-start gap-3">
        <Key className="h-4 w-4 text-[#00df8f] shrink-0 mt-0.5" />
        <div>
          <strong className="text-slate-200 block mb-0.5">Strict Internal Access</strong>
          Public registration is disabled. Only accounts created by platform administrators can access Choranta Agent Studio. Client credentials and provider API keys are managed centrally in the backend.
        </div>
      </div>
    </div>
  );
};
