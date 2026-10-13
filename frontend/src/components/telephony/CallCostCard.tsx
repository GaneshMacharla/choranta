import React from 'react';
import { IndianRupee } from 'lucide-react';
import { CallCost } from '../../services/telephony';

const inr = (value: number, digits = 2) =>
  `₹${value.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

const ROWS: Array<{ key: keyof NonNullable<CallCost['breakdown']>; label: string }> = [
  { key: 'telephony', label: 'Telephony (Exotel)' },
  { key: 'text_to_speech', label: 'Agent voice (TTS)' },
  { key: 'speech_to_text', label: 'Speech-to-text' },
  { key: 'llm', label: 'AI model (LLM)' },
];

const LLM_LABELS: Record<string, string> = { sarvam: 'AI model (Sarvam)', gemini: 'AI model (Gemini)' };

/**
 * Client charge for a call. Admins (whose cost object includes the breakdown) also see our
 * cost, the profit margin and the per-provider split; operators see the charge only.
 */
export const CallCostCard: React.FC<{ cost: CallCost }> = ({ cost }) => {
  const internal = !!cost.breakdown;
  const total = cost.total || 0;
  return (
    <div className="space-y-3 rounded border border-[#1b2030] bg-[#0d101a] p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-semibold text-slate-300">
          <IndianRupee className="h-3.5 w-3.5 text-amber-400" />
          Charge to client
        </span>
        <span className="text-[10px] text-slate-500">{cost.billed_minutes} billed min · estimated</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded bg-black/30 p-2">
          <span className="block text-[10px] uppercase tracking-wider text-slate-500">Per minute</span>
          <span className="font-mono text-lg font-bold text-amber-300">
            {cost.charge_per_minute != null ? inr(cost.charge_per_minute) : '—'}
          </span>
        </div>
        <div className="rounded bg-black/30 p-2">
          <span className="block text-[10px] uppercase tracking-wider text-slate-500">This call</span>
          <span className="font-mono text-lg font-bold text-slate-100">{inr(cost.charge_total || 0)}</span>
        </div>
      </div>

      {internal && (
        <>
          <div className="grid grid-cols-3 gap-2 border-t border-[#1b2030] pt-2">
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-slate-500">Our cost / min</span>
              <span className="font-mono text-slate-200">{cost.per_minute != null ? inr(cost.per_minute) : '—'}</span>
            </div>
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-slate-500">Profit</span>
              <span className="font-mono text-emerald-300">{cost.profit_percent ?? 0}%</span>
            </div>
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-slate-500">Profit this call</span>
              <span className="font-mono text-emerald-300">{inr(cost.profit || 0)}</span>
            </div>
          </div>

          <div className="space-y-1.5">
            {ROWS.map(({ key, label }) => {
              const value = cost.breakdown?.[key] || 0;
              const share = total > 0 ? (value / total) * 100 : 0;
              const rowLabel = key === 'llm' ? LLM_LABELS[cost.llm_provider || ''] || label : label;
              return (
                <div key={key}>
                  <div className="flex justify-between text-slate-400">
                    <span>{rowLabel}</span>
                    <span className="font-mono text-slate-300">{inr(value, value < 1 ? 3 : 2)}</span>
                  </div>
                  <div className="mt-0.5 h-1 rounded bg-slate-800">
                    <div className="h-1 rounded bg-amber-500/70" style={{ width: `${share}%` }} />
                  </div>
                </div>
              );
            })}
            <div className="flex justify-between border-t border-[#1b2030] pt-1 text-slate-300">
              <span>Our cost this call</span>
              <span className="font-mono">{inr(total)}</span>
            </div>
          </div>

          {cost.rates && (
            <p className="text-[10px] leading-relaxed text-slate-500">
              Estimated from backend rates (Exotel ₹{cost.rates.telephony_per_minute_inr}/min billed per{' '}
              {cost.rates.billing_pulse_seconds}s, TTS ${cost.rates.tts_usd_per_minute}/min). The client is charged cost + profit % in credits (₹1 = 1 credit); profit % is set in Settings.
            </p>
          )}
        </>
      )}
    </div>
  );
};

/** Client charge per minute for a list cell. */
export const formatInrPerMinute = (cost?: CallCost | null) =>
  cost && cost.charge_per_minute != null ? `${inr(cost.charge_per_minute)}/min` : '—';
