import React from 'react';
import { Badge } from '../common/Badge';
import { creditsLabel, Subscription } from '../../services/plans';

const fmtDate = (value: string) => new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

export const SubscriptionStatusBadge: React.FC<{ subscription: Subscription }> = ({ subscription: s }) => {
  if (s.status === 'ACTIVE') return <Badge variant={s.cancel_at_period_end ? 'yellow' : 'green'}>{s.cancel_at_period_end ? 'ENDS AT PERIOD END' : 'ACTIVE'}</Badge>;
  if (s.status === 'PAST_DUE') return <Badge variant={s.in_grace ? 'yellow' : 'red'}>{s.in_grace ? 'PAYMENT DUE' : 'EXPIRED'}</Badge>;
  return <Badge variant="gray">CANCELLED</Badge>;
};

/** Plan name, period and a credits-used bar. */
export const PlanUsageBar: React.FC<{ subscription: Subscription }> = ({ subscription: s }) => {
  const pct = s.monthly_credits > 0 ? Math.min(100, (s.credits_used / s.monthly_credits) * 100) : 100;
  const minutesLeft = s.avg_credits_per_minute > 0 ? Math.floor(s.credits_remaining / s.avg_credits_per_minute) : 0;
  const barColor = pct >= 100 ? 'bg-rose-500' : pct >= 80 ? 'bg-amber-400' : 'bg-[#00df8f]';
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold text-slate-100">{s.plan?.name ?? 'Plan'}</span>
            <SubscriptionStatusBadge subscription={s} />
          </div>
          <p className="mt-0.5 text-xs text-slate-400">
            {fmtDate(s.current_period_start)} – {fmtDate(s.current_period_end)}
            {s.status === 'ACTIVE' && ` · ${s.days_left} day${s.days_left === 1 ? '' : 's'} left`}
            {s.renewed_ahead && ' · next month paid'}
          </p>
        </div>
        <div className="text-right text-xs">
          <span className="font-mono text-lg font-bold text-slate-100">{creditsLabel(s.credits_remaining)}</span>
          <span className="block text-slate-500">
            left of {creditsLabel(s.monthly_credits)} · about {minutesLeft.toLocaleString('en-IN')} min
          </span>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[#0f2a33]">
        <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      {s.plan && (
        <p className="text-[11px] text-slate-500">
          Each call uses credits for what it actually costs (~{Math.round(s.avg_credits_per_minute)} per minute) · after plan credits run out, bought credits are used
          {s.plan.max_concurrent_calls ? ` · up to ${s.plan.max_concurrent_calls} call${s.plan.max_concurrent_calls === 1 ? '' : 's'} at a time` : ''}
        </p>
      )}
    </div>
  );
};

export { fmtDate };
