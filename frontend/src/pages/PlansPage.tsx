import React, { useEffect, useState } from 'react';
import { Phone } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { inr } from '../services/portal';
import { NUMBER_TYPE_LABELS, NumberPrice, plansService } from '../services/plans';

const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100';

/**
 * Admin pricing for phone numbers clients buy. Monthly plans are retired (Choranta is pay-as-you-go:
 * clients buy credits and each call costs its real cost + profit %), so they're no longer shown here.
 */
export const PlansPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex items-center gap-3 border-b border-[#102d38] pb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#00df8f]/30 bg-[#00df8f]/15 text-[#00df8f]">
          <Phone className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">Number Pricing</h1>
          <p className="text-xs text-slate-400">
            What clients pay for phone numbers. Calls are pay-as-you-go: clients buy credits and each call costs its real
            cost + your profit % (Settings → Client Pricing).
          </p>
        </div>
      </div>

      <NumberPricingCard isAdmin={isAdmin} />
    </div>
  );
};

const NumberPricingCard: React.FC<{ isAdmin: boolean }> = ({ isAdmin }) => {
  const [prices, setPrices] = useState<NumberPrice[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [setupDrafts, setSetupDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    plansService
      .numberPricing()
      .then((p) => {
        setPrices(p);
        setDrafts(Object.fromEntries(p.map((x) => [x.number_type, String(x.monthly_rent_inr)])));
        setSetupDrafts(Object.fromEntries(p.map((x) => [x.number_type, String(x.setup_fee_inr ?? 0)])));
      })
      .catch((err) => setError(err.message || 'Could not load number pricing.'));

  useEffect(() => {
    load();
  }, []);

  const save = async (price: NumberPrice, isAvailable = price.is_available) => {
    setBusy(price.number_type);
    setError(null);
    try {
      await plansService.updateNumberPricing(price.number_type, Number(drafts[price.number_type]), isAvailable, Number(setupDrafts[price.number_type] || 0));
      await load();
    } catch (err: any) {
      setError(err.message || 'Could not save.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <Phone className="h-4 w-4 text-[#00df8f]" /> Phone number rent
        </span>
      }
      subtitle="What clients pay per number: a one-time setup fee plus monthly rent (excl. GST), taken from bought credits. New prices apply to numbers bought from now on."
    >
      {error && <p className="mb-3 text-xs text-rose-300">{error}</p>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {prices.map((p) => {
          const changed = Number(drafts[p.number_type]) !== p.monthly_rent_inr || Number(setupDrafts[p.number_type] || 0) !== (p.setup_fee_inr ?? 0);
          return (
            <div key={p.number_type} className={`rounded-lg border border-[#143c49] bg-[#06141a] p-4 text-xs ${p.is_available ? '' : 'opacity-60'}`}>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">{NUMBER_TYPE_LABELS[p.number_type]}</span>
                <Badge variant={p.is_available ? 'green' : 'gray'}>{p.is_available ? 'ON SALE' : 'HIDDEN'}</Badge>
              </div>
              <label className="mt-3 block space-y-1">
                <span className="text-slate-400">Rent per month (₹, excl. GST)</span>
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={drafts[p.number_type] ?? ''}
                  disabled={!isAdmin}
                  onChange={(e) => setDrafts({ ...drafts, [p.number_type]: e.target.value })}
                />
              </label>
              <p className="mt-1 text-[11px] text-slate-500">{inr(p.monthly_rent_with_gst_inr)} incl. GST</p>
              <label className="mt-3 block space-y-1">
                <span className="text-slate-400">One-time setup fee (₹, excl. GST)</span>
                <input
                  type="number"
                  min={0}
                  className={inputClass}
                  value={setupDrafts[p.number_type] ?? '0'}
                  disabled={!isAdmin}
                  onChange={(e) => setSetupDrafts({ ...setupDrafts, [p.number_type]: e.target.value })}
                />
              </label>
              {isAdmin && (
                <div className="mt-3 flex justify-between gap-2">
                  <Button size="sm" variant="ghost" isLoading={busy === p.number_type && !changed} onClick={() => save(p, !p.is_available)}>
                    {p.is_available ? 'Stop selling' : 'Start selling'}
                  </Button>
                  <Button size="sm" variant="primary" disabled={!changed || !(Number(drafts[p.number_type]) > 0)} isLoading={busy === p.number_type && changed} onClick={() => save(p)}>
                    Save
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
};
