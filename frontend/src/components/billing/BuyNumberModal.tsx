import React, { useEffect, useState } from 'react';
import { AlertTriangle, Search, Phone } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { inr } from '../../services/portal';
import { AvailableNumber, NUMBER_TYPE_LABELS, NumberPrice, NumberType } from '../../services/plans';

const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100';

interface BuyNumberModalProps {
  isOpen: boolean;
  onClose: () => void;
  pricing: NumberPrice[];
  walletBalance?: number;
  /** Where the client tops up their wallet (portal only). */
  topUpLink?: string;
  search: (numberType: NumberType, region?: string) => Promise<AvailableNumber[]>;
  buy: (phoneNumber: string, numberType: NumberType) => Promise<unknown>;
  onBought: () => void;
}

/** Search Exotel's available numbers and buy one; the first month's rent comes from the wallet. */
export const BuyNumberModal: React.FC<BuyNumberModalProps> = ({
  isOpen, onClose, pricing, walletBalance, topUpLink, search, buy, onBought,
}) => {
  const available = pricing.filter((p) => p.is_available);
  const [numberType, setNumberType] = useState<NumberType>('Landline');
  const [region, setRegion] = useState('');
  const [results, setResults] = useState<AvailableNumber[] | null>(null);
  const [selected, setSelected] = useState<AvailableNumber | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'search' | 'buy' | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setResults(null);
    setSelected(null);
    setError(null);
    if (available.length && !available.some((p) => p.number_type === numberType)) setNumberType(available[0].number_type);
  }, [isOpen]);

  const price = pricing.find((p) => p.number_type === numberType);
  const short = walletBalance !== undefined && price ? walletBalance < price.monthly_rent_inr : false;

  const runSearch = async () => {
    setBusy('search');
    setError(null);
    setSelected(null);
    try {
      setResults(await search(numberType, region.trim() || undefined));
    } catch (err: any) {
      setError(err.message || 'Could not search numbers.');
    } finally {
      setBusy(null);
    }
  };

  const runBuy = async () => {
    if (!selected) return;
    setBusy('buy');
    setError(null);
    try {
      await buy(selected.phone_number, selected.number_type);
      onBought();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Could not buy this number.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Get a phone number"
      description="Numbers are provided by Choranta. Rent is charged monthly from the wallet; the first month is charged now."
      maxWidth="xl"
    >
      <div className="space-y-4 text-xs">
        {error && (
          <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <label className="block space-y-1">
            <span className="text-slate-300">Type</span>
            <select className={inputClass} value={numberType} onChange={(e) => { setNumberType(e.target.value as NumberType); setResults(null); setSelected(null); }}>
              {available.map((p) => (
                <option key={p.number_type} value={p.number_type}>
                  {NUMBER_TYPE_LABELS[p.number_type]} · {inr(p.monthly_rent_inr, 0)}/month + GST
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-slate-300">Region (optional)</span>
            <input className={inputClass} value={region} onChange={(e) => setRegion(e.target.value)} placeholder="e.g. TG, KA, MH" />
          </label>
          <Button variant="secondary" onClick={runSearch} isLoading={busy === 'search'} disabled={!available.length}>
            <Search className="mr-1.5 h-3.5 w-3.5" /> Search
          </Button>
        </div>

        {results !== null && (
          <div className="max-h-64 overflow-y-auto rounded border border-[#1b2030]">
            {results.length === 0 ? (
              <p className="px-4 py-6 text-center text-slate-500">No numbers available for this search. Try another type or region.</p>
            ) : (
              results.map((n) => (
                <button
                  key={n.phone_number}
                  type="button"
                  onClick={() => setSelected(n)}
                  className={`flex w-full items-center justify-between gap-3 border-b border-[#151a26] px-4 py-2.5 text-left last:border-0 ${
                    selected?.phone_number === n.phone_number ? 'bg-[#00df8f]/10' : 'hover:bg-[#0c2129]'
                  }`}
                >
                  <span className="flex items-center gap-2 font-mono text-sm text-slate-100">
                    <Phone className="h-3.5 w-3.5 text-[#00df8f]" /> {n.phone_number}
                  </span>
                  <span className="text-slate-500">{n.region || ''}</span>
                  <span className="font-mono text-slate-300">{inr(n.monthly_rent_inr, 0)}/mo</span>
                </button>
              ))
            )}
          </div>
        )}

        {selected && price && (
          <div className="rounded border border-[#143c49] bg-[#06141a] p-3 text-slate-300">
            <p>
              <span className="font-mono text-slate-100">{selected.phone_number}</span> costs{' '}
              <strong className="text-slate-100">{inr(price.monthly_rent_inr)}/month</strong>, charged from the wallet now and every month after.
            </p>
            {walletBalance !== undefined && (
              <p className={`mt-1 ${short ? 'text-rose-300' : 'text-slate-500'}`}>
                Wallet balance {inr(walletBalance)}
                {short && (
                  <>
                    {' '}— not enough for the first month.{' '}
                    {topUpLink && <Link to={topUpLink} className="text-[#00df8f] hover:underline">Top up the wallet</Link>}
                  </>
                )}
              </p>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!selected || short} isLoading={busy === 'buy'} onClick={runBuy}>
            Buy number
          </Button>
        </div>
      </div>
    </Modal>
  );
};
