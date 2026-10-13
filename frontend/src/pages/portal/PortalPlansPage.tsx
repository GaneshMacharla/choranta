import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Sparkles } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { PlanGrid } from '../../components/billing/PlanGrid';
import { payWithRazorpay } from '../../components/billing/razorpayCheckout';
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

  const choose = async (plan: Plan) => {
    setBusyPlanId(plan.id);
    setError(null);
    try {
      const order = await portalService.createOrder({ purpose: 'SUBSCRIPTION', plan_id: plan.id });
      if (await payWithRazorpay(order)) navigate('/portal', { replace: true });
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

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-[#00df8f]/30 bg-[#00df8f]/15 text-[#00df8f]">
          <Sparkles className="h-5 w-5" />
        </div>
        <h1 className="text-2xl font-bold">{hasPlan ? 'Plans' : `Welcome${user?.name ? `, ${user.name.split(' ')[0]}` : ''}! Choose your plan`}</h1>
        <p className="mx-auto mt-1 max-w-xl text-sm text-slate-400">
          Each plan gives your AI employee credits every month (1 credit = ₹1). Calls use plan credits first, then any credits you buy.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}
      {!info.online_payments && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-700/60 bg-amber-950/30 p-3 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Online payment isn't available yet. Contact Choranta to subscribe.
        </div>
      )}

      {plans.length === 0 ? (
        <p className="py-10 text-center text-sm text-slate-400">No plans are available right now. You can start on pay-as-you-go.</p>
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
            Skip for now — pay as you go with bought credits
          </button>
        </div>
      )}
    </div>
  );
};
