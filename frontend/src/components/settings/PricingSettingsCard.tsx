import React, { useEffect, useState } from 'react';
import { IndianRupee, Save } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { pricingService, PricingSettings } from '../../services/pricing';

const inr = (value: number | null | undefined) =>
  value == null ? '—' : `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Admin-only: profit % added to each call's real cost (charged in credits). */
export const PricingSettingsCard: React.FC = () => {
  const [pricing, setPricing] = useState<PricingSettings | null>(null);
  const [profit, setProfit] = useState('');
  const [concurrent, setConcurrent] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (data: PricingSettings) => {
    setPricing(data);
    setProfit(String(data.profit_percent));
    setConcurrent(String(data.payg_max_concurrent_calls));
  };

  useEffect(() => {
    pricingService.get().then(apply).catch((err) => setMessage({ ok: false, text: err.message }));
  }, []);

  const profitValue = Number(profit);
  const concurrentValue = Number(concurrent);
  const valid =
    profit !== '' && profitValue >= 0 && profitValue <= 1000 && Number.isInteger(concurrentValue) && concurrentValue >= 1 && concurrentValue <= 500;

  // Live estimate while typing: recent average real cost per minute, then the new profit %
  const preview = pricing?.preview;
  const draftCost = preview?.avg_cost_per_minute != null && valid ? preview.avg_cost_per_minute : null;
  const draftCharge = draftCost != null ? draftCost * (1 + profitValue / 100) : null;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      apply(await pricingService.update(profitValue, concurrentValue));
      setMessage({ ok: true, text: 'Pricing saved. Calls ending from now on use these values.' });
    } catch (err: any) {
      setMessage({ ok: false, text: err.message || 'Could not save pricing.' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Client Pricing" subtitle="Profit on top of each call's real cost (admin only)">
      <div className="space-y-4 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="block font-medium text-slate-300">Profit %</span>
            <input
              type="number"
              min={0}
              max={1000}
              step="0.5"
              value={profit}
              onChange={(e) => setProfit(e.target.value)}
              className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
            />
          </label>
          <label className="space-y-1">
            <span className="block font-medium text-slate-300">Calls at a time (default)</span>
            <input
              type="number"
              min={1}
              max={500}
              step="1"
              value={concurrent}
              onChange={(e) => setConcurrent(e.target.value)}
              className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
            />
            <span className="block text-[10px] text-slate-500">Per client; override it on a client's page</span>
          </label>
        </div>
        <p className="leading-relaxed text-slate-500">
          When a call ends, Choranta works out its real cost (Exotel minutes, speech-to-text, text-to-speech and LLM),
          adds the profit %, and takes that many credits (₹1 = 1 credit) from the client's wallet.
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
