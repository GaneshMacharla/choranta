import React, { useCallback, useEffect, useState } from 'react';
import { Button } from '../common/Button';
import { ErrorState } from '../common/ErrorState';
import { LoadingState } from '../common/LoadingState';
import { NumberOperation, Paged, numbersService } from '../../services/numbers';
import { MockBadge, NumberStatusBadge, formatDate } from './shared';

const FIELD = 'rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-xs text-slate-100 focus:border-[#00df8f] focus:outline-none';
const OPEN = ['PENDING', 'UNCERTAIN', 'NEEDS_RECONCILIATION'];

/** Every purchase, assignment, release and sync, newest first. Uncertain ones can be checked with the carrier. */
export const OperationsTable: React.FC<{ operations: NumberOperation[]; isAdmin: boolean; onChanged: () => void }> = ({
  operations, isAdmin, onChanged,
}) => {
  const [checking, setChecking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = async (op: NumberOperation) => {
    setChecking(op.id);
    setError(null);
    try {
      await numbersService.reconcile(op.id);
      onChanged();
    } catch (err: any) {
      setError(err.message || "Couldn't check with the carrier.");
    } finally {
      setChecking(null);
    }
  };

  if (operations.length === 0) return <p className="text-xs text-slate-500">No operations yet.</p>;
  return (
    <div className="space-y-2">
      {error && <p role="alert" className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-xs text-rose-300">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-[#102d38]">
        <table className="w-full min-w-[760px] text-left text-xs text-slate-300">
          <thead className="border-b border-[#102d38] bg-[#06161d] uppercase tracking-wider text-slate-400">
            <tr>
              <th className="px-3 py-2 font-medium">When</th>
              <th className="px-3 py-2 font-medium">What</th>
              <th className="px-3 py-2 font-medium">Number</th>
              <th className="px-3 py-2 font-medium">Outcome</th>
              <th className="px-3 py-2 font-medium">By</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#102d38]">
            {operations.map((op) => (
              <tr key={op.id}>
                <td className="whitespace-nowrap px-3 py-2">{formatDate(op.created_at)}</td>
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5">{op.operation_type.replace('_', ' ').toLowerCase()} {op.is_mock && <MockBadge />}</span>
                </td>
                <td className="px-3 py-2 font-mono">{op.e164 || '-'}</td>
                <td className="px-3 py-2">
                  <NumberStatusBadge status={op.operation_status} />
                  {op.error_message && <span className="mt-1 block max-w-md text-[11px] text-slate-400">{op.error_message}</span>}
                </td>
                <td className="px-3 py-2 text-slate-400">{op.actor || '-'}</td>
                <td className="px-3 py-2 text-right">
                  {isAdmin && OPEN.includes(op.operation_status) && ['PURCHASE', 'RELEASE'].includes(op.operation_type) && (
                    <Button variant="secondary" size="sm" isLoading={checking === op.id} onClick={() => check(op)}>Check again</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const OperationsPanel: React.FC<{ isAdmin: boolean; refreshKey?: number }> = ({ isAdmin, refreshKey }) => {
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<NumberOperation> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await numbersService.operations({ status, page, per_page: 50 }));
    } catch (err: any) {
      setError(err.message || "Couldn't load operations.");
    } finally {
      setLoading(false);
    }
  }, [status, page]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const lastPage = data?.total ? Math.max(1, Math.ceil(data.total / 50)) : 1;
  return (
    <div className="space-y-3">
      <select className={FIELD} aria-label="Outcome" value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
        <option value="">All outcomes</option>
        <option value="UNCERTAIN">Uncertain</option>
        <option value="NEEDS_RECONCILIATION">Needs reconciliation</option>
        <option value="FAILED">Failed</option>
        <option value="SUCCEEDED">Succeeded</option>
        <option value="RECOVERED">Recovered</option>
      </select>
      {loading ? <LoadingState message="Loading operations..." /> : error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <OperationsTable operations={data?.items || []} isAdmin={isAdmin} onChanged={load} />
          {data && data.total! > 50 && (
            <div className="flex justify-end gap-2 text-xs text-slate-400">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="self-center">Page {page} of {lastPage}</span>
              <Button variant="secondary" size="sm" disabled={page >= lastPage} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          )}
        </>
      )}
    </div>
  );
};
