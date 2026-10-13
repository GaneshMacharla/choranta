import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Download, Plus, Wallet as WalletIcon } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { Modal } from '../../components/common/Modal';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { inr, InvoiceSummary, portalService, Wallet } from '../../services/portal';
import { Plan, plansService, Subscription } from '../../services/plans';
import { WalletLedger } from '../../components/billing/WalletLedger';
import { fmtDate, PlanUsageBar } from '../../components/billing/PlanUsageBar';
import { payWithRazorpay } from '../../components/billing/razorpayCheckout';
import { PlanGrid } from '../../components/billing/PlanGrid';

type PortalPlanInfo = Awaited<ReturnType<typeof portalService.subscription>>;

export const PortalBillingPage: React.FC = () => {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [info, setInfo] = useState<PortalPlanInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [topupOpen, setTopupOpen] = useState(false);
  const [topupAmount, setTopupAmount] = useState('');

  const load = () =>
    Promise.all([portalService.wallet(), portalService.invoices(), plansService.list(), portalService.subscription()])
      .then(([w, i, p, s]) => {
        setWallet(w);
        setInvoices(i);
        setPlans(p);
        setInfo(s);
      })
      .catch((err) => setLoadError(err.message || 'Could not load billing.'));

  useEffect(() => {
    load();
  }, []);

  const pay = async (key: string, body: Parameters<typeof portalService.createOrder>[0], successMessage: string) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const order = await portalService.createOrder(body);
      const paid = await payWithRazorpay(order);
      if (paid) {
        setTopupOpen(false);
        setNotice(successMessage);
        await load();
      }
    } catch (err: any) {
      setError(err.message || 'Payment could not be completed.');
    } finally {
      setBusy(null);
    }
  };

  const download = async (invoice: InvoiceSummary) => {
    setBusy('pdf-' + invoice.id);
    try {
      await portalService.downloadInvoice(invoice);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };

  if (loadError) return <ErrorState message={loadError} onRetry={() => window.location.reload()} />;
  if (!wallet || !info) return <LoadingState message="Loading billing..." />;

  const sub: Subscription | null = info.subscription;
  const online = info.online_payments;
  const gstRate = info.gst_rate_percent;
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-xl font-bold">Billing</h1>
        <p className="text-sm">
          Wallet balance: <span className="font-mono font-bold text-[#00df8f]">{inr(wallet.balance_inr)}</span>
          <span className="ml-1 text-xs text-slate-500">(excl. GST)</span>
        </p>
      </div>

      {notice && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-800/60 bg-emerald-950/30 p-3 text-xs text-emerald-200">
          <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" /> {notice}
        </div>
      )}
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}
      {sub?.status === 'PAST_DUE' && (
        <div className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${sub.in_grace ? 'border-amber-700/60 bg-amber-950/30 text-amber-200' : 'border-rose-800/60 bg-rose-950/40 text-rose-200'}`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {sub.in_grace && sub.grace_ends_at
            ? `Your ${sub.plan?.name} plan ended on ${fmtDate(sub.current_period_end)}. Renew by ${fmtDate(sub.grace_ends_at)} to keep your AI employee taking calls.`
            : `Your ${sub.plan?.name} plan has expired, so calls are paused. Renew to resume.`}
        </div>
      )}
      {wallet.calls_blocked && sub?.status !== 'PAST_DUE' && wallet.calls_blocked_reason && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {wallet.calls_blocked_reason}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <Card title="Your plan" className="lg:col-span-7" bodyClassName="flex flex-col justify-center">
          {sub && sub.status !== 'CANCELLED' ? (
            <PlanUsageBar subscription={sub} />
          ) : (
            <p className="text-xs text-slate-400">
              You're on pay-as-you-go: each call is charged from your wallet. Pick a monthly plan below to get included minutes at a lower rate.
            </p>
          )}
        </Card>

        <Card
          title="Wallet"
          subtitle={sub ? 'Pays for minutes beyond your plan' : 'Pays for your calls'}
          className="lg:col-span-5"
          bodyClassName="flex flex-col justify-between gap-4"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#0f3d33] bg-[#06221c] text-[#00df8f]">
              <WalletIcon className="h-5 w-5" />
            </div>
            <div>
              <span className="block font-mono text-2xl font-bold text-slate-100">{inr(wallet.balance_inr)}</span>
              <span className="text-xs text-slate-500">excluding GST</span>
            </div>
          </div>
          <Button
            variant="secondary"
            disabled={!online}
            title={online ? '' : 'Online payments are not set up yet'}
            onClick={() => {
              setTopupAmount('');
              setError(null);
              setTopupOpen(true);
            }}
          >
            <Plus className="mr-1.5 h-4 w-4" /> Top up wallet
          </Button>
        </Card>
      </div>

      {plans.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-200">Monthly plans</h2>
            {!online && <span className="text-xs text-amber-300">Online payment isn't available yet. Contact Choranta to subscribe.</span>}
          </div>
          <PlanGrid
            plans={plans}
            subscription={sub}
            online={online}
            gstRate={gstRate}
            busyPlanId={busy?.startsWith('plan-') ? busy.slice(5) : null}
            onChoose={(plan) =>
              pay('plan-' + plan.id, { purpose: 'SUBSCRIPTION', plan_id: plan.id }, `Payment received. Your ${plan.name} plan is set, and the GST invoice is below.`)
            }
          />
        </div>
      )}

      <Card title="Invoices" subtitle="GST tax invoices for your plans and wallet top-ups" noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#1f2433] text-slate-400">
              <tr>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">For</th>
                <th className="px-4 py-3">Taxable</th>
                <th className="px-4 py-3">GST</th>
                <th className="px-4 py-3">Total</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-500">No invoices yet.</td>
                </tr>
              )}
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-b border-[#151a26] text-slate-300">
                  <td className="px-4 py-3 font-mono">{inv.number}</td>
                  <td className="px-4 py-3">{new Date(inv.issue_date).toLocaleDateString('en-IN')}</td>
                  <td className="max-w-[16rem] truncate px-4 py-3 text-slate-400" title={inv.description}>
                    {inv.description.replace('AI voice agent services - ', '')}
                  </td>
                  <td className="px-4 py-3 font-mono">{inr(inv.taxable_inr)}</td>
                  <td className="px-4 py-3 font-mono">{inr(inv.cgst_inr + inv.sgst_inr + inv.igst_inr)}</td>
                  <td className="px-4 py-3 font-mono font-semibold">{inr(inv.total_inr)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button size="sm" variant="secondary" isLoading={busy === 'pdf-' + inv.id} onClick={() => download(inv)}>
                      <Download className="mr-1 h-3.5 w-3.5" /> PDF
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Wallet activity" subtitle="Top-ups and call charges" noPadding>
        <WalletLedger transactions={wallet.transactions} />
      </Card>

      <Modal
        isOpen={topupOpen}
        onClose={() => setTopupOpen(false)}
        title="Top up wallet"
        description={`Pay any amount from ${inr(info.min_topup_inr, 0)}, GST included. Your wallet is credited with the amount excluding GST, and a GST invoice is issued.`}
      >
        <div className="space-y-3 text-xs">
          <div className="flex flex-wrap gap-2">
            {[1180, 2950, 5900, 11800].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setTopupAmount(String(value))}
                className={`rounded border px-3 py-1.5 font-mono ${topupAmount === String(value) ? 'border-[#00df8f] text-[#00df8f]' : 'border-[#232736] text-slate-300 hover:border-slate-500'}`}
              >
                {inr(value, 0)}
              </button>
            ))}
          </div>
          <label className="block space-y-1">
            <span className="text-slate-300">Amount (₹, incl. GST)</span>
            <input
              type="number"
              min={info.min_topup_inr}
              className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100"
              value={topupAmount}
              onChange={(e) => setTopupAmount(e.target.value)}
            />
          </label>
          {Number(topupAmount) > 0 && (
            <p className="text-slate-400">
              Wallet credit: <span className="font-mono text-[#00df8f]">{inr(Number(topupAmount) / (1 + gstRate / 100))}</span>
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setTopupOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={Number(topupAmount) < info.min_topup_inr}
              isLoading={busy === 'topup'}
              onClick={() => pay('topup', { purpose: 'WALLET_TOPUP', amount_inr: Number(topupAmount) }, 'Payment received. Your wallet has been topped up.')}
            >
              Pay {Number(topupAmount) > 0 ? inr(Number(topupAmount), 0) : ''}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
