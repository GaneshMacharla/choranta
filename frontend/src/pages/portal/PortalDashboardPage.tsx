import React, { useEffect, useState } from 'react';
import { AlertTriangle, PhoneCall, Clock, IndianRupee, Wallet } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { inr, PaymentInstructions, PortalSummary, portalService } from '../../services/portal';

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
  const [summary, setSummary] = useState<PortalSummary | null>(null);
  const [payment, setPayment] = useState<PaymentInstructions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([portalService.summary(), portalService.paymentInstructions()])
      .then(([s, p]) => {
        setSummary(s);
        setPayment(p);
      })
      .catch((err) => setError(err.message || 'Could not load your dashboard.'));
  }, []);

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!summary) return <LoadingState message="Loading dashboard..." />;

  const { wallet, month } = summary;
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-bold">{summary.client_name}</h1>
        <p className="text-xs text-slate-400">Welcome back, {summary.user_name}</p>
      </div>

      {(wallet.low_balance || wallet.calls_blocked) && (
        <div className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${wallet.calls_blocked ? 'border-rose-800/60 bg-rose-950/40 text-rose-200' : 'border-amber-700/60 bg-amber-950/30 text-amber-200'}`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {wallet.calls_blocked
              ? 'Your wallet balance is exhausted, so your AI employee can’t take or make calls. Recharge to resume.'
              : `Low balance: ${inr(wallet.balance_inr)} left (alert below ${inr(wallet.low_balance_threshold_inr, 0)}). Recharge soon to avoid interruptions.`}
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat icon={<Wallet className="h-4 w-4 text-[#00df8f]" />} label="Wallet balance" value={inr(wallet.balance_inr)} hint="excluding GST" />
        <Stat icon={<PhoneCall className="h-4 w-4 text-indigo-400" />} label="Calls this month" value={String(month.calls)} />
        <Stat icon={<Clock className="h-4 w-4 text-sky-400" />} label="Minutes this month" value={month.minutes.toFixed(1)} />
        <Stat icon={<IndianRupee className="h-4 w-4 text-amber-400" />} label="Spend this month" value={inr(month.spend_inr)} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Call minutes" subtitle="Last 30 days">
          <DailyBars data={summary.daily} metric="minutes" color="bg-sky-500/70" format={(v) => `${v} min`} />
        </Card>
        <Card title="Spend" subtitle="Last 30 days, charged from your wallet">
          <DailyBars data={summary.daily} metric="spend_inr" color="bg-amber-500/70" format={(v) => inr(v)} />
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
