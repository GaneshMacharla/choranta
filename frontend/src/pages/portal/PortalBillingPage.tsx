import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { portalAgentRequestsService } from '../../services/agentRequests';
import { AlertTriangle, CheckCircle, Download, Plus, Wallet as WalletIcon } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { Modal } from '../../components/common/Modal';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { inr, InvoiceSummary, portalService, Wallet } from '../../services/portal';
import { creditsLabel, Plan, plansService, Subscription } from '../../services/plans';
import { WalletLedger } from '../../components/billing/WalletLedger';
import { fmtDate, PlanUsageBar } from '../../components/billing/PlanUsageBar';
import { payWithRazorpay } from '../../components/billing/razorpayCheckout';
import { PlanGrid } from '../../components/billing/PlanGrid';
import { CreditPackGrid } from '../../components/billing/CreditPackGrid';

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

  const navigate = useNavigate();
  const pay = async (key: string, body: Parameters<typeof portalService.createOrder>[0], successMessage: string) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const order = await portalService.createOrder(body);
      const paid = await payWithRazorpay(order);
      if (paid && body.purpose === 'SUBSCRIPTION') {
        const me = await portalAgentRequestsService.me().catch(() => null);
        if (me && !me.has_ai_employee) {
          navigate('/portal/employees?welcome=plan');
          return;
        }
      }
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
  const gst = info.gst_registered;
  const perMinute = info.avg_credits_per_minute;
  const creditsFor = (paid: number) => Math.floor((paid / (1 + gstRate / 100)) * 100) / 100;
  const packs = info.credit_packs;
  const selectedPack = packs.find((pack) => String(pack.price_with_gst_inr) === topupAmount)?.key ?? null;
  const openTopup = (amount = '') => {
    setTopupAmount(amount);
    setError(null);
    setTopupOpen(true);
  };
  const docName = gst ? 'invoice' : 'receipt';
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-xl font-bold">Billing</h1>
        <p className="text-sm">
          Bought credits: <span className="font-mono font-bold text-[#00df8f]">{creditsLabel(wallet.balance_inr)}</span>
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
      {info.simulated_payments && (
        <div className="flex items-start gap-2 rounded-lg border border-sky-700/60 bg-sky-950/30 p-3 text-xs text-sky-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Test mode: payments are simulated. No money is charged.
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
        <Card title={sub && sub.status !== 'CANCELLED' ? 'Your plan' : 'Pay-as-you-go'} className="lg:col-span-7" bodyClassName="flex flex-col justify-center">
          {sub && sub.status !== 'CANCELLED' ? (
            <>
              <PlanUsageBar subscription={sub} />
              {info.payg_only && (
                <p className="mt-3 text-xs text-slate-400">
                  Your {sub.plan?.name} plan ends on {fmtDate(sub.current_period_end)}. After that you're on pay-as-you-go: calls are
                  paid from your bought credits.
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-400">
              You're on pay-as-you-go: each call is paid from your credits, about {inr(perMinute)} per minute (1 credit = ₹1).
              {plans.length > 0 ? ' Pick a monthly plan below to get bonus credits every month.' : ' Not sure how much to add? Pick a pack below.'}
            </p>
          )}
        </Card>

        <Card
          title="Bought credits"
          subtitle={sub ? 'Used after your plan credits run out · never expire' : 'Pay for your calls · never expire'}
          className="lg:col-span-5"
          bodyClassName="flex flex-col justify-between gap-4"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#0f3d33] bg-[#06221c] text-[#00df8f]">
              <WalletIcon className="h-5 w-5" />
            </div>
            <div>
              <span className="block font-mono text-2xl font-bold text-slate-100">{creditsLabel(wallet.balance_inr)}</span>
              <span className="text-xs text-slate-500">1 credit = ₹1{gst ? ' (excl. GST)' : ''} · about {inr(perMinute)} per call minute</span>
            </div>
          </div>
          <Button
            variant="secondary"
            disabled={!online}
            title={online ? '' : 'Online payments are not set up yet'}
            onClick={() => openTopup()}
          >
            <Plus className="mr-1.5 h-4 w-4" /> Buy credits
          </Button>
        </Card>
      </div>

      {packs.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-slate-200">Which pack do I need?</h2>
              <p className="text-xs text-slate-500">
                Calls cost about {inr(perMinute)} a minute. Minutes and calls below are estimates at that rate.
              </p>
            </div>
            {!online && <span className="text-xs text-amber-300">Online payment isn't available yet. Contact Choranta to buy credits.</span>}
          </div>
          <CreditPackGrid
            packs={packs}
            gst={gst}
            disabled={!online}
            onSelect={(pack) => openTopup(String(pack.price_with_gst_inr))}
            onCustom={online ? () => openTopup() : undefined}
            customLabel="Enter any amount"
          />
        </div>
      )}

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
              pay('plan-' + plan.id, { purpose: 'SUBSCRIPTION', plan_id: plan.id }, `Payment received. Your ${plan.name} plan is set, and the ${gst ? 'GST invoice' : 'receipt'} is below.`)
            }
          />
        </div>
      )}

      <Card
        title={gst ? 'Invoices' : 'Receipts'}
        subtitle={gst ? 'GST tax invoices for your plans and credit purchases' : 'Payment receipts for your credit purchases'}
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#1f2433] text-slate-400">
              <tr>
                <th className="px-4 py-3">{gst ? 'Invoice' : 'Receipt'}</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">For</th>
                {gst && <th className="px-4 py-3">Taxable</th>}
                {gst && <th className="px-4 py-3">GST</th>}
                <th className="px-4 py-3">Total</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={gst ? 7 : 5} className="px-4 py-6 text-center text-slate-500">No {docName}s yet.</td>
                </tr>
              )}
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-b border-[#151a26] text-slate-300">
                  <td className="px-4 py-3 font-mono">{inv.number}</td>
                  <td className="px-4 py-3">{new Date(inv.issue_date).toLocaleDateString('en-IN')}</td>
                  <td className="max-w-[16rem] truncate px-4 py-3 text-slate-400" title={inv.description}>
                    {inv.description.replace('AI voice agent services - ', '')}
                  </td>
                  {gst && <td className="px-4 py-3 font-mono">{inr(inv.taxable_inr)}</td>}
                  {gst && <td className="px-4 py-3 font-mono">{inr(inv.cgst_inr + inv.sgst_inr + inv.igst_inr)}</td>}
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
        title="Buy credits"
        description={
          gst
            ? `Pay any amount from ${inr(info.min_topup_inr, 0)}, GST included. You get 1 credit per ₹1 excluding GST, and a GST invoice is issued. Bought credits never expire.`
            : `Pay any amount from ${inr(info.min_topup_inr, 0)}. You get 1 credit per ₹1 and a payment receipt. Bought credits never expire.`
        }
      >
        <div className="space-y-3 text-xs">
          <CreditPackGrid
            compact
            packs={packs}
            gst={gst}
            selectedKey={selectedPack}
            onSelect={(pack) => setTopupAmount(String(pack.price_with_gst_inr))}
          />
          <label className="block space-y-1">
            <span className="text-slate-300">Or enter an amount (₹{gst ? ', incl. GST' : ''})</span>
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
              You get:{' '}
              <span className="font-mono text-[#00df8f]">{creditsLabel(creditsFor(Number(topupAmount)))}</span>
              {perMinute > 0 && <span> · about {Math.floor(creditsFor(Number(topupAmount)) / perMinute).toLocaleString('en-IN')} call minutes</span>}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setTopupOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={Number(topupAmount) < info.min_topup_inr}
              isLoading={busy === 'topup'}
              onClick={() => pay('topup', { purpose: 'WALLET_TOPUP', amount_inr: Number(topupAmount) }, 'Payment received. Your credits have been added.')}
            >
              Pay {Number(topupAmount) > 0 ? inr(Number(topupAmount), 0) : ''}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
