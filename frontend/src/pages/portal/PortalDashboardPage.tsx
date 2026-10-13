import React, { useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight, Bot, PhoneCall, Clock, IndianRupee, Wallet } from 'lucide-react';
import { portalAgentRequestsService } from '../../services/agentRequests';
import { Card } from '../../components/common/Card';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { inr, PaymentInstructions, PortalSummary, portalService } from '../../services/portal';
import { creditsLabel, plansService } from '../../services/plans';
import { useAuth } from '../../context/AuthContext';
import { hasSkippedPlanChoice } from './PortalPlansPage';

const Stat: React.FC<{ icon: React.ReactNode; label: string; value: string; hint?: string }> = ({ icon, label, value, hint }) => (
  <div className="rounded-xl border border-[#1b2030] bg-[#0c0e14] p-4">
    <div className="flex items-center justify-between text-xs text-slate-400">
      <span>{label}</span>
      {icon}
    </div>
    <p className="mt-2 font-mono text-2xl font-bold text-slate-100">{value}</p>
    {hint && <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
  </div>
);

/** 30-day bars for one metric (no chart library needed). */
const DailyBars: React.FC<{ data: PortalSummary['daily']; metric: 'minutes' | 'spend_inr'; color: string; format: (v: number) => string }> = ({
  data,
  metric,
  color,
  format,
}) => {
  const max = Math.max(1, ...data.map((d) => d[metric]));
  return (
    <div>
      <div className="flex h-32 items-end gap-[3px]">
        {data.map((d) => (
          <div key={d.date} className="group relative flex-1">
            <div className={`w-full rounded-t ${color}`} style={{ height: `${Math.max(2, (d[metric] / max) * 128)}px`, opacity: d[metric] ? 1 : 0.25 }} />
            <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded bg-black/90 px-2 py-1 text-[10px] text-slate-200 group-hover:block">
              {new Date(d.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}: {format(d[metric])}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>{new Date(data[0]?.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
        <span>Today</span>
      </div>
    </div>
  );
};

export const PortalDashboardPage: React.FC = () => {
  const { user } = useAuth();
  const [summary, setSummary] = useState<PortalSummary | null>(null);
  const [payment, setPayment] = useState<PaymentInstructions | null>(null);
  const [planCount, setPlanCount] = useState(0);
  const [hasEmployee, setHasEmployee] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([portalService.summary(), portalService.paymentInstructions(), plansService.list(), portalAgentRequestsService.me()])
      .then(([s, p, plans, me]) => {
        setSummary(s);
        setPayment(p);
        setPlanCount(plans.length);
        setHasEmployee(me.has_ai_employee);
      })
      .catch((err) => setError(err.message || 'Could not load your dashboard.'));
  }, []);

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!summary) return <LoadingState message="Loading dashboard..." />;

  const { wallet, month, subscription: plan } = summary;
  // Clients who have never had a plan choose one first (unless they chose pay-as-you-go)
  if (!plan && planCount > 0 && !hasSkippedPlanChoice(user?.id)) return <Navigate to="/portal/plans" replace />;
  const planCoversCalls = !!plan?.usable && plan.credits_remaining > 0;
  const showLowBalance = wallet.low_balance && !planCoversCalls;
  const hasPaid = !!plan?.usable || wallet.balance_inr > 0;
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-bold">{summary.client_name}</h1>
        <p className="text-xs text-slate-400">Welcome back, {summary.user_name}</p>
      </div>

      {hasPaid && !hasEmployee && (
        <div className="flex flex-col gap-4 rounded-xl border border-[#0a4d39] bg-gradient-to-r from-[#052b20] to-[#071c22] p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#00df8f]/15 text-[#00df8f]">
              <Bot className="h-5 w-5" />
            </span>
            <div>
              <p className="text-base font-semibold text-slate-100">Create your first AI employee</p>
              <p className="text-sm text-slate-400">Tell us your company name, type of business and a name for it. We'll set up the rest.</p>
            </div>
          </div>
          <Link
            to="/portal/employees"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md bg-[#00df8f] px-4 py-2 text-sm font-semibold text-[#04110c] hover:bg-[#00c97f]"
          >
            Get started <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}

      {(showLowBalance || wallet.calls_blocked) && (
        <div className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${wallet.calls_blocked ? 'border-rose-800/60 bg-rose-950/40 text-rose-200' : 'border-amber-700/60 bg-amber-950/30 text-amber-200'}`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {wallet.calls_blocked
              ? wallet.calls_blocked_reason || 'Your AI employee can’t take or make calls right now.'
              : `Low on credits: ${creditsLabel(wallet.balance_inr)} left (alert below ${creditsLabel(wallet.low_balance_threshold_inr)}). Buy credits soon to avoid interruptions.`}
          </span>
          <Link to={plan ? '/portal/billing' : '/portal/plans'} className="ml-auto shrink-0 font-semibold underline-offset-2 hover:underline">
            {plan ? 'Buy credits' : 'Choose a plan'}
          </Link>
        </div>
      )}

      {summary.numbers_past_due.map((n) => (
        <div key={n.phone_number} className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Rent of {inr(n.monthly_rent_inr)} for {n.phone_number} is overdue.
            {n.grace_ends_at && ` Top up your wallet by ${new Date(n.grace_ends_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} or the number will be released.`}
          </span>
        </div>
      ))}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat icon={<Wallet className="h-4 w-4 text-[#00df8f]" />} label="Bought credits" value={creditsLabel(wallet.balance_inr)} hint="never expire · 1 credit = ₹1" />
        <Stat icon={<PhoneCall className="h-4 w-4 text-indigo-400" />} label="Calls this month" value={String(month.calls)} />
        {plan?.usable ? (
          <Stat
            icon={<Clock className="h-4 w-4 text-sky-400" />}
            label="Plan credits left"
            value={creditsLabel(plan.credits_remaining)}
            hint={`of ${plan.monthly_credits.toLocaleString('en-IN')} · reset ${new Date(plan.current_period_end).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`}
          />
        ) : (
          <Stat icon={<Clock className="h-4 w-4 text-sky-400" />} label="Minutes this month" value={month.minutes.toFixed(1)} />
        )}
        <Stat icon={<IndianRupee className="h-4 w-4 text-amber-400" />} label="Bought credits used" value={creditsLabel(month.spend_inr)} hint="this month" />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Call minutes" subtitle="Last 30 days">
          <DailyBars data={summary.daily} metric="minutes" color="bg-sky-500/70" format={(v) => `${v} min`} />
        </Card>
        <Card title="Bought credits used" subtitle="Last 30 days">
          <DailyBars data={summary.daily} metric="spend_inr" color="bg-amber-500/70" format={(v) => creditsLabel(v)} />
        </Card>
      </div>

      {payment && (payment.upi_id || payment.bank_details) && (
        <Card title="How to recharge" subtitle={`Pay by UPI or bank transfer; GST @ ${payment.gst_rate_percent}% applies`}>
          <div className="space-y-2 text-xs text-slate-300">
            {payment.upi_id && (
              <p>
                <span className="text-slate-500">UPI ID: </span>
                <span className="font-mono text-[#00df8f]">{payment.upi_id}</span>
              </p>
            )}
            {payment.bank_details && <p className="whitespace-pre-line">{payment.bank_details}</p>}
            <p className="text-slate-500">{payment.note}</p>
          </div>
        </Card>
      )}
    </div>
  );
};
