import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Search } from 'lucide-react';
import { Button } from '../common/Button';
import { ErrorState } from '../common/ErrorState';
import { LoadingState } from '../common/LoadingState';
import { InternalStatus, OwnedNumber, Paged, money, numbersService } from '../../services/numbers';
import { MockBadge, NumberStatusBadge, formatDate } from './shared';
import { AssignModal } from './AssignModal';
import { ReleaseModal } from './ReleaseModal';

const FIELD = 'rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';
const STATUSES: { value: InternalStatus | ''; label: string }[] = [
  { value: '', label: 'All current' }, { value: 'AVAILABLE', label: 'In pool' }, { value: 'ASSIGNED', label: 'Assigned' },
  { value: 'NEEDS_RECONCILIATION', label: 'Needs attention' }, { value: 'RELEASED', label: 'Released' },
];
const PER_PAGE = 25;

/** Numbers Choranta owns: who has them, what they cost, and what can be done with each. */
export const OwnedNumbersPanel: React.FC<{ isAdmin: boolean; refreshKey?: number }> = ({ isAdmin, refreshKey }) => {
  const navigate = useNavigate();
  const [filters, setFilters] = useState({ search: '', status: '' as InternalStatus | '', capability: '' });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<OwnedNumber> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<OwnedNumber | null>(null);
  const [releasing, setReleasing] = useState<OwnedNumber | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await numbersService.list({ ...applied, page, per_page: PER_PAGE }));
    } catch (err: any) {
      setError(err.message || "Couldn't load numbers.");
    } finally {
      setLoading(false);
    }
  }, [applied, page]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const unassign = async (n: OwnedNumber) => {
    if (!window.confirm(`Take ${n.e164} back from ${n.assignment?.client_name || 'its client'}? Inbound calls to it stop reaching their AI employee.`)) return;
    setNotice(null);
    try {
      await numbersService.unassign(n.id);
      setNotice(`${n.e164} is back in the pool.`);
      load();
    } catch (err: any) {
      setError(err.message || "Couldn't unassign.");
    }
  };

  const lastPage = data?.total ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : 1;

  return (
    <div className="space-y-4">
      <form className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto_auto]" aria-label="Filter numbers"
        onSubmit={(e) => { e.preventDefault(); setPage(1); setApplied({ ...filters }); }}>
        <input className={FIELD} placeholder="Search by number" aria-label="Search by number" value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        <select className={FIELD} aria-label="Status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value as InternalStatus | '' })}>
          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select className={FIELD} aria-label="Capability" value={filters.capability} onChange={(e) => setFilters({ ...filters, capability: e.target.value })}>
          <option value="">Any capability</option>
          <option value="voice">Voice</option>
          <option value="sms">SMS</option>
        </select>
        <Button type="submit" variant="primary" size="sm" leftIcon={<Search className="h-3.5 w-3.5" />}>Filter</Button>
      </form>
      {notice && <p role="status" className="rounded border border-[#0a4d39] bg-[#052b20]/80 p-2 text-xs text-[#00df8f]">{notice}</p>}

      {loading ? (
        <LoadingState message="Loading numbers..." />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data || data.items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#1b3a46] p-8 text-center text-sm text-slate-400">
          No numbers yet. Buy one from the Inventory tab, or run a sync to pick up numbers bought in the Vobiz console.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-[#102d38]">
            <table className="w-full min-w-[900px] text-left text-sm text-slate-300">
              <thead className="border-b border-[#102d38] bg-[#06161d] text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Number</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Client · AI employee</th>
                  <th className="px-4 py-2.5 font-medium">Trunk</th>
                  <th className="px-4 py-2.5 font-medium">Monthly cost</th>
                  <th className="px-4 py-2.5 font-medium">Bought</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#102d38]">
                {data.items.map((n) => (
                  <tr key={n.id} className="cursor-pointer hover:bg-[#071a21]" onClick={() => navigate(`/numbers/${n.id}`)}>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2 font-mono text-slate-100">{n.e164} {n.is_mock && <MockBadge />}</span>
                      <span className="text-[11px] text-slate-500">{n.provider} · {n.country || '-'} · {n.number_type || '-'}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="flex flex-col gap-1">
                        <NumberStatusBadge status={n.internal_status} />
                        <span className="text-[11px] text-slate-500">carrier: {n.provider_status || '-'}</span>
                      </span>
                      {n.attention && <AlertTriangle className="mt-1 h-3.5 w-3.5 text-amber-400" aria-label="Needs attention" />}
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {n.assignment ? <>{n.assignment.client_name}<span className="block text-slate-500">{n.assignment.agent_name || 'No AI employee'}</span></> : <span className="text-slate-500">-</span>}
                    </td>
                    <td className="px-4 py-2.5 text-xs">{n.trunk_id ? <span className="font-mono">{n.trunk_id.slice(0, 8)}…</span> : '-'}</td>
                    <td className="px-4 py-2.5 text-xs">{money(n.monthly_cost, n.currency)}</td>
                    <td className="px-4 py-2.5 text-xs">{formatDate(n.purchased_at)}</td>
                    <td className="px-4 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                      <span className="flex justify-end gap-1.5">
                        {n.internal_status === 'AVAILABLE' && <Button variant="secondary" size="sm" onClick={() => setAssigning(n)}>Assign</Button>}
                        {n.internal_status === 'ASSIGNED' && <Button variant="secondary" size="sm" onClick={() => unassign(n)}>Unassign</Button>}
                        {isAdmin && ['AVAILABLE', 'NEEDS_RECONCILIATION'].includes(n.internal_status) && (
                          <Button variant="ghost" size="sm" onClick={() => setReleasing(n)}>Release</Button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>{data.total} numbers</span>
            <span className="flex items-center gap-2">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              Page {page} of {lastPage}
              <Button variant="secondary" size="sm" disabled={page >= lastPage} onClick={() => setPage(page + 1)}>Next</Button>
            </span>
          </div>
        </>
      )}

      <AssignModal number={assigning} onClose={() => setAssigning(null)}
        onDone={(n) => { setAssigning(null); setNotice(`${n.e164} assigned to ${n.assignment?.client_name}.`); load(); }} />
      <ReleaseModal number={releasing} onClose={() => setReleasing(null)}
        onDone={(r) => { setReleasing(null); setNotice(`${r.operation.e164}: release ${r.operation.operation_status.toLowerCase()}.`); load(); }} />
    </div>
  );
};
