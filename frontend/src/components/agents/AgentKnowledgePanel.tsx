import React, { useEffect, useState } from 'react';
import { AlertTriangle, BookOpen, HelpCircle, Pencil, Plus, StickyNote, Trash2 } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { catalogsService } from '../../services/catalogs';
import { KnowledgeSource } from '../../types';

type EntryType = 'NOTES' | 'FAQ';

const PLACEHOLDERS: Record<EntryType, string> = {
  NOTES:
    'e.g. Smile Dental Care, Kukatpally, Hyderabad. Open 10am-8pm, closed Sundays.\nConsultation fee Rs 300. Cleaning Rs 1,200. Root canal from Rs 4,500.\nParking available in the basement.',
  FAQ: 'Q: Do you accept insurance?\nA: Yes, we accept Star Health and ICICI Lombard.\n\nQ: Is there parking?\nA: Yes, free parking in the basement.',
};

interface Draft {
  id?: string;
  name: string;
  type: EntryType;
  content: string;
}

const EMPTY: Draft = { name: '', type: 'NOTES', content: '' };

/**
 * One AI employee's own knowledge: notes and FAQs it reads on every conversation (no republish needed).
 * Shared library entries can still be attached below it.
 */
export const AgentKnowledgePanel: React.FC<{ agentId: string; onChange?: () => void }> = ({ agentId, onChange }) => {
  const [entries, setEntries] = useState<KnowledgeSource[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    catalogsService
      .getAgentKnowledge(agentId)
      .then((all) => setEntries(all.filter((k) => k.owner_agent_id === agentId)))
      .catch((e) => setError(e.message || 'Could not load knowledge.'));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const body = { name: draft.name.trim(), type: draft.type, content: draft.content.trim() };
      if (draft.id) await catalogsService.updateAgentKnowledge(agentId, draft.id, body);
      else await catalogsService.createAgentKnowledge(agentId, body);
      setDraft(null);
      await load();
      onChange?.();
    } catch (e: any) {
      setError(e.message || 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entry: KnowledgeSource) => {
    if (!window.confirm(`Delete "${entry.name}"? This AI employee will stop using it.`)) return;
    try {
      await catalogsService.detachKnowledge(agentId, entry.id);
      await load();
      onChange?.();
    } catch (e: any) {
      setError(e.message || 'Could not delete.');
    }
  };

  const valid = !!draft && draft.name.trim().length > 0 && draft.content.trim().length > 0;
  const totalChars = (entries || []).reduce((sum, e) => sum + (e.content?.length || 0), 0);

  return (
    <Card
      title={`This AI employee's knowledge (${entries?.length ?? 0})`}
      subtitle="Facts it uses to answer callers: timings, prices, services, policies, FAQs. Changes apply from the next call."
    >
      <div className="space-y-4 text-xs">
        {error && (
          <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        {entries === null ? (
          <p className="text-slate-500">Loading...</p>
        ) : entries.length === 0 && !draft ? (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-[#232736] py-8 text-center">
            <BookOpen className="h-7 w-7 text-slate-500" />
            <p className="text-sm text-slate-300">No knowledge yet</p>
            <p className="max-w-md text-slate-500">Add notes or FAQs about the business so the AI employee answers with real facts instead of guessing.</p>
          </div>
        ) : (
          <ul className="divide-y divide-[#1b1f2d]">
            {entries.map((e) => (
              <li key={e.id} className="flex items-start justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {e.type === 'FAQ' ? <HelpCircle className="h-3.5 w-3.5 text-sky-400" /> : <StickyNote className="h-3.5 w-3.5 text-amber-300" />}
                    <span className="text-sm font-semibold text-slate-200">{e.name}</span>
                    <span className="rounded bg-[#1b1f2d] px-1.5 py-0.5 text-[10px] text-slate-400">{e.type === 'FAQ' ? 'FAQ' : 'Notes'}</span>
                  </div>
                  <p className="mt-1 line-clamp-3 whitespace-pre-line text-slate-400">{e.content}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    aria-label={`Edit ${e.name}`}
                    className="rounded p-1.5 text-slate-400 hover:bg-[#151824] hover:text-slate-200"
                    onClick={() => setDraft({ id: e.id, name: e.name, type: (e.type as EntryType) === 'FAQ' ? 'FAQ' : 'NOTES', content: e.content || '' })}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${e.name}`}
                    className="rounded p-1.5 text-slate-400 hover:bg-[#151824] hover:text-rose-400"
                    onClick={() => remove(e)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {draft ? (
          <div className="space-y-3 rounded-lg border border-[#232736] bg-[#0c0e14] p-4">
            <div className="flex flex-wrap items-end gap-3">
              <label className="min-w-[220px] flex-1 space-y-1">
                <span className="block font-medium text-slate-300">Title</span>
                <input
                  className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
                  placeholder="e.g. Timings & prices"
                  value={draft.name}
                  onChange={(ev) => setDraft({ ...draft, name: ev.target.value })}
                />
              </label>
              <div className="flex rounded-full bg-[#151824] p-0.5">
                {(['NOTES', 'FAQ'] as EntryType[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setDraft({ ...draft, type: t })}
                    className={`rounded-full px-3 py-1 font-medium ${draft.type === t ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300'}`}
                  >
                    {t === 'FAQ' ? 'FAQ' : 'Notes'}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              rows={8}
              className="w-full rounded border border-[#232736] bg-[#10121a] p-2.5 font-mono text-[12px] text-slate-100 placeholder-slate-600"
              placeholder={PLACEHOLDERS[draft.type]}
              value={draft.content}
              onChange={(ev) => setDraft({ ...draft, content: ev.target.value })}
            />
            <p className="text-[11px] text-slate-500">
              {draft.type === 'FAQ' ? 'Write each question as "Q:" and its answer as "A:".' : 'Short, plain facts work best.'} Keep the total under
              about 8,000 characters per AI employee.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setDraft(null)}>Cancel</Button>
              <Button variant="primary" size="sm" disabled={!valid || saving} isLoading={saving} onClick={save}>
                {draft.id ? 'Save changes' : 'Add knowledge'}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-500">{totalChars > 0 ? `${totalChars.toLocaleString('en-IN')} characters` : ''}</span>
            <Button variant="primary" size="sm" leftIcon={<Plus className="h-3.5 w-3.5" />} onClick={() => setDraft({ ...EMPTY })}>
              Add knowledge
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
};
