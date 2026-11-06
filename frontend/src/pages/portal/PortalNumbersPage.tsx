import React, { useEffect, useState } from 'react';
import { AlertTriangle, BadgeCheck, Clock, Phone, PhoneOutgoing, Plus, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { NumberActivationModal } from '../../components/billing/NumberActivationModal';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { Badge } from '../../components/common/Badge';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { BuyNumberModal } from '../../components/billing/BuyNumberModal';
import { fmtDate } from '../../components/billing/PlanUsageBar';
import { inr, PortalNumber, portalService, VerificationStatus } from '../../services/portal';
import { NUMBER_TYPE_LABELS, NumberPrice } from '../../services/plans';

type Agent = Awaited<ReturnType<typeof portalService.agents>>[number];

const NumberStatus: React.FC<{ n: PortalNumber }> = ({ n }) => {
  if (n.rental_status === 'RELEASED' || n.status === 'RELEASED') return <Badge variant="gray">RELEASED</Badge>;
  if (n.rental_status === 'PAST_DUE') return <Badge variant="red">RENT DUE</Badge>;
  if (n.cancel_at_period_end) return <Badge variant="yellow">ENDS {n.current_period_end ? fmtDate(n.current_period_end).toUpperCase() : ''}</Badge>;
  if (n.status === 'READY_TO_TEST') return <Badge variant="yellow">TEST NEEDED</Badge>;
  if (n.status !== 'ACTIVE') return <Badge variant="gray">{n.status}</Badge>;
  return <Badge variant="green">ACTIVE</Badge>;
};

export const PortalNumbersPage: React.FC = () => {
  const [numbers, setNumbers] = useState<PortalNumber[] | null>(null);
  const [pricing, setPricing] = useState<NumberPrice[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [balance, setBalance] = useState<number | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [buyOpen, setBuyOpen] = useState(false);
  const [verification, setVerification] = useState<VerificationStatus>('NOT_STARTED');
  const [contactPhone, setContactPhone] = useState<string | null>(null);
  const [activating, setActivating] = useState<PortalNumber | null>(null);

  const load = () =>
    Promise.all([portalService.numbers(), portalService.agents(), portalService.wallet()])
      .then(([n, a, w]) => {
        setNumbers(n.numbers);
        setPricing(n.pricing);
        setVerification(n.verification_status);
        setContactPhone(n.contact_phone);
        setAgents(a);
        setBalance(w.balance_inr);
      })
      .catch((err) => setLoadError(err.message || 'Could not load phone numbers.'));

  useEffect(() => {
    load();
  }, []);

  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      await load();
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  if (loadError) return <ErrorState message={loadError} onRetry={() => window.location.reload()} />;
  if (!numbers) return <LoadingState message="Loading phone numbers..." />;

  const active = numbers.filter((n) => n.status !== 'RELEASED');
  const released = numbers.filter((n) => n.status === 'RELEASED');
  const pastDue = active.filter((n) => n.rental_status === 'PAST_DUE');

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Phone numbers</h1>
          <p className="text-xs text-slate-400">Numbers your AI employees answer and call from. Rent is charged monthly from your wallet.</p>
        </div>
        {verification === 'VERIFIED' ? (
          <Button variant="primary" onClick={() => setBuyOpen(true)} disabled={pricing.length === 0}>
            <Plus className="mr-1.5 h-4 w-4" /> Get a number
          </Button>
        ) : (
          <Link to="/portal/verification">
            <Button variant="primary" leftIcon={<ShieldCheck className="h-4 w-4" />}>
              {verification === 'NOT_STARTED' ? 'Verify your business' : 'Finish verification'}
            </Button>
          </Link>
        )}
      </div>

      {verification !== 'VERIFIED' && (
        <div className="flex items-start gap-3 rounded-lg border border-[#143c49] bg-[#071c22] p-4 text-sm text-slate-200">
          {verification === 'IN_PROGRESS' ? <Clock className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" /> : <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[#00df8f]" />}
          <div className="space-y-1">
            {verification === 'NOT_STARTED' ? (
              <>
                <p className="font-semibold">Step 1: verify your business (one time)</p>
                <p className="text-xs text-slate-400">Indian telecom rules require a verified owner for every phone number. Enter your PAN and GSTIN, or verify Aadhaar through DigiLocker: it takes a few minutes and is checked instantly.</p>
              </>
            ) : (
              <>
                <p className="font-semibold">Finish verifying your business</p>
                <p className="text-xs text-slate-400">You've started. Complete the remaining documents and you can get numbers right away.</p>
                <Link to="/portal/verification" className="text-xs font-semibold underline">Continue verification</Link>
              </>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}
      {pastDue.map((n) => (
        <div key={n.id} className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          Rent of {inr(n.monthly_rent_inr || 0)} for {n.phone_number} couldn't be charged.
          {n.grace_ends_at ? ` Top up your wallet by ${fmtDate(n.grace_ends_at)} or the number will be released.` : ''}
        </div>
      ))}

      <Card title={`Your numbers (${active.length})`} noPadding>
        {active.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-12 text-center text-xs text-slate-400">
            <Phone className="h-8 w-8 text-slate-600" />
            <p>You don't have a phone number yet. Get one so customers can call your AI employee, and so it can call them.</p>
            {verification === 'VERIFIED' ? (
              <Button variant="primary" size="sm" onClick={() => setBuyOpen(true)} disabled={pricing.length === 0}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Get a number
              </Button>
            ) : (
              <span className="flex items-center gap-1 text-slate-500"><BadgeCheck className="h-3.5 w-3.5" /> Available once your business is verified</span>
            )}
          </div>
        ) : (
          <div className="divide-y divide-[#151a26]">
            {active.map((n) => (
              <div key={n.id} className="grid grid-cols-1 gap-3 px-5 py-4 text-xs md:grid-cols-[1.3fr_1.5fr_1fr_auto] md:items-center">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-slate-100">{n.phone_number}</span>
                    <NumberStatus n={n} />
                  </div>
                  <span className="text-slate-500">{n.number_type ? NUMBER_TYPE_LABELS[n.number_type] : 'Phone number'}</span>
                </div>
                <label className="block space-y-1">
                  <span className="text-[11px] text-slate-500">Answered by</span>
                  <select
                    className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100"
                    value={n.agent_id || ''}
                    disabled={busy === 'assign-' + n.id || (n.status !== 'ACTIVE' && n.status !== 'READY_TO_TEST')}
                    onChange={(e) => run('assign-' + n.id, () => portalService.assignNumber(n.id, e.target.value || null))}
                  >
                    <option value="">No AI employee (calls rejected)</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id} disabled={!a.published}>
                        {a.name}{a.published ? '' : ' (not published)'}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="text-slate-400">
                  {n.monthly_rent_inr != null ? (
                    <>
                      <span className="font-mono text-slate-200">{inr(n.monthly_rent_inr)}</span>/month
                      {n.current_period_end && (
                        <span className="block text-[11px] text-slate-500">
                          {n.cancel_at_period_end ? 'Released on ' : 'Next rent '}
                          {fmtDate(n.current_period_end)}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-slate-500">Included</span>
                  )}
                </div>
                <div className="flex flex-wrap justify-end gap-1.5">
                  {n.status === 'READY_TO_TEST' && (
                    <Button size="sm" variant="primary" leftIcon={<PhoneOutgoing className="h-3.5 w-3.5" />} onClick={() => setActivating(n)}>
                      Test &amp; activate
                    </Button>
                  )}
                  {n.monthly_rent_inr != null &&
                    (n.cancel_at_period_end ? (
                      <Button size="sm" variant="secondary" isLoading={busy === 'keep-' + n.id} onClick={() => run('keep-' + n.id, () => portalService.keepNumber(n.id))}>
                        Keep number
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        isLoading={busy === 'release-' + n.id}
                        onClick={() => {
                          if (window.confirm(`Stop renting ${n.phone_number}? It stays yours until the end of the month you've paid for.`)) {
                            run('release-' + n.id, () => portalService.releaseNumber(n.id));
                          }
                        }}
                      >
                        Release
                      </Button>
                    ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {released.length > 0 && (
        <Card title="Released numbers" subtitle="No longer yours; kept here for your call history" noPadding>
          <div className="divide-y divide-[#151a26]">
            {released.map((n) => (
              <div key={n.id} className="flex items-center justify-between px-5 py-3 text-xs text-slate-500">
                <span className="font-mono">{n.phone_number}</span>
                <NumberStatus n={n} />
              </div>
            ))}
          </div>
        </Card>
      )}

      <BuyNumberModal
        isOpen={buyOpen}
        onClose={() => setBuyOpen(false)}
        pricing={pricing}
        walletBalance={balance}
        topUpLink="/portal/billing"
        search={(type, region) => portalService.availableNumbers(type, region)}
        buy={(number, type) => portalService.buyNumber(number, type)}
        onBought={(bought) => {
          load();
          if (bought?.id) setActivating(bought as PortalNumber);
        }}
      />
      <NumberActivationModal
        isOpen={activating !== null}
        onClose={() => {
          setActivating(null);
          load();
        }}
        number={activating}
        agents={agents}
        contactPhone={contactPhone}
        onChanged={load}
      />
    </div>
  );
};
