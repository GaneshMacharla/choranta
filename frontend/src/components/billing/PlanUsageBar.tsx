import React from 'react';
import { Badge } from '../common/Badge';
import { minutesLabel, Subscription } from '../../services/plans';

const fmtDate = (value: string) => new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

export const SubscriptionStatusBadge: React.FC<{ subscription: Subscription }> = ({ subscription: s }) => {
  if (s.status === 'ACTIVE') return <Badge variant={s.cancel_at_period_end ? 'yellow' : 'green'}>{s.cancel_at_period_end ? 'ENDS AT PERIOD END' : 'ACTIVE'}</Badge>;
  if (s.status === 'PAST_DUE') return <Badge variant={s.in_grace ? 'yellow' : 'red'}>{s.in_grace ? 'PAYMENT DUE' : 'EXPIRED'}</Badge>;
  return <Badge variant="gray">CANCELLED</Badge>;
};

/** Plan name, period and a minutes-used bar. */
export const PlanUsageBar: React.FC<{ subscription: Subscription }> = ({ subscription: s }) => {
  const pct = s.included_minutes > 0 ? Math.min(100, (s.minutes_used / s.included_minutes) * 100) : 100;
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
          <span className="font-mono text-lg font-bold text-slate-100">{minutesLabel(s.minutes_remaining)}</span>
          <span className="block text-slate-500">left of {minutesLabel(s.included_minutes)}</span>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[#0f2a33]">
        <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      {s.plan && (
        <p className="text-[11px] text-slate-500">
          Extra minutes ₹{s.plan.overage_per_minute_inr}/min from your wallet
          {s.plan.max_concurrent_calls ? ` · up to ${s.plan.max_concurrent_calls} call${s.plan.max_concurrent_calls === 1 ? '' : 's'} at a time` : ''}
        </p>
      )}
    </div>
  );
};

export { fmtDate };
