import React, { useEffect, useState } from 'react';
import { AlertTriangle, BadgeCheck, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { Condition, QualificationField, QualificationSetup, Rules, portalQualification } from '../../services/qualification';

const OP_LABEL: Record<string, string> = {
  is_true: 'is yes',
  is_false: 'is no',
  is_set: 'was given',
  gte: 'is at least',
  lte: 'is at most',
  eq: 'equals',
  in: 'is one of',
  contains: 'mentions',
};

const fieldClass =
  'rounded-md border border-[#143c49] bg-[#06141a] px-2 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';

const defaultCondition = (field: QualificationField, ops: QualificationSetup['ops']): Condition => {
  const op = ops[field.data_type][0];
  if (op === 'in') return { field: field.name, op, value: field.data_type === 'interest' ? ['interested'] : [] };
  if (['gte', 'lte', 'eq'].includes(op)) return { field: field.name, op, value: 0 };
  return { field: field.name, op };
};

const ConditionRow: React.FC<{
  setup: QualificationSetup;
  condition: Condition;
  onChange: (c: Condition) => void;
  onRemove: () => void;
}> = ({ setup, condition, onChange, onRemove }) => {
  const field = setup.fields.find((f) => f.name === condition.field) || setup.fields[0];
  const ops = setup.ops[field.data_type];
  const values = Array.isArray(condition.value) ? condition.value : [];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        aria-label="Detail"
        className={fieldClass}
        value={field.name}
        onChange={(e) => onChange(defaultCondition(setup.fields.find((f) => f.name === e.target.value)!, setup.ops))}
      >
        {setup.fields.map((f) => (
          <option key={f.name} value={f.name}>
            {f.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Check"
        className={fieldClass}
        value={condition.op}
        onChange={(e) => {
          const op = e.target.value;
          onChange({ field: field.name, op, value: op === 'in' ? values : ['gte', 'lte', 'eq'].includes(op) ? 0 : op === 'contains' ? '' : undefined });
        }}
      >
        {ops.map((op) => (
          <option key={op} value={op}>
            {OP_LABEL[op] || op}
          </option>
        ))}
      </select>

      {condition.op === 'in' && field.data_type === 'interest' && (
        <span className="flex flex-wrap gap-2 text-xs text-slate-300">
          {setup.interest_values.map((v) => (
            <label key={v.value} className="flex items-center gap-1">
              <input
                type="checkbox"
                className="accent-[#00df8f]"
                checked={values.includes(v.value)}
                onChange={() =>
                  onChange({ ...condition, value: values.includes(v.value) ? values.filter((x) => x !== v.value) : [...values, v.value] })
                }
              />
              {v.label}
            </label>
          ))}
        </span>
      )}
      {condition.op === 'in' && field.data_type !== 'interest' && (
        <input
          aria-label="Values"
          className={`${fieldClass} min-w-[12rem] flex-1`}
          placeholder="NEET, JEE (comma separated)"
          value={values.join(', ')}
          onChange={(e) => onChange({ ...condition, value: e.target.value.split(',').map((v) => v.trimStart()) })}
        />
      )}
      {condition.op === 'contains' && (
        <input
          aria-label="Text"
          className={`${fieldClass} min-w-[10rem] flex-1`}
          value={String(condition.value ?? '')}
          onChange={(e) => onChange({ ...condition, value: e.target.value })}
        />
      )}
      {['gte', 'lte', 'eq'].includes(condition.op) && (
        <input
          aria-label="Number"
          type="number"
          className={`${fieldClass} w-24`}
          value={String(condition.value ?? '')}
          onChange={(e) => onChange({ ...condition, value: e.target.value === '' ? '' : Number(e.target.value) })}
        />
      )}
      <button type="button" aria-label="Remove condition" onClick={onRemove} className="text-slate-500 hover:text-rose-400">
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
};

const cleanRules = (rules: Rules): Rules =>
  rules
    .map((group) =>
      group.map((c) => (Array.isArray(c.value) ? { ...c, value: c.value.map((v) => v.trim()).filter(Boolean) } : c)),
    )
    .filter((group) => group.length > 0);

const SetupEditor: React.FC<{ setup: QualificationSetup; onSaved: (s: QualificationSetup) => void }> = ({ setup, onSaved }) => {
  const [rules, setRules] = useState<Rules>(setup.configured ? setup.rules : []);
  const [criteria, setCriteria] = useState(setup.ai_criteria || '');
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const update = (next: Rules) => {
    setRules(next);
    setNotice(null);
  };
  const setCondition = (g: number, i: number, c: Condition) => update(rules.map((group, gi) => (gi === g ? group.map((x, xi) => (xi === i ? c : x)) : group)));
  const removeCondition = (g: number, i: number) => update(rules.map((group, gi) => (gi === g ? group.filter((_, xi) => xi !== i) : group)).filter((group) => group.length));
  const addCondition = (g: number) => update(rules.map((group, gi) => (gi === g ? [...group, defaultCondition(setup.fields[0], setup.ops)] : group)));
  const addGroup = () => update([...rules, [defaultCondition(setup.fields[0], setup.ops)]]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const saved = await portalQualification.save(setup.agent_id, { rules: cleanRules(rules), ai_criteria: criteria.trim() || null });
      onSaved(saved);
      setRules(saved.rules);
      setNotice('Saved. New calls use these rules.');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const recheck = async () => {
    setChecking(true);
    setError(null);
    try {
      const { changed, days } = await portalQualification.reevaluate(setup.agent_id);
      setNotice(`Re-checked the last ${days} days of calls: ${changed} changed.`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="space-y-3 px-5 py-4">
      <div className="text-sm font-semibold text-slate-100">{setup.agent_name}</div>

      {rules.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          {setup.configured ? 'No rules.' : 'Not set up: interested callers and callback requests count as qualified.'}
          <Button size="sm" variant="secondary" onClick={() => update(setup.suggested_rules)}>
            Start from a suggestion
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-xs text-slate-400">A caller is qualified if they match any of these:</div>
          {rules.map((group, g) => (
            <React.Fragment key={g}>
              {g > 0 && <div className="pl-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">or</div>}
              <div className="space-y-2 rounded-lg border border-[#102d38] bg-[#06141a]/60 p-3">
                {group.map((c, i) => (
                  <React.Fragment key={i}>
                    {i > 0 && <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">and</div>}
                    <ConditionRow setup={setup} condition={c} onChange={(next) => setCondition(g, i, next)} onRemove={() => removeCondition(g, i)} />
                  </React.Fragment>
                ))}
                <button type="button" className="text-xs text-[#00df8f] hover:underline" onClick={() => addCondition(g)}>
                  + and…
                </button>
              </div>
            </React.Fragment>
          ))}
          <Button size="sm" variant="ghost" leftIcon={<Plus className="h-3.5 w-3.5" />} onClick={addGroup}>
            Add another way to qualify
          </Button>
        </div>
      )}

      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-slate-300" htmlFor={`ai-criteria-${setup.agent_id}`}>
          When a detail is missing, also ask the AI (optional)
        </label>
        <textarea
          id={`ai-criteria-${setup.agent_id}`}
          rows={2}
          maxLength={500}
          value={criteria}
          onChange={(e) => {
            setCriteria(e.target.value);
            setNotice(null);
          }}
          placeholder="e.g. Plans to join a course this year and the fees suit them"
          className="block w-full rounded-md border border-[#143c49] bg-[#06141a] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none"
        />
        <p className="text-[11px] text-slate-500">
          After each call the AI answers yes, no or can't tell, with a reason. Your rules decide first; this is used when they can't.
        </p>
      </div>

      {error && (
        <p className="flex items-start gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="primary" isLoading={saving} onClick={save}>
          Save
        </Button>
        {setup.configured && (
          <Button size="sm" variant="ghost" isLoading={checking} leftIcon={<RefreshCw className="h-3.5 w-3.5" />} onClick={recheck}>
            Re-check recent calls
          </Button>
        )}
        {notice && <span className="text-xs text-[#00df8f]">{notice}</span>}
      </div>
    </div>
  );
};

/** Per AI employee: what makes a caller a qualified lead (hot leads, WhatsApp follow-ups, lead status). */
export const QualificationSettings: React.FC = () => {
  const [setups, setSetups] = useState<QualificationSetup[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    portalQualification
      .list()
      .then(setSetups)
      .catch((e) => setError(e.message || 'Could not load lead qualification.'));
  }, []);

  if (error) return <p className="text-xs text-rose-300">{error}</p>;
  if (!setups || setups.length === 0) return null;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <BadgeCheck className="h-4 w-4 text-[#00df8f]" /> Who is a qualified lead
        </span>
      }
      subtitle="Qualified callers appear in Hot leads, can get your WhatsApp follow-up, and are marked Qualified on the lead."
      noPadding
    >
      <div className="divide-y divide-[#102d38]">
        {setups.map((s) => (
          <SetupEditor key={s.agent_id} setup={s} onSaved={(saved) => setSetups((all) => all && all.map((x) => (x.agent_id === saved.agent_id ? saved : x)))} />
        ))}
      </div>
    </Card>
  );
};
