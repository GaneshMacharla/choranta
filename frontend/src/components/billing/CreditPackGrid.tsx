import React from 'react';
import { Check, MessageSquare } from 'lucide-react';
import { Button } from '../common/Button';
import { inr } from '../../services/portal';
import { creditsLabel } from '../../services/plans';
import { CreditPack } from '../../services/pricing';

interface CreditPackGridProps {
  packs: CreditPack[];
  /** Prices are shown "+ GST" when the company is GST registered */
  gst: boolean;
  /** Compact cards that select a pack (Buy credits popup); otherwise full cards with a buy button */
  compact?: boolean;
  selectedKey?: string | null;
  busyKey?: string | null;
  disabled?: boolean;
  actionLabel?: string;
  onSelect?: (pack: CreditPack) => void;
  /** Adds a "Custom" card for bigger needs (any amount, more simultaneous calls); called when it is clicked */
  onCustom?: () => void;
  customLabel?: string;
}

const num = (value: number) => value.toLocaleString('en-IN');

/** Suggested credit packs by business size, with about how many minutes and calls each buys. */
export const CreditPackGrid: React.FC<CreditPackGridProps> = ({
  packs, gst, compact, selectedKey, busyKey, disabled, actionLabel = 'Buy', onSelect, onCustom, customLabel = 'Talk to us',
}) => {
  if (compact) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {packs.map((pack) => {
          const selected = selectedKey === pack.key;
          return (
            <button
              key={pack.key}
              type="button"
              onClick={() => onSelect?.(pack)}
              className={`rounded-lg border p-3 text-left transition-colors ${
                selected ? 'border-[#00df8f] bg-[#06221c]/60' : 'border-[#232736] hover:border-slate-500'
              }`}
            >
              <span className="flex items-center justify-between gap-1 text-xs font-semibold text-slate-200">
                {pack.name}
                {pack.recommended && <span className="text-[9px] uppercase tracking-wider text-[#00df8f]">Popular</span>}
              </span>
              <span className="mt-1 block font-mono text-sm font-bold text-slate-100">{creditsLabel(pack.credits)}</span>
              <span className="block text-[11px] text-slate-400">
                ≈ {num(pack.approx_minutes)} min · ≈ {num(pack.approx_calls)} calls
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {packs.map((pack) => (
        <div
          key={pack.key}
          className={`relative flex flex-col rounded-lg border p-5 ${
            pack.recommended ? 'border-[#00df8f]/60 bg-[#06221c]/60' : 'border-[#143c49] bg-[#091b22]'
          }`}
        >
          {pack.recommended && (
            <span className="absolute -top-2.5 left-4 rounded-full bg-[#00df8f] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#04120d]">
              Most popular
            </span>
          )}
          <span className="text-base font-semibold text-slate-100">{pack.name}</span>
          <p className="mt-1 text-xs text-slate-400">{pack.suits}</p>
          <div className="mt-4">
            <span className="font-mono text-2xl font-bold text-slate-100">{inr(pack.credits, 0)}</span>
            {gst && <span className="text-xs text-slate-500"> + GST</span>}
          </div>
          <ul className="mt-4 flex-1 space-y-1.5 text-xs text-slate-300">
            {[
              creditsLabel(pack.credits),
              `About ${num(pack.approx_minutes)} call minutes`,
              `About ${num(pack.approx_calls)} calls of 2 minutes`,
              'Credits never expire',
            ].map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#00df8f]" /> {line}
              </li>
            ))}
          </ul>
          {onSelect && (
            <Button
              className="mt-5"
              variant={pack.recommended ? 'primary' : 'secondary'}
              disabled={disabled}
              isLoading={busyKey === pack.key}
              onClick={() => onSelect(pack)}
            >
              {actionLabel} · {inr(pack.price_with_gst_inr, 0)}
            </Button>
          )}
        </div>
      ))}
      {onCustom && (
        <div className="flex flex-col rounded-lg border border-dashed border-[#143c49] bg-[#091b22]/50 p-5">
          <span className="text-base font-semibold text-slate-100">Custom</span>
          <p className="mt-1 text-xs text-slate-400">Bigger volumes, or several AI employees calling at once</p>
          <div className="mt-4">
            <span className="font-mono text-2xl font-bold text-slate-100">Any amount</span>
          </div>
          <ul className="mt-4 flex-1 space-y-1.5 text-xs text-slate-300">
            {['1 credit = ₹1, same per-minute rate', 'More calls at the same time', 'Help setting up your campaigns'].map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#00df8f]" /> {line}
              </li>
            ))}
          </ul>
          <Button className="mt-5" variant="secondary" onClick={onCustom}>
            <MessageSquare className="mr-1.5 h-4 w-4" /> {customLabel}
          </Button>
        </div>
      )}
    </div>
  );
};
