import React, { useCallback, useEffect, useState } from 'react';
import { Search, ShoppingCart } from 'lucide-react';
import { Button } from '../common/Button';
import { ErrorState } from '../common/ErrorState';
import { LoadingState } from '../common/LoadingState';
import { InventoryNumber, InventoryPage, NumberType, OperationResult, money, numbersService } from '../../services/numbers';
import { MockBadge } from './shared';
import { PurchaseConfirmModal } from './PurchaseConfirmModal';

const FIELD = 'rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';
const COUNTRIES = [{ value: 'IN', label: 'India' }, { value: 'US', label: 'United States' }, { value: '', label: 'Any country' }];
const TYPES: { value: NumberType | ''; label: string }[] = [
  { value: '', label: 'Any type' }, { value: 'Landline', label: 'Landline' }, { value: 'Mobile', label: 'Mobile' }, { value: 'TollFree', label: 'Toll-free' },
];
const PER_PAGE = 25;

/** What the carrier is selling. Buying is admin-only; everyone else can browse. */
export const InventoryPanel: React.FC<{ canBuy: boolean; onBought?: (result: OperationResult) => void }> = ({ canBuy, onBought }) => {
  const [filters, setFilters] = useState({ country: 'IN', search: '', number_type: '' as NumberType | '', region: '' });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<InventoryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [buying, setBuying] = useState<InventoryNumber | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await numbersService.inventory({ ...applied, page, per_page: PER_PAGE }));
    } catch (err: any) {
      setError(err.message || "Couldn't load the carrier's numbers.");
    } finally {
      setLoading(false);
    }
  }, [applied, page]);

  useEffect(() => {
    load();
  }, [load]);

  const search = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setApplied({ ...filters }); // a new object, so searching again with the same filters reloads
  };

  const lastPage = data?.total ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : page;

  return (
    <div className="space-y-4">
      <form onSubmit={search} className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[1fr_auto_auto_1fr_auto]" aria-label="Search numbers">
        <input className={FIELD} placeholder="Digits or prefix, e.g. 8040" aria-label="Number or prefix" value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        <select className={FIELD} aria-label="Country" value={filters.country} onChange={(e) => setFilters({ ...filters, country: e.target.value })}>
          {COUNTRIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <select className={FIELD} aria-label="Number type" value={filters.number_type}
          onChange={(e) => setFilters({ ...filters, number_type: e.target.value as NumberType | '' })}>
          {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <input className={FIELD} placeholder="Region, e.g. Karnataka" aria-label="Region" value={filters.region}
          onChange={(e) => setFilters({ ...filters, region: e.target.value })} />
        <Button type="submit" variant="primary" size="sm" leftIcon={<Search className="h-3.5 w-3.5" />}>Search</Button>
      </form>
      <p className="text-[11px] text-slate-500">
        Vobiz filters by country and digits. Type is worked out from the prefix and region is matched on each page, so a filtered
        page can be shorter. Every number for sale supports voice; Vobiz doesn't list other capabilities before purchase.
      </p>

      {loading ? (
        <LoadingState message="Loading numbers for sale..." />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data || data.items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#1b3a46] p-8 text-center text-sm text-slate-400">
          No numbers match. Try another prefix, type or region.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-[#102d38]">
            <table className="w-full min-w-[640px] text-left text-sm text-slate-300">
              <thead className="border-b border-[#102d38] bg-[#06161d] text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Number</th>
                  <th className="px-4 py-2.5 font-medium">Type · region</th>
                  <th className="px-4 py-2.5 font-medium">Setup fee</th>
                  <th className="px-4 py-2.5 font-medium">Monthly</th>
                  <th className="px-4 py-2.5 font-medium">Availability</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#102d38]">
                {data.items.map((n) => (
                  <tr key={n.e164}>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2 font-mono text-slate-100">{n.e164} {n.is_mock && <MockBadge />}</span>
                      {n.scenario && <span className="text-[11px] text-amber-300">{n.scenario}</span>}
                    </td>
                    <td className="px-4 py-2.5 text-xs">{n.number_type || '-'} · {n.region || n.country || '-'}</td>
                    <td className="px-4 py-2.5 text-xs">{money(n.setup_fee, n.currency)}</td>
                    <td className="px-4 py-2.5 text-xs">{money(n.monthly_fee, n.currency)}</td>
                    <td className="px-4 py-2.5 text-xs text-[#00df8f]">Listed for sale</td>
                    <td className="px-4 py-2.5 text-right">
                      {canBuy && (
                        <Button variant="secondary" size="sm" leftIcon={<ShoppingCart className="h-3.5 w-3.5" />} onClick={() => setBuying(n)}>
                          Buy
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>{data.total != null ? `${data.total} listed` : ''}</span>
            <span className="flex items-center gap-2">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              Page {page} of {lastPage}
              <Button variant="secondary" size="sm" disabled={page >= lastPage} onClick={() => setPage(page + 1)}>Next</Button>
            </span>
          </div>
        </>
      )}

      <PurchaseConfirmModal
        number={buying}
        onClose={() => {
          setBuying(null);
          load();
        }}
        onDone={(result) => onBought?.(result)}
      />
    </div>
  );
};
