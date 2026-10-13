import React, { useEffect, useState } from 'react';
import { IndianRupee, Save } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { pricingService, PricingSettings } from '../../services/pricing';

const inr = (value: number | null | undefined) =>
  value == null ? '—' : `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Admin-only: credits each call minute costs clients, and infra overhead for profit reporting. */
export const PricingSettingsCard: React.FC = () => {
  const [pricing, setPricing] = useState<PricingSettings | null>(null);
  const [rate, setRate] = useState('');
  const [infra, setInfra] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (data: PricingSettings) => {
    setPricing(data);
    setRate(String(data.credits_per_minute));
    setInfra(String(data.infra_cost_per_minute_inr));
  };

  useEffect(() => {
    pricingService.get().then(apply).catch((err) => setMessage({ ok: false, text: err.message }));
  }, []);

  const rateValue = Number(rate);
  const infraValue = Number(infra);
  const valid = rate !== '' && infra !== '' && rateValue > 0 && rateValue <= 1000 && infraValue >= 0;

  // Live estimate while typing: recent average provider cost + new infra vs. the new credit rate
  const preview = pricing?.preview;
  const providerCostPerMin =
    preview?.avg_cost_per_minute != null ? preview.avg_cost_per_minute - pricing!.infra_cost_per_minute_inr : null;
  const draftCost = providerCostPerMin != null && valid ? providerCostPerMin + infraValue : null;
  // Billed per started minute, so charge per talk minute runs a little above the rate; scale the recent average
  const pulseFactor =
    preview?.avg_charge_per_minute != null && pricing && pricing.credits_per_minute > 0
      ? preview.avg_charge_per_minute / pricing.credits_per_minute
      : 1;
  const draftCharge = draftCost != null && valid ? rateValue * pulseFactor : null;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      apply(await pricingService.update(rateValue, infraValue));
      setMessage({ ok: true, text: 'Pricing saved. Calls now use this many credits per minute.' });
    } catch (err: any) {
      setMessage({ ok: false, text: err.message || 'Could not save pricing.' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Client Pricing" subtitle="Credits per call minute (admin only)">
      <div className="space-y-4 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="block font-medium text-slate-300">Credits per minute</span>
            <input
              type="number"
              min={0.5}
              max={1000}
              step="0.5"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
            />
          </label>
          <label className="space-y-1">
            <span className="block font-medium text-slate-300">Infra cost ₹/min</span>
            <input
              type="number"
              min={0}
              step="0.05"
              value={infra}
              onChange={(e) => setInfra(e.target.value)}
              className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
            />
          </label>
        </div>
        <p className="leading-relaxed text-slate-500">
          1 credit = ₹1 (excl. GST). Each call costs billed minutes × credits per minute, taken from plan credits
          first, then bought credits. Infra (monthly infra bill ÷ monthly minutes) only feeds the profit preview.
        </p>

        <div className="rounded border border-[#1b2030] bg-black/30 p-3">
          <div className="mb-2 flex items-center gap-1.5 font-semibold text-slate-300">
            <IndianRupee className="h-3.5 w-3.5 text-amber-400" />
            {preview && preview.calls > 0
              ? `Based on ${preview.calls} calls (${preview.minutes} min) in the last ${preview.window_days} days`
              : 'No completed calls yet to preview'}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-slate-500">Cost / min</span>
              <span className="font-mono text-sm text-slate-200">{inr(draftCost)}</span>
            </div>
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-slate-500">Charge / min</span>
              <span className="font-mono text-sm font-bold text-amber-300">{inr(draftCharge)}</span>
            </div>
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-slate-500">Profit / min</span>
              <span className="font-mono text-sm text-emerald-300">
                {inr(draftCharge != null && draftCost != null ? draftCharge - draftCost : null)}
              </span>
            </div>
          </div>
        </div>

        {message && <p className={message.ok ? 'text-emerald-300' : 'text-rose-300'}>{message.text}</p>}

        <div className="flex items-center justify-between">
          <span className="text-[10px] text-slate-500">
            {pricing?.updated_at ? `Last updated ${new Date(pricing.updated_at).toLocaleString()}` : 'Using default values'}
          </span>
          <Button size="sm" variant="primary" onClick={save} isLoading={saving} disabled={!valid || saving}>
            <Save className="mr-1.5 h-3.5 w-3.5" /> Save pricing
          </Button>
        </div>
      </div>
    </Card>
  );
};
