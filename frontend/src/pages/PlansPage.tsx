import React, { useEffect, useState } from 'react';
import { Layers, Plus, Pencil, AlertTriangle, Phone } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { Table, Column } from '../components/common/Table';
import { EmptyState } from '../components/common/EmptyState';
import { inr } from '../services/portal';
import { perMinuteRange } from '../components/billing/PlanGrid';
import { NUMBER_TYPE_LABELS, NumberPrice, Plan, PlanInput, plansService } from '../services/plans';

const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100';

const emptyDraft: PlanInput = {
  name: '',
  description: '',
  monthly_price_inr: 0,
  monthly_credits: 0,
  max_concurrent_calls: null,
  is_active: true,
  sort_order: 0,
};

/** Admin catalogue of monthly plans clients can subscribe to. */
export const PlansPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Plan | 'new' | null>(null);
  const [draft, setDraft] = useState<PlanInput>(emptyDraft);
  const [saving, setSaving] = useState(false);

  const load = () =>
    plansService
      .list(true)
      .then(setPlans)
      .catch((err) => setError(err.message || 'Could not load plans.'));

  useEffect(() => {
    load();
  }, []);

  const openEditor = (plan: Plan | 'new') => {
    setError(null);
    setEditing(plan);
    setDraft(plan === 'new' ? { ...emptyDraft, sort_order: plans?.length ?? 0 } : { ...plan });
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body = { ...draft, description: draft.description || null };
      if (editing === 'new') await plansService.create(body);
      else if (editing) await plansService.update(editing.id, body);
      setEditing(null);
      await load();
    } catch (err: any) {
      setError(err.message || 'Could not save the plan.');
    } finally {
      setSaving(false);
    }
  };

  const valid = draft.name.trim() && draft.monthly_price_inr > 0 && draft.monthly_credits > 0;

  const columns: Column<Plan>[] = [
    {
      key: 'name',
      header: 'Plan',
      render: (p) => (
        <div>
          <span className="font-semibold text-slate-100">{p.name}</span>
          {p.description && <span className="block text-[11px] text-slate-500">{p.description}</span>}
        </div>
      ),
    },
    {
      key: 'price',
      header: 'Monthly fee',
      render: (p) => (
        <div className="font-mono">
          {inr(p.monthly_price_inr, 0)}
          <span className="block text-[11px] text-slate-500">{inr(p.monthly_price_with_gst_inr)} incl. GST</span>
        </div>
      ),
    },
    {
      key: 'credits',
      header: 'Credits / month',
      render: (p) => (
        <div className="font-mono">
          {p.monthly_credits.toLocaleString('en-IN')}
          <span className="block text-[11px] text-slate-500">≈ {p.approx_minutes.toLocaleString('en-IN')} min</span>
        </div>
      ),
    },
    { key: 'per_minute', header: 'Per minute', render: (p) => <span className="font-mono">{perMinuteRange(p)}</span> },
    { key: 'concurrency', header: 'Calls at a time', render: (p) => <span className="font-mono">{p.max_concurrent_calls ?? 'No limit'}</span> },
    { key: 'status', header: 'Status', render: (p) => <Badge variant={p.is_active ? 'green' : 'gray'}>{p.is_active ? 'AVAILABLE' : 'ARCHIVED'}</Badge> },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (p) =>
        isAdmin ? (
          <Button size="sm" variant="ghost" onClick={() => openEditor(p)}>
            <Pencil className="mr-1 h-3.5 w-3.5" /> Edit
          </Button>
        ) : null,
    },
  ];

  const numberField = (key: keyof PlanInput, label: string, hint?: string, step = '1') => (
    <label className="block space-y-1">
      <span className="text-slate-300">{label}</span>
      <input
        type="number"
        min={0}
        step={step}
        className={inputClass}
        value={(draft[key] as number | null) ?? ''}
        onChange={(e) => setDraft({ ...draft, [key]: e.target.value === '' ? 0 : Number(e.target.value) })}
      />
      {hint && <span className="block text-[11px] text-slate-500">{hint}</span>}
    </label>
  );

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-col justify-between gap-4 border-b border-[#102d38] pb-4 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#00df8f]/30 bg-[#00df8f]/15 text-[#00df8f]">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-100">Plans</h1>
            <p className="text-xs text-slate-400">
              Monthly plans clients subscribe to. Extra minutes are charged from their wallet; clients without a plan pay as they go.
            </p>
          </div>
        </div>
        {isAdmin && (
          <Button variant="primary" onClick={() => openEditor('new')}>
            <Plus className="mr-1.5 h-4 w-4" /> New plan
          </Button>
        )}
      </div>

      {error && !editing && (
        <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
        </div>
      )}

      <Card noPadding>
        {plans === null ? (
          <p className="p-6 text-xs text-slate-500">Loading plans...</p>
        ) : (
          <Table
            columns={columns}
            data={plans}
            keyExtractor={(p) => p.id}
            emptyState={
              <EmptyState
                icon={<Layers className="h-5 w-5" />}
                title="No plans yet"
                description="Create a plan, e.g. Starter: ₹3,000/month with 3,500 credits."
              />
            }
          />
        )}
      </Card>

      <NumberPricingCard isAdmin={isAdmin} />

      <Modal
        isOpen={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === 'new' ? 'New plan' : 'Edit plan'}
        description="Prices exclude GST; GST is added at checkout. Changes apply to current subscribers straight away."
      >
        <div className="space-y-3 text-xs">
          {error && (
            <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
            </div>
          )}
          <label className="block space-y-1">
            <span className="text-slate-300">Name</span>
            <input className={inputClass} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Growth" />
          </label>
          <label className="block space-y-1">
            <span className="text-slate-300">Description (shown to clients)</span>
            <input className={inputClass} value={draft.description || ''} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {numberField('monthly_price_inr', 'Monthly fee (₹, excl. GST)', undefined, '0.01')}
            {numberField('monthly_credits', 'Credits / month', '1 credit = ₹1. Expire at the end of each month; give more credits than the fee as a bonus.')}
            <label className="block space-y-1">
              <span className="text-slate-300">Calls at a time</span>
              <input
                type="number"
                min={1}
                className={inputClass}
                value={draft.max_concurrent_calls ?? ''}
                placeholder="No limit"
                onChange={(e) => setDraft({ ...draft, max_concurrent_calls: e.target.value === '' ? null : Number(e.target.value) })}
              />
              <span className="block text-[11px] text-slate-500">Leave empty for no limit</span>
            </label>
            {numberField('sort_order', 'Display order', 'Lower shows first')}
            <label className="flex items-center gap-2 self-center pt-4">
              <input type="checkbox" checked={draft.is_active} onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })} />
              <span className="text-slate-300">Available to clients</span>
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
            <Button variant="primary" disabled={!valid} isLoading={saving} onClick={save}>
              {editing === 'new' ? 'Create plan' : 'Save changes'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

/** Monthly rent Choranta charges for phone numbers, by type. */
const NumberPricingCard: React.FC<{ isAdmin: boolean }> = ({ isAdmin }) => {
  const [prices, setPrices] = useState<NumberPrice[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    plansService
      .numberPricing()
      .then((p) => {
        setPrices(p);
        setDrafts(Object.fromEntries(p.map((x) => [x.number_type, String(x.monthly_rent_inr)])));
      })
      .catch((err) => setError(err.message || 'Could not load number pricing.'));

  useEffect(() => {
    load();
  }, []);

  const save = async (price: NumberPrice, isAvailable = price.is_available) => {
    setBusy(price.number_type);
    setError(null);
    try {
      await plansService.updateNumberPricing(price.number_type, Number(drafts[price.number_type]), isAvailable);
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
      subtitle="What clients pay per number each month (excl. GST), charged from their wallet. New prices apply to numbers bought from now on."
    >
      {error && <p className="mb-3 text-xs text-rose-300">{error}</p>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {prices.map((p) => {
          const changed = Number(drafts[p.number_type]) !== p.monthly_rent_inr;
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
