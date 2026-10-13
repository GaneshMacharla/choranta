import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle, FileText, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { LoadingState } from '../components/common/LoadingState';
import { request } from '../services/api';
import { BusinessVerification, fetchAuthedBlob } from '../services/portal';

const FILTERS = [
  { value: 'PENDING', label: 'To review' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Needs changes' },
  { value: '', label: 'All' },
];
const STATUS_VARIANT: Record<string, 'yellow' | 'green' | 'red' | 'gray'> = { PENDING: 'yellow', APPROVED: 'green', REJECTED: 'red' };

export const verificationsApi = {
  list: (status?: string) => request<BusinessVerification[]>(`/verifications${status ? `?status=${status}` : ''}`),
  pendingCount: () => request<{ pending: number }>('/verifications/count'),
  approve: (clientId: string) => request<BusinessVerification>(`/verifications/${clientId}/approve`, { method: 'POST' }),
  reject: (clientId: string, note: string) =>
    request<BusinessVerification>(`/verifications/${clientId}/reject`, { method: 'POST', body: JSON.stringify({ note }) }),
  openDocument: async (clientId: string, index: number) => {
    const url = URL.createObjectURL(await fetchAuthedBlob(`/verifications/${clientId}/documents/${index}`));
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },
};

/** Admin: review clients' business verification (KYC) before they can buy phone numbers. */
export const VerificationsPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [filter, setFilter] = useState('PENDING');
  const [rows, setRows] = useState<BusinessVerification[] | null>(null);
  const [open, setOpen] = useState<BusinessVerification | null>(null);
  const [note, setNote] = useState('');
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

  const decide = async (approve: boolean) => {
    if (!open?.client_id) return;
    setBusy(approve ? 'approve' : 'reject');
    try {
      if (approve) await verificationsApi.approve(open.client_id);
      else await verificationsApi.reject(open.client_id, note.trim());
      setOpen(null);
      setNote('');
      await load();
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
          <p className="mt-1 text-sm text-slate-400">Clients must be verified before they can buy phone numbers. Check the documents match the details, then approve or ask for changes.</p>
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
                <th className="px-4 py-3 font-medium">Business</th>
                <th className="px-4 py-3 font-medium">PAN / GSTIN</th>
                <th className="px-4 py-3 font-medium">Submitted</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.client_id} className="border-t border-[#102d38]">
                  <td className="px-4 py-3">
                    <Link to={`/clients/${v.client_id}`} className="text-slate-200 hover:underline">{v.client_name}</Link>
                    <div className="font-mono text-[11px] text-[#00df8f]">{v.client_code}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{v.legal_name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-300">{v.pan}{v.gstin ? <div className="text-slate-500">{v.gstin}</div> : null}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{v.submitted_at ? new Date(v.submitted_at).toLocaleString('en-IN') : ''}</td>
                  <td className="px-4 py-3"><Badge variant={STATUS_VARIANT[v.status] || 'gray'} size="sm">{v.status}</Badge></td>
                  <td className="px-4 py-3 text-right">
                    <Button size="sm" variant={v.status === 'PENDING' ? 'primary' : 'ghost'} onClick={() => { setOpen(v); setNote(''); }}>
                      {v.status === 'PENDING' ? 'Review' : 'View'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal isOpen={open !== null} onClose={() => setOpen(null)} title={`Verify ${open?.legal_name ?? ''}`}
        description={`${open?.client_name ?? ''} · ${open?.client_code ?? ''}`} maxWidth="2xl">
        {open && (
          <div className="space-y-4 text-xs">
            <dl className="grid grid-cols-[170px_1fr] gap-x-4 gap-y-2 rounded-lg border border-[#143c49] bg-[#06141a] p-4">
              {([
                ['Registered name', open.legal_name], ['PAN', open.pan], ['GSTIN', open.gstin || '—'], ['CIN / LLPIN', open.cin || '—'],
                ['Registered address', open.registered_address],
                ['Authorised signatory', `${open.signatory_name}${open.signatory_designation ? `, ${open.signatory_designation}` : ''}`],
                ['Signatory phone', open.signatory_phone || '—'],
              ] as Array<[string, string | undefined]>).map(([k, val]) => (
                <React.Fragment key={k}>
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="whitespace-pre-line text-slate-200">{val}</dd>
                </React.Fragment>
              ))}
            </dl>
            <div className="space-y-1.5">
              <p className="font-medium text-slate-300">Documents</p>
              {(open.documents || []).map((d) => (
                <button key={d.index} type="button" onClick={() => verificationsApi.openDocument(open.client_id!, d.index).catch((e) => setError(e.message))}
                  className="flex w-full items-center justify-between rounded border border-[#143c49] px-3 py-2 text-left hover:border-[#00df8f]">
                  <span className="flex items-center gap-2 text-slate-200"><FileText className="h-3.5 w-3.5 text-[#00df8f]" /> {d.label}</span>
                  <span className="text-slate-500">{d.filename} · {(d.size / 1024).toFixed(0)} KB</span>
                </button>
              ))}
            </div>
            {open.admin_note && <p className="text-rose-300">Previous note: {open.admin_note}</p>}
            {open.status === 'PENDING' && isAdmin && (
              <>
                <textarea rows={2} className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
                  placeholder="If something's wrong, tell the client what to fix (e.g. address proof is older than 3 months)"
                  value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" leftIcon={<XCircle className="h-4 w-4" />} disabled={!note.trim()} isLoading={busy === 'reject'} onClick={() => decide(false)}>
                    Ask for changes
                  </Button>
                  <Button variant="primary" leftIcon={<CheckCircle className="h-4 w-4" />} isLoading={busy === 'approve'} onClick={() => decide(true)}>
                    Approve
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};
