import React, { useEffect, useState } from 'react';
import { Puzzle, RefreshCw, CheckCircle2, Globe, Key, ShieldCheck } from 'lucide-react';
import { catalogsService } from '../services/catalogs';
import { Integration } from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

export const IntegrationsPage: React.FC = () => {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchIntegrations = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await catalogsService.listIntegrations();
      setIntegrations(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch integrations catalog');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchIntegrations();
  }, []);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <Puzzle className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">Integrations &amp; Connectors</h1>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Enterprise CRM, calendar synchronization, and third-party communication channels.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={fetchIntegrations} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Connectors
          </Button>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">System Connectors</span>
          <div className="text-2xl font-bold font-mono text-slate-100 mt-1">{integrations.length}</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Registered integration adapters</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#22d3ee]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Auth Protocol</span>
          <div className="text-2xl font-bold font-mono text-[#22d3ee] mt-1">OAuth2 &bull; API Key</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Encrypted backend credential vaults</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Sync Mode</span>
          <div className="text-2xl font-bold font-mono text-[#00df8f] mt-1">Real-time Hook</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Post-call automated calendar &amp; CRM push</span>
        </Card>
      </div>

      {/* Integrations Catalog */}
      <Card
        title={`Registered External Connectors (${integrations.length})`}
        subtitle="Connectors provide bidirectional synchronization between voice employees and client software"
      >
        {isLoading ? (
          <LoadingState message="Loading integrations..." />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchIntegrations} />
        ) : integrations.length === 0 ? (
          <EmptyState
            icon={<Puzzle className="h-6 w-6" />}
            title="No integrations found."
            description="Integration adapters can be configured and linked to client accounts."
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {integrations.map((item) => (
              <div
                key={item.id}
                className="rounded-lg border border-[#143c49] bg-[#06141a] p-4 flex flex-col justify-between hover:border-[#00df8f]/40 transition-colors"
              >
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <div className="h-8 w-8 rounded bg-[#091b22] border border-[#143c49] flex items-center justify-center text-[#00df8f]">
                        <Globe className="h-4 w-4" />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-slate-100">{item.name}</h3>
                        <span className="text-[11px] font-mono text-slate-500">{item.id}</span>
                      </div>
                    </div>
                    <Badge variant={item.connection_status === 'CONNECTED' ? 'green' : 'gray'} dot size="sm">
                      {item.connection_status}
                    </Badge>
                  </div>

                  <p className="text-xs text-slate-300 mt-3 leading-relaxed">
                    {item.description || 'External platform connection service for automated operations.'}
                  </p>
                </div>

                <div className="mt-4 pt-3 border-t border-[#102d38] flex items-center justify-between text-[11px] text-slate-400">
                  <span className="font-mono text-slate-400">
                    Category: <span className="text-slate-200">{item.category}</span>
                  </span>
                  <span className="font-mono text-slate-400">
                    Provider: <span className="text-slate-200">{item.provider}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};
