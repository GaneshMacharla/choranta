import React, { useEffect, useState } from 'react';
import { ArrowRight, Coins } from 'lucide-react';
import { CreditPackGrid } from '../billing/CreditPackGrid';
import { CreditPack, publicPricingService, PublicCreditPacks } from '../../services/pricing';

interface PricingSectionProps {
  onOpenDemo: () => void;
}

// Shown if the live packs can't be loaded (estimates at the default ₹7 a minute, 2-minute calls)
const FALLBACK_RATE = 7;
const fallbackPack = (key: string, name: string, credits: number, suits: string, recommended = false): CreditPack => {
  const minutes = Math.floor(credits / FALLBACK_RATE);
  return { key, name, credits, suits, recommended, price_with_gst_inr: credits, approx_minutes: minutes, approx_calls: Math.floor(minutes / 2) };
};
const FALLBACK: PublicCreditPacks = {
  packs: [
    fallbackPack('starter', 'Starter', 1000, 'Trying it out, or a few calls a day'),
    fallbackPack('growth', 'Growth', 3000, 'About 7 calls a day for a month', true),
    fallbackPack('business', 'Business', 7500, 'About 18 calls a day for a month'),
    fallbackPack('scale', 'Scale', 20000, 'Campaigns, 45+ calls a day'),
    fallbackPack('enterprise', 'Enterprise', 50000, 'Large teams and call centres, 120+ calls a day'),
  ],
  avg_credits_per_minute: FALLBACK_RATE,
  gst_rate_percent: 0,
  gst_registered: false,
  min_topup_inr: 500,
};

/** Pay-per-minute pricing: suggested credit packs by business size. */
export const PricingSection: React.FC<PricingSectionProps> = ({ onOpenDemo }) => {
  const [data, setData] = useState<PublicCreditPacks>(FALLBACK);

  useEffect(() => {
    publicPricingService.creditPacks().then(setData).catch(() => setData(FALLBACK));
  }, []);

  return (
    <section id="pricing" className="relative py-24 bg-[#040d12] text-slate-100">
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider text-[#00df8f] bg-[#05261d] border border-[#00df8f]/30">
            <Coins className="w-3.5 h-3.5" />
            <span>Simple pricing</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">Pay only for the minutes you use</h2>
          <p className="text-slate-400">
            Add credits and your AI employee uses them as it talks: about ₹{Math.round(data.avg_credits_per_minute)} a minute
            (1 credit = ₹1{data.gst_registered ? ', plus GST' : ''}). No monthly fee, and credits never expire.
          </p>
        </div>

        <CreditPackGrid packs={data.packs} gst={data.gst_registered} onCustom={onOpenDemo} customLabel="Talk to us" />

        <div className="mt-10 flex flex-col items-center gap-3 text-center">
          <p className="text-xs text-slate-500">
            Minutes and calls are estimates; real usage depends on call length. You can also add any amount from ₹
            {data.min_topup_inr.toLocaleString('en-IN')}.
          </p>
          <button
            type="button"
            onClick={onOpenDemo}
            className="inline-flex items-center gap-2 rounded-lg bg-[#00df8f] px-5 py-2.5 text-sm font-semibold text-[#04120d] hover:bg-[#00c47e]"
          >
            Try a free demo call <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  );
};
