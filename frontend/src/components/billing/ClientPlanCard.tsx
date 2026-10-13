import React, { useEffect, useState } from 'react';
import { Layers, AlertTriangle, Phone } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import { PlanUsageBar } from './PlanUsageBar';
import { BuyNumberModal } from './BuyNumberModal';
import { inr } from '../../services/portal';
import { CallUsage, creditsLabel, minutesLabel, NumberPrice, Plan, plansService, Subscription } from '../../services/plans';

const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100';

/** Admin view of a client's monthly plan: usage, offline plan payments, cancellation. */
export const ClientPlanCard: React.FC<{ clientId: string; onChange?: () => void }> = ({ clientId, onChange }) => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [subscription, setSubscription] = useState<Subscription | null | undefined>(undefined);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [usage, setUsage] = useState<CallUsage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [planId, setPlanId] = useState('');
  const [reference, setReference] = useState('');
  const [amount, setAmount] = useState('');
  const [numberOpen, setNumberOpen] = useState(false);
  const [numberPricing, setNumberPricing] = useState<NumberPrice[]>([]);

  const load = async () => {
    try {
      const [s, p, u] = await Promise.all([plansService.subscription(clientId), plansService.list(), plansService.usage(clientId)]);
      setSubscription(s.subscription);
      setPlans(p);
      setUsage(u);
    } catch (err: any) {
      setError(err.message || 'Could not load the plan.');
    }
  };

  useEffect(() => {
    load();
  }, [clientId]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setAssignOpen(false);
      await load();
      onChange?.();
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  const openAssign = () => {
    setPlanId(subscription?.plan?.id || plans[0]?.id || '');
    setReference('');
    setAmount('');
    setError(null);
    setAssignOpen(true);
  };

  const selectedPlan = plans.find((p) => p.id === planId);
  const sameActivePlan = subscription?.status === 'ACTIVE' && subscription.plan?.id === planId;

  return (
    <Card
      title="Plan"
      subtitle="Monthly plan with included minutes; extra minutes are charged from the wallet"
      action={
        isAdmin && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => plansService.numberPricing().then((p) => { setNumberPricing(p); setNumberOpen(true); }).catch((err) => setError(err.message))}
            >
              <Phone className="mr-1 h-3.5 w-3.5" /> Buy number
            </Button>
            <Button size="sm" variant="primary" onClick={openAssign} disabled={plans.length === 0}>
              <Layers className="mr-1 h-3.5 w-3.5" /> {subscription ? 'Renew / change plan' : 'Assign plan'}
            </Button>
          </div>
        )
      }
    >
      <div className="space-y-4 text-xs">
        {error && !assignOpen && (
          <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        {subscription === undefined ? (
          <p className="text-slate-500">Loading plan...</p>
        ) : subscription === null ? (
          <p className="text-slate-400">
            No plan. This client's calls use bought credits.
            {plans.length === 0 && (
              <>
                {' '}
                <Link to="/plans" className="text-[#00df8f] hover:underline">Create a plan</Link> first.
              </>
            )}
          </p>
        ) : (
          <>
            <PlanUsageBar subscription={subscription} />
            {isAdmin && subscription.status === 'ACTIVE' && (
              <div className="flex justify-end">
                <Button
                  size="sm"
                  variant="ghost"
                  isLoading={busy}
                  onClick={() => run(() => plansService.setCancelAtPeriodEnd(clientId, !subscription.cancel_at_period_end))}
                >
                  {subscription.cancel_at_period_end ? 'Keep plan after this period' : 'Cancel at period end'}
                </Button>
              </div>
            )}
          </>
        )}

        {usage.length > 0 && (
          <div className="rounded border border-[#1b2030]">
            <p className="border-b border-[#1b2030] px-4 py-2 font-semibold text-slate-300">Recent call usage</p>
            <div className="max-h-64 overflow-y-auto">
              {usage.slice(0, 30).map((u) => (
                <div key={u.call_id} className="flex items-center justify-between gap-3 border-b border-[#151a26] px-4 py-2 last:border-0">
                  <span className="text-slate-500">{new Date(u.created_at).toLocaleString('en-IN')}</span>
                  <span className="font-mono text-slate-300">{minutesLabel(u.billed_minutes)}</span>
                  <span className="text-slate-400">
                    {u.plan_credits > 0 ? `${creditsLabel(u.plan_credits)} from plan` : 'Bought credits'}
                  </span>
                  <span className={`font-mono ${u.wallet_credits > 0 ? 'text-amber-300' : 'text-slate-500'}`}>
                    {u.wallet_credits > 0 ? `-${creditsLabel(u.wallet_credits)}` : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <Modal
        isOpen={assignOpen}
        onClose={() => setAssignOpen(false)}
        title={subscription ? 'Renew or change plan' : 'Assign plan'}
        description="Record a plan payment the client made by bank transfer or UPI. A GST invoice is issued; the wallet isn't credited."
      >
        <div className="space-y-3 text-xs">
          {error && (
            <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
            </div>
          )}
          <label className="block space-y-1">
            <span className="text-slate-300">Plan</span>
            <select className={inputClass} value={planId} onChange={(e) => setPlanId(e.target.value)}>
              {plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {inr(p.monthly_price_with_gst_inr)} incl. GST · {creditsLabel(p.monthly_credits)}
                </option>
              ))}
            </select>
          </label>
          {selectedPlan && (
            <p className="rounded border border-[#1b2030] bg-black/30 p-2.5 text-slate-400">
              {sameActivePlan
                ? 'Same plan as now: this pays for the next month, which starts when the current period ends.'
                : subscription
                ? 'A different plan starts today with fresh credits. Unused credits on the current plan are dropped.'
                : 'The plan starts today.'}
            </p>
          )}
          <label className="block space-y-1">
            <span className="text-slate-300">Amount received (₹, incl. GST)</span>
            <input
              type="number"
              min={1}
              className={inputClass}
              value={amount}
              placeholder={selectedPlan ? String(selectedPlan.monthly_price_with_gst_inr) : ''}
              onChange={(e) => setAmount(e.target.value)}
            />
            <span className="block text-[11px] text-slate-500">Leave empty to use the plan price plus GST</span>
          </label>
          <label className="block space-y-1">
            <span className="text-slate-300">Payment reference (UTR / UPI ref)</span>
            <input className={inputClass} value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setAssignOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!planId || (subscription?.renewed_ahead && sameActivePlan)}
              isLoading={busy}
              onClick={() => run(() => plansService.assign(clientId, planId, reference, Number(amount) || undefined))}
            >
              Record & issue invoice
            </Button>
          </div>
        </div>
      </Modal>
      <BuyNumberModal
        isOpen={numberOpen}
        onClose={() => setNumberOpen(false)}
        pricing={numberPricing}
        search={(type, region) => plansService.searchNumbersForClient(clientId, type, region)}
        buy={(number, type) => plansService.buyNumberForClient(clientId, number, type)}
        onBought={() => onChange?.()}
      />
    </Card>
  );
};
