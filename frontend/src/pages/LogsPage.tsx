import React, { useEffect, useState } from 'react';
import { Terminal, AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { telephonyService, Call } from '../services/telephony';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

export const LogsPage: React.FC = () => {
  const [calls, setCalls] = useState<Call[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterLevel, setFilterLevel] = useState<'ALL' | 'ERROR' | 'COMPLETED'>('ALL');

  const fetchLogs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await telephonyService.getCalls();
      setCalls(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch operations logs');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  const filteredCalls = calls.filter((c) => {
    if (filterLevel === 'ERROR') return c.status === 'FAILED' || c.status === 'ERROR';
    if (filterLevel === 'COMPLETED') return c.status === 'COMPLETED';
    return true;
  });

  const failureCount = calls.filter((c) => c.status === 'FAILED' || c.status === 'ERROR').length;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <Terminal className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">Errors &amp; Diagnostic Logs</h1>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-time runtime session events, PSTN webhook status callbacks, and carrier failure audits.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={fetchLogs} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Diagnostics
          </Button>
        </div>
      </div>

      {/* Metrics Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Audit Records</span>
          <div className="text-2xl font-bold font-mono text-slate-100 mt-1">{calls.length}</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Persisted telephony session interactions</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-rose-500">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Recorded Errors / Failures</span>
          <div className="text-2xl font-bold font-mono text-rose-400 mt-1">{failureCount}</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Aborted, rejected, or dropped sessions</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#22d3ee]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">System Health</span>
          <div className="text-2xl font-bold font-mono text-[#00df8f] mt-1">Operational</div>
          <span className="text-[11px] text-slate-500 mt-1 block">FastAPI core daemon online &bull; PBKDF2 active</span>
        </Card>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant={filterLevel === 'ALL' ? 'primary' : 'secondary'}
          onClick={() => setFilterLevel('ALL')}
        >
          All Events ({calls.length})
        </Button>
        <Button
          size="sm"
          variant={filterLevel === 'ERROR' ? 'primary' : 'secondary'}
          onClick={() => setFilterLevel('ERROR')}
        >
          Errors Only ({failureCount})
        </Button>
        <Button
          size="sm"
          variant={filterLevel === 'COMPLETED' ? 'primary' : 'secondary'}
          onClick={() => setFilterLevel('COMPLETED')}
        >
          Completed Successful
        </Button>
      </div>

      {/* Log Feed */}
      <Card
        title={`Operations Audit Stream (${filteredCalls.length})`}
        subtitle="Chronological audit records captured by the backend telephony runtime"
      >
        {isLoading ? (
          <LoadingState message="Loading diagnostic stream..." />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchLogs} />
        ) : filteredCalls.length === 0 ? (
          <EmptyState
            icon={<Terminal className="h-6 w-6" />}
            title="No log events matching filter."
            description={
              filterLevel === 'ERROR'
                ? 'Zero system errors recorded. All telephony and runtime sessions completed cleanly.'
                : 'No session events recorded in system database.'
            }
          />
        ) : (
          <div className="space-y-2.5 max-h-[600px] overflow-y-auto pr-1">
            {filteredCalls.map((call) => {
              const isError = call.status === 'FAILED' || call.status === 'ERROR';

              return (
                <div
                  key={call.id}
                  className={`rounded-lg border p-3 text-xs font-mono transition-colors ${
                    isError
                      ? 'bg-rose-950/20 border-rose-900/40 text-rose-200'
                      : 'bg-[#06141a] border-[#143c49] text-slate-200'
                  }`}
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      {isError ? (
                        <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4 text-[#00df8f] shrink-0" />
                      )}
                      <div>
                        <span className="font-semibold text-slate-100">{call.provider.toUpperCase()} CALL</span>
                        <span className="text-slate-500 text-[11px] ml-2">ID: {call.id}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 text-[11px]">
                      <Badge variant={isError ? 'red' : 'green'} size="sm" dot>
                        {call.status}
                      </Badge>
                      <span className="text-slate-500">
                        {new Date(call.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>

                  <div className="mt-2.5 pt-2 border-t border-[#102d38] grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] text-slate-400">
                    <div>
                      <span className="text-slate-500 block">Caller Number:</span>
                      <span className="text-slate-200">{call.caller_number || 'Unknown'}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Agent Assignment:</span>
                      <span className="text-slate-200">{call.agent_name || call.agent_id}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Duration:</span>
                      <span className="text-slate-200 font-mono">{call.duration_seconds ?? 0}s</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Carrier SID:</span>
                      <span className="text-slate-400 font-mono truncate block" title={call.provider_call_id}>
                        {call.provider_call_id}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
};
