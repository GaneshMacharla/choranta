import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { ErrorState } from '../components/common/ErrorState';
import { LoadingState } from '../components/common/LoadingState';
import { AssignModal } from '../components/numbers/AssignModal';
import { OperationsTable } from '../components/numbers/OperationsPanel';
import { ReleaseModal } from '../components/numbers/ReleaseModal';
import { MockBadge, MockModeBanner, NumberStatusBadge, formatDate } from '../components/numbers/shared';
import { useAuth } from '../context/AuthContext';
import { OwnedNumber, money, numbersService } from '../services/numbers';

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <>
    <dt className="text-slate-400">{label}</dt>
    <dd className="break-all text-slate-200">{children}</dd>
  </>
);

/** One number: carrier ids, status, costs, who has it now and before, and every operation on it. */
export const NumberDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [number, setNumber] = useState<OwnedNumber | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    setError(null);
    numbersService.get(id).then(setNumber).catch((err) => setError(err.message || "Couldn't load the number."));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const unassign = async () => {
    if (!number || !window.confirm(`Take ${number.e164} back from ${number.assignment?.client_name}?`)) return;
    setBusy(true);
    try {
      setNumber(await numbersService.unassign(number.id));
    } catch (err: any) {
      setError(err.message || "Couldn't unassign.");
    } finally {
      setBusy(false);
    }
  };

  if (error && !number) return <div className="p-8"><ErrorState message={error} onRetry={load} /></div>;
  if (!number) return <div className="p-8"><LoadingState message="Loading number..." /></div>;
  const current = number.assignment;

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-8">
      <Link to="/numbers" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200"><ArrowLeft className="h-3.5 w-3.5" /> Phone numbers</Link>
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="flex items-center gap-2 font-mono text-2xl font-semibold text-slate-100">{number.e164} {number.is_mock && <MockBadge />}</h1>
          <div className="mt-1 flex items-center gap-2"><NumberStatusBadge status={number.internal_status} /><span className="text-xs text-slate-500">carrier status: {number.provider_status || '-'}</span></div>
        </div>
        <div className="flex flex-wrap gap-2">
          {number.internal_status === 'AVAILABLE' && <Button variant="primary" size="sm" onClick={() => setAssigning(true)}>Assign to a client</Button>}
          {number.internal_status === 'ASSIGNED' && <Button variant="secondary" size="sm" isLoading={busy} onClick={unassign}>Unassign</Button>}
          {isAdmin && ['AVAILABLE', 'NEEDS_RECONCILIATION'].includes(number.internal_status) && (
            <Button variant="danger" size="sm" onClick={() => setReleasing(true)}>Release</Button>
          )}
        </div>
      </div>
      {number.is_mock && <MockModeBanner />}
      {number.attention && (
        <p role="alert" className="flex items-start gap-2 rounded border border-amber-800/50 bg-amber-950/40 p-3 text-sm text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {number.attention}
        </p>
      )}
      {error && <p role="alert" className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-xs text-rose-300">{error}</p>}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Carrier">
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-xs">
            <Row label="Provider">{number.provider}</Row>
            <Row label="Provider number id">{number.provider_number_id || '-'}</Row>
            <Row label="Country · region">{number.country || '-'} · {number.region || '-'}</Row>
            <Row label="Type">{number.number_type || '-'}{number.number_type_derived ? ' (from prefix)' : ''}</Row>
            <Row label="Capabilities">{Object.entries(number.capabilities).filter(([, on]) => on).map(([c]) => c).join(', ') || 'Not reported'}</Row>
            <Row label="Inbound application">{number.application_id || 'Not attached'}</Row>
            <Row label="SIP trunk">{number.trunk_id || 'None'}</Row>
            <Row label="Vobiz sub-account">{number.subaccount_auth_id || 'Main account'}</Row>
            {number.aadhaar_verification_required && <Row label="Compliance"><span className="text-amber-300">Aadhaar verification required by Vobiz</span></Row>}
          </dl>
        </Card>
        <Card title="Costs and dates">
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-xs">
            <Row label="Monthly rental">{money(number.monthly_cost, number.currency)}</Row>
            <Row label="Setup fee">{money(number.setup_cost, number.currency)}</Row>
            <Row label="Currency">{number.currency || '-'}</Row>
            <Row label="Bought">{formatDate(number.purchased_at)}</Row>
            <Row label="Next billing">{formatDate(number.next_billing_date)}</Row>
            <Row label="Last synced">{formatDate(number.last_synced_at)}</Row>
            {number.released_at && <Row label="Released">{formatDate(number.released_at)}</Row>}
          </dl>
        </Card>
      </div>

      <Card title="Assignments" subtitle={current ? `Now with ${current.client_name}` : 'Not assigned to anyone right now'}>
        {(number.assignments || []).length === 0 ? <p className="text-xs text-slate-500">Never assigned.</p> : (
          <ul className="divide-y divide-[#102d38] text-xs">
            {(number.assignments || []).map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span>
                  <span className="font-semibold text-slate-200">{a.client_name}</span>
                  <span className="text-slate-400"> · {a.agent_name || 'no AI employee'}{a.trunk_id ? ` · trunk ${a.trunk_id.slice(0, 8)}…` : ''}</span>
                  <span className="block text-slate-500">
                    {formatDate(a.assigned_at)} by {a.assigned_by || '-'}
                    {a.released_at && ` → ${formatDate(a.released_at)} (${(a.end_reason || '').toLowerCase().replace('_', ' ')})`}
                  </span>
                </span>
                <NumberStatusBadge status={a.status === 'ACTIVE' ? 'ASSIGNED' : 'RELEASED'} />
              </li>
            ))}
          </ul>
        )}
        {current && (
          <p className="mt-3 text-[11px] text-slate-500">
            Unassigning stops routing calls to the client's AI employee. Vobiz has no way to detach a number from an application,
            so calls to an unassigned number still reach Choranta and are refused as unconfigured.
          </p>
        )}
      </Card>

      <Card title="Operations">
        <OperationsTable operations={number.operations || []} isAdmin={isAdmin} onChanged={load} />
      </Card>

      {assigning && <AssignModal number={number} onClose={() => setAssigning(false)} onDone={(n) => { setAssigning(false); setNumber(n); }} />}
      {releasing && <ReleaseModal number={number} onClose={() => setReleasing(false)} onDone={() => { setReleasing(false); load(); }} />}
    </div>
  );
};
