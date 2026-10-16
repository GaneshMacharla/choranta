import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Sparkles } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { PlanGrid } from '../../components/billing/PlanGrid';
import { CreditPackGrid } from '../../components/billing/CreditPackGrid';
import { CreditPack } from '../../services/pricing';
import { inr } from '../../services/portal';
import { payWithRazorpay } from '../../components/billing/razorpayCheckout';
import { portalAgentRequestsService } from '../../services/agentRequests';
import { portalService } from '../../services/portal';
import { Plan, plansService } from '../../services/plans';

type PortalPlanInfo = Awaited<ReturnType<typeof portalService.subscription>>;

/** Remembers that a client chose pay-as-you-go, so the dashboard stops sending them here. */
export const planChoiceKey = (userId: string) => `choranta_plan_skipped_${userId}`;

export const hasSkippedPlanChoice = (userId?: string) => {
  if (!userId) return false;
  try {
    return localStorage.getItem(planChoiceKey(userId)) === '1';
  } catch {
    return false;
  }
};

/** First stop for clients without a plan: pick a monthly plan, or continue pay-as-you-go. */
export const PortalPlansPage: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [info, setInfo] = useState<PortalPlanInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyPlanId, setBusyPlanId] = useState<string | null>(null);
  // New clients see the three smaller packs first
  const [showAllPacks, setShowAllPacks] = useState(false);

  useEffect(() => {
    Promise.all([plansService.list(), portalService.subscription()])
      .then(([p, s]) => {
        setPlans(p);
        setInfo(s);
      })
      .catch((err) => setLoadError(err.message || 'Could not load plans.'));
  }, []);

  const skip = () => {
    if (user) {
      try {
        localStorage.setItem(planChoiceKey(user.id), '1');
      } catch {
        // storage unavailable: the dashboard will offer plans again next time
      }
    }
    navigate('/portal', { replace: true });
  };

  const choose = (plan: Plan) => checkout(plan.id, { purpose: 'SUBSCRIPTION', plan_id: plan.id });
  const buyPack = (pack: CreditPack) => checkout(pack.key, { purpose: 'WALLET_TOPUP', amount_inr: pack.price_with_gst_inr });

  const checkout = async (key: string, body: Parameters<typeof portalService.createOrder>[0]) => {
    setBusyPlanId(key);
    setError(null);
    try {
      const order = await portalService.createOrder(body);
      if (await payWithRazorpay(order)) {
        // No AI employee yet: take them straight to creating one
        const me = await portalAgentRequestsService.me().catch(() => null);
        navigate(me && !me.has_ai_employee ? '/portal/employees?welcome=plan' : '/portal', { replace: true });
      }
    } catch (err: any) {
      setError(err.message || 'Payment could not be completed.');
    } finally {
      setBusyPlanId(null);
    }
  };

  if (loadError) return <ErrorState message={loadError} onRetry={() => window.location.reload()} />;
  if (!plans || !info) return <LoadingState message="Loading plans..." />;

  const sub = info.subscription;
  const hasPlan = !!sub && sub.status !== 'CANCELLED';
  const packsOnly = plans.length === 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-[#00df8f]/30 bg-[#00df8f]/15 text-[#00df8f]">
          <Sparkles className="h-5 w-5" />
        </div>
        <h1 className="text-2xl font-bold">{hasPlan ? 'Plans' : `Welcome${user?.name ? `, ${user.name.split(' ')[0]}` : ''}! Choose ${packsOnly ? 'a credit pack' : 'your plan'}`}</h1>
        <p className="mx-auto mt-1 max-w-xl text-sm text-slate-400">
          {packsOnly
            ? `Pay only for the minutes your AI employee talks: about ${inr(info.avg_credits_per_minute)} a minute (1 credit = ₹1). Pick the pack that fits how many calls you make. Credits never expire.`
            : 'Each plan gives your AI employee credits every month (1 credit = ₹1). Calls use plan credits first, then any credits you buy.'}
        </p>
      </div>

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
      {!info.online_payments && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-700/60 bg-amber-950/30 p-3 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Online payment isn't available yet. Contact Choranta to {packsOnly ? 'buy credits' : 'subscribe'}.
        </div>
      )}

      {packsOnly ? (
        <div className="space-y-4">
          <CreditPackGrid
            packs={showAllPacks ? info.credit_packs : info.credit_packs.slice(0, 3)}
            gst={info.gst_registered}
            disabled={!info.online_payments}
            busyKey={busyPlanId}
            onSelect={buyPack}
            onCustom={showAllPacks && info.online_payments ? () => navigate('/portal/billing') : undefined}
            customLabel="Enter any amount"
          />
          {!showAllPacks && info.credit_packs.length > 3 && (
            <div className="text-center">
              <button type="button" onClick={() => setShowAllPacks(true)} className="text-xs font-semibold text-[#00df8f] underline-offset-2 hover:underline">
                See all packs, including large-scale business
              </button>
            </div>
          )}
        </div>
      ) : (
        <PlanGrid
          plans={plans}
          subscription={sub}
          online={info.online_payments}
          gstRate={info.gst_rate_percent}
          busyPlanId={busyPlanId}
          onChoose={choose}
        />
      )}

      {!hasPlan && (
        <div className="text-center">
          <button type="button" onClick={skip} className="text-xs text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline">
            {packsOnly ? "Skip for now — I'll add credits later" : 'Skip for now — pay as you go with bought credits'}
          </button>
        </div>
      )}
    </div>
  );
};
