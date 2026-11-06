import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { request } from '../services/api';
import { BusinessVerification, KycCheck, KycCheckKind } from '../services/portal';

const FILTERS = [
  { value: 'IN_PROGRESS', label: 'In progress' },
  { value: 'VERIFIED', label: 'Verified' },
  { value: '', label: 'All' },
];
const STATUS_VARIANT: Record<string, 'yellow' | 'green' | 'gray'> = { IN_PROGRESS: 'yellow', VERIFIED: 'green' };
const CHECK_VARIANT: Record<KycCheck['status'], 'green' | 'red' | 'yellow'> = { verified: 'green', failed: 'red', pending: 'yellow' };
const CHECK_ORDER: KycCheckKind[] = ['pan', 'gst', 'cin', 'aadhaar'];

export const verificationsApi = {
  list: (status?: string) => request<BusinessVerification[]>(`/verifications${status ? `?status=${status}` : ''}`),
  refresh: (clientId: string) => request<BusinessVerification>(`/verifications/${clientId}/refresh`, { method: 'POST' }),
};

/** Staff: where each client is with business verification. Vobiz does the checking; this is read-only. */
export const VerificationsPage: React.FC = () => {
  const [filter, setFilter] = useState('IN_PROGRESS');
  const [rows, setRows] = useState<BusinessVerification[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await verificationsApi.list(filter || undefined));
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Could not load verifications.');
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  const recheck = async (clientId: string) => {
    setBusy(clientId);
    try {
      const updated = await verificationsApi.refresh(clientId);
      setRows((prev) => (prev || []).map((r) => (r.client_id === clientId ? updated : r)));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-8">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-100">
            <ShieldCheck className="h-6 w-6 text-[#00df8f]" /> Business Verifications
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Clients verify themselves in the portal; Vobiz checks each document against government records, in the client's own name.
            They can get numbers once Vobiz has verified them.
          </p>
        </div>
        <Button variant="secondary" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={load}>Refresh</Button>
      </div>

      <div className="flex w-fit rounded-full bg-[#0a2028] p-0.5">
        {FILTERS.map((f) => (
          <button key={f.value} type="button" onClick={() => setFilter(f.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${filter === f.value ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300 hover:text-slate-100'}`}>
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {rows === null ? (
        <LoadingState message="Loading verifications..." />
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#143c49] p-10 text-center text-sm text-slate-400">Nothing here.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[#143c49]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#091b22] text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Client</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Documents</th>
                <th className="px-4 py-3 font-medium">Updated</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.client_id || v.created_at} className="border-t border-[#102d38] align-top">
                  <td className="px-4 py-3">
                    {v.client_id ? (
                      <Link to={`/clients/${v.client_id}`} className="text-slate-200 hover:underline">{v.client_name}</Link>
                    ) : (
                      <span className="text-slate-400">{v.client_name} (deleted)</span>
                    )}
                    <div className="font-mono text-[11px] text-[#00df8f]">{v.client_code}</div>
                    <div className="text-[11px] text-slate-500">{v.email}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{v.kyc_type ? v.kyc_types[v.kyc_type]?.label : ''}</td>
                  <td className="px-4 py-3">
                    <div className="space-y-1">
                      {CHECK_ORDER.filter((k) => v.checks?.[k]).map((k) => {
                        const c = v.checks![k]!;
                        return (
                          <div key={k} className="flex flex-wrap items-center gap-2 text-xs">
                            <Badge variant={CHECK_VARIANT[c.status]} size="sm">{c.status}</Badge>
                            <span className="text-slate-300">{c.label}</span>
                            {c.value && <span className="font-mono text-slate-500">{c.value}</span>}
                            {c.name && <span className="text-slate-500">{c.name}</span>}
                          </div>
                        );
                      })}
                      {!Object.keys(v.checks || {}).length && <span className="text-xs text-slate-500">Nothing submitted yet</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">{v.updated_at ? new Date(v.updated_at).toLocaleString('en-IN') : ''}</td>
                  <td className="px-4 py-3"><Badge variant={STATUS_VARIANT[v.status] || 'gray'} size="sm">{v.status.replace('_', ' ')}</Badge></td>
                  <td className="px-4 py-3 text-right">
                    {v.client_id && v.status !== 'VERIFIED' && (
                      <Button size="sm" variant="ghost" leftIcon={<RefreshCw className="h-3.5 w-3.5" />} isLoading={busy === v.client_id}
                        onClick={() => recheck(v.client_id!)}>Re-check</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
