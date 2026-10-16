import React, { useEffect, useState } from 'react';
import { Calculator, ArrowRight, TrendingUp, IndianRupee, Clock, Zap } from 'lucide-react';
import { publicPricingService } from '../../services/pricing';

interface RoiCalculatorSectionProps {
  onOpenDemo: () => void;
}

export const RoiCalculatorSection: React.FC<RoiCalculatorSectionProps> = ({ onOpenDemo }) => {
  const [callsPerMonth, setCallsPerMonth] = useState<number>(4500);
  const [callMinutes, setCallMinutes] = useState<number>(2);
  // Live per-minute rate (same as the pricing section); ₹7 until it loads
  const [ratePerMinute, setRatePerMinute] = useState<number>(7);

  useEffect(() => {
    publicPricingService.creditPacks().then((d) => setRatePerMinute(d.avg_credits_per_minute)).catch(() => {});
  }, []);

  const talkMinutes = callsPerMonth * callMinutes;

  // Loaded cost per telecaller in India (salary + PF + workstation + dialer) ~ ₹23,500/mo.
  // After dialling, unanswered calls, breaks and wrap-up, a telecaller talks ~100 minutes a day, 26 days a month.
  const TELECALLER_TALK_MINUTES = 100 * 26;
  const agents = Math.max(1, Math.ceil(talkMinutes / TELECALLER_TALK_MINUTES));
  const monthlyHumanCost = agents * 23500;
  const annualHumanCost = monthlyHumanCost * 12;

  // Choranta: pay per talk minute, no monthly fee
  const monthlyAiCost = Math.round(talkMinutes * ratePerMinute);
  const annualAiCost = monthlyAiCost * 12;

  const annualSavings = Math.max(0, annualHumanCost - annualAiCost);
  const savingsPercent = Math.round((annualSavings / annualHumanCost) * 100);

  const formatLakhs = (amount: number) => {
    const lakhs = (amount / 100000).toFixed(1);
    return `₹${lakhs} Lakhs`;
  };

  return (
    <section id="roi" className="relative py-24 bg-[#051117] text-slate-100 border-t border-b border-[#143c49]/50">
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider text-[#00df8f] bg-[#05261d] border border-[#00df8f]/30">
            <Calculator className="w-3.5 h-3.5" />
            <span>Interactive ROI Calculator</span>
          </div>

          <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
            Calculate Your Estimated Annual Cost Reduction
          </h2>

          <p className="text-slate-400 text-base sm:text-lg">
            See how much your organization saves by automating tier-1 calls with Choranta's sub-second AI voice workforce.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center max-w-5xl mx-auto">
          {/* Controls Column */}
          <div className="lg:col-span-7 rounded-3xl border border-[#143c49] bg-[#081b24] p-6 sm:p-8 space-y-8 shadow-xl">
            {/* Slider 1: Calls */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-semibold text-white">
                  Estimated Monthly Inbound / Outbound Calls
                </label>
                <span className="font-mono font-bold text-lg text-[#00df8f] bg-[#00df8f]/10 px-3 py-1 rounded-xl border border-[#00df8f]/30">
                  {callsPerMonth.toLocaleString('en-IN')} Calls
                </span>
              </div>
              <input
                type="range"
                min="500"
                max="20000"
                step="500"
                value={callsPerMonth}
                onChange={(e) => setCallsPerMonth(parseInt(e.target.value))}
                className="w-full h-2 bg-[#051116] rounded-lg appearance-none cursor-pointer accent-[#00df8f]"
              />
              <div className="flex justify-between text-[11px] text-slate-500 font-mono">
                <span>500</span>
                <span>10,000</span>
                <span>20,000+</span>
              </div>
            </div>

            {/* Slider 2: Average call length */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-semibold text-white">
                  Average Call Length
                </label>
                <span className="font-mono font-bold text-lg text-[#00df8f] bg-[#00df8f]/10 px-3 py-1 rounded-xl border border-[#00df8f]/30">
                  {callMinutes} min
                </span>
              </div>
              <input
                type="range"
                min="1"
                max="10"
                step="0.5"
                value={callMinutes}
                onChange={(e) => setCallMinutes(parseFloat(e.target.value))}
                className="w-full h-2 bg-[#051116] rounded-lg appearance-none cursor-pointer accent-[#00df8f]"
              />
              <div className="flex justify-between text-[11px] text-slate-500 font-mono">
                <span>1 min</span>
                <span>5 min</span>
                <span>10 min</span>
              </div>
            </div>

            <div className="rounded-2xl bg-[#051116] p-4 border border-[#143c49]/80 text-xs text-slate-400 space-y-1.5">
              <div className="flex justify-between text-slate-300">
                <span>Telecallers needed for this volume:</span>
                <span className="font-mono text-white">
                  {agents} × ~₹23,500 / mo
                </span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span>Choranta AI, no monthly fee:</span>
                <span className="font-mono text-[#00df8f]">~₹{Math.round(ratePerMinute)} / talk minute</span>
              </div>
              <p className="pt-1 text-[11px] text-slate-500">
                A telecaller talks ~100 minutes a day after dialling, unanswered calls and wrap-up.
              </p>
            </div>
          </div>

          {/* Results Summary Column */}
          <div className="lg:col-span-5 rounded-3xl border border-[#00df8f]/40 bg-gradient-to-br from-[#082028] via-[#092731] to-[#05141a] p-8 space-y-6 shadow-[0_0_40px_-10px_rgba(0,223,143,0.3)]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-[#00df8f]">
                Estimated Annual Savings
              </span>
              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-[#00df8f] text-[#022016]">
                Save ~{savingsPercent}%
              </span>
            </div>

            <div>
              <div className="text-4xl sm:text-5xl font-black font-mono text-white tracking-tight">
                {formatLakhs(annualSavings)}
              </div>
              <div className="text-xs text-emerald-400 font-medium mt-1">
                ≈ ₹{Math.round(annualSavings / 12).toLocaleString('en-IN')} / month back to your bottom line
              </div>
            </div>

            <div className="space-y-3 pt-4 border-t border-[#143c49]">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-slate-400" /> Human hold &amp; wrap-up:
                </span>
                <span className="font-semibold text-rose-400 line-through">45% wasted</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-[#00df8f]" /> Choranta AI pickup speed:
                </span>
                <span className="font-bold text-[#00df8f]">Instant 0 seconds</span>
              </div>
            </div>

            <button
              onClick={onOpenDemo}
              className="w-full flex items-center justify-center gap-2 py-3.5 px-6 rounded-xl font-bold text-sm text-[#022016] bg-[#00df8f] hover:bg-[#00f59b] transition-all shadow-[0_0_20px_rgba(0,223,143,0.4)] cursor-pointer"
            >
              <span>Unlock These Savings</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
};
