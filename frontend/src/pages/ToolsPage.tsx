import React, { useEffect, useState } from 'react';
import { Wrench, RefreshCw, Clock, CheckCircle2 } from 'lucide-react';
import { catalogsService } from '../services/catalogs';
import { Tool } from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

export const ToolsPage: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTools = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await catalogsService.listTools();
      setTools(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch tools catalog');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <Wrench className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">Tools & Execution Capabilities</h1>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic action schemas, tool execution boundaries, and live agent integrations.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={fetchTools} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Catalog
          </Button>
        </div>
      </div>

      {/* Overview Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Registered Tools</span>
          <div className="text-2xl font-bold font-mono text-slate-100 mt-1">{tools.length}</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Active system execution capabilities</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#22d3ee]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Execution Pipeline</span>
          <div className="text-2xl font-bold font-mono text-[#22d3ee] mt-1">Sandboxed</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Strict JSON schema validation &amp; timeout safety</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Invocation Model</span>
          <div className="text-2xl font-bold font-mono text-[#00df8f] mt-1">Function Calling</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Gemini 3.8 Flash structured tool resolution</span>
        </Card>
      </div>

      {/* Tools Catalog */}
      <Card
        title={`Available Tools Catalog (${tools.length})`}
        subtitle="Tools attached to AI employees are invoked dynamically during voice conversations"
      >
        {isLoading ? (
          <LoadingState message="Loading tools catalog from backend..." />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchTools} />
        ) : tools.length === 0 ? (
          <EmptyState
            icon={<Wrench className="h-6 w-6" />}
            title="No tools found in catalog."
            description="Tools can be defined in the database or attached via individual AI employee blueprints."
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {tools.map((tool) => (
              <div
                key={tool.id}
                className="rounded-lg border border-[#143c49] bg-[#06141a] p-4 flex flex-col justify-between hover:border-[#00df8f]/40 transition-colors"
              >
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                        {tool.name}
                      </h3>
                      <span className="text-[11px] font-mono text-slate-500">{tool.id}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="rounded bg-[#052b20] border border-[#0a4d39] px-2 py-0.5 text-[10px] font-mono text-[#00df8f] font-medium">
                        {tool.executor_type}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-300 mt-2.5 leading-relaxed">
                    {tool.description}
                  </p>
                </div>

                <div className="mt-4 pt-3 border-t border-[#102d38] flex items-center justify-between text-[11px] text-slate-400">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5 text-slate-500" /> Timeout: {tool.timeout}s
                  </span>
                  <span className="flex items-center gap-1 text-[#00df8f]">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Schema Validated
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
