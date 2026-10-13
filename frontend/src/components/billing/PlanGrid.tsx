import React from 'react';
import { Check } from 'lucide-react';
import { Button } from '../common/Button';
import { inr } from '../../services/portal';
import { creditsLabel, Plan, Subscription } from '../../services/plans';
import { fmtDate } from './PlanUsageBar';

const planAction = (plan: Plan, sub: Subscription | null): { label: string; disabled: boolean } => {
  if (!sub || sub.status === 'CANCELLED') return { label: 'Choose plan', disabled: false };
  if (sub.plan?.id !== plan.id) return { label: 'Switch to this plan', disabled: false };
  if (sub.renewed_ahead) return { label: 'Next month paid', disabled: true };
  if (sub.status === 'PAST_DUE') return { label: 'Renew now', disabled: false };
  return { label: 'Pay next month', disabled: false };
};

/**
 * Typical per-minute price range (excl. GST), from the recent average credits per call minute: minutes paid
 * with plan credits cost the plan fee per credit, minutes paid with bought credits cost ₹1 per credit.
 */
export const perMinuteRange = (plan: Plan): string => {
  const rates = [plan.avg_credits_per_minute];
  if (plan.monthly_credits > 0) rates.push((plan.monthly_price_inr / plan.monthly_credits) * plan.avg_credits_per_minute);
  const low = Math.round(Math.min(...rates));
  const high = Math.round(Math.max(...rates));
  return low === high ? `₹${low}` : `₹${low}–${high}`;
};

interface PlanGridProps {
  plans: Plan[];
  subscription: Subscription | null;
  online: boolean;
  gstRate: number;
  busyPlanId: string | null;
  onChoose: (plan: Plan) => void;
}

/** Monthly plan cards with the right action for the client's current subscription. */
export const PlanGrid: React.FC<PlanGridProps> = ({ plans, subscription: sub, online, gstRate, busyPlanId, onChoose }) => (
  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
    {plans.map((plan) => {
      const current = sub?.plan?.id === plan.id && sub.status !== 'CANCELLED';
      const action = planAction(plan, sub);
      return (
        <div
          key={plan.id}
          className={`flex flex-col rounded-lg border p-5 ${current ? 'border-[#00df8f]/60 bg-[#06221c]/60' : 'border-[#143c49] bg-[#091b22]'}`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-base font-semibold text-slate-100">{plan.name}</span>
            {current && <span className="text-[10px] font-semibold uppercase tracking-wider text-[#00df8f]">Current</span>}
          </div>
          {plan.description && <p className="mt-1 text-xs text-slate-400">{plan.description}</p>}
          <div className="mt-4">
            <span className="font-mono text-2xl font-bold text-slate-100">{inr(plan.monthly_price_inr, 0)}</span>
            <span className="text-xs text-slate-500"> / month + {gstRate}% GST</span>
            <div className="mt-1 text-xs font-medium text-[#00df8f]">≈ {perMinuteRange(plan)} per minute</div>
          </div>
          <ul className="mt-4 flex-1 space-y-1.5 text-xs text-slate-300">
            {[
              `${creditsLabel(plan.monthly_credits)} every month`,
              `About ${plan.approx_minutes.toLocaleString('en-IN')} call minutes (a minute uses ~${Math.round(plan.avg_credits_per_minute)} credits)`,
              'Unused plan credits expire at the end of the month',
              plan.max_concurrent_calls
                ? `Up to ${plan.max_concurrent_calls} call${plan.max_concurrent_calls === 1 ? '' : 's'} at a time`
                : 'No limit on calls at a time',
            ].map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#00df8f]" /> {line}
              </li>
            ))}
          </ul>
          <Button
            className="mt-5"
            variant={current ? 'secondary' : 'primary'}
            disabled={!online || action.disabled}
            isLoading={busyPlanId === plan.id}
            onClick={() => onChoose(plan)}
          >
            {action.label} · {inr(plan.monthly_price_with_gst_inr, 0)}
          </Button>
          {current && sub?.status === 'ACTIVE' && !sub.renewed_ahead && (
            <p className="mt-2 text-center text-[11px] text-slate-500">Next month starts {fmtDate(sub.current_period_end)}</p>
          )}
          {!current && sub && sub.status !== 'CANCELLED' && (
            <p className="mt-2 text-center text-[11px] text-slate-500">Starts today; unused minutes on your current plan end</p>
          )}
        </div>
      );
    })}
  </div>
);
