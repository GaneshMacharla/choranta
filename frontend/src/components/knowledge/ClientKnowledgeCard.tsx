import React, { useEffect, useRef, useState } from 'react';
import { BookOpen, FileText, HelpCircle, Pencil, Plus, Trash2, Upload, X } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { catalogsService } from '../../services/catalogs';
import { KnowledgeSource } from '../../types';

type EntryType = 'NOTES' | 'FAQ';
interface Draft {
  id: string | null;
  name: string;
  type: EntryType;
  content: string;
}

const EMPTY: Draft = { id: null, name: '', type: 'NOTES', content: '' };
// AI employees read up to this much knowledge per call (runtime/knowledge.py)
const PER_CALL_CHARS = 8000;

const typeLabel = (t: string) => ({ FAQ: 'FAQ', NOTES: 'Notes', PDF: 'PDF', TEXT: 'Document' } as Record<string, string>)[t] || t;

/** Admin: the client's knowledge base. Its AI employees answer from the entries they're given. */
export const ClientKnowledgeCard: React.FC<{ clientId: string }> = ({ clientId }) => {
  const [entries, setEntries] = useState<KnowledgeSource[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = () =>
    catalogsService
      .listClientKnowledge(clientId)
      .then(setEntries)
      .catch((err) => setError(err.message || 'Could not load the knowledge base.'));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      return true;
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    const body = { name: draft.name.trim(), type: draft.type, content: draft.content.trim() };
    if (!body.name || !body.content) return setError('Add a title and some content.');
    const ok = await run(() =>
      draft.id ? catalogsService.updateClientKnowledge(clientId, draft.id, body) : catalogsService.createClientKnowledge(clientId, body)
    );
    if (ok) setDraft(null);
  };

  const upload = (file: File | undefined) => {
    if (file) run(() => catalogsService.uploadClientKnowledge(clientId, file));
    if (fileInput.current) fileInput.current.value = '';
  };

  const remove = (entry: KnowledgeSource) => {
    if (window.confirm(`Delete "${entry.name}"? AI employees using it will stop seeing it.`)) {
      run(() => catalogsService.deleteClientKnowledge(clientId, entry.id));
    }
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <BookOpen className="h-4 w-4 text-[#00df8f]" /> Knowledge base
        </span>
      }
      subtitle="Facts this client's AI employees answer from on calls: courses, fees, timings, policies, FAQs. Pick which ones each employee uses when you create it."
      action={
        <div className="flex gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.txt,.md,.csv"
            className="hidden"
            onChange={(e) => upload(e.target.files?.[0])}
          />
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => fileInput.current?.click()}>
            <Upload className="mr-1.5 h-3.5 w-3.5" /> Upload file
          </Button>
          <Button variant="primary" size="sm" disabled={busy} onClick={() => setDraft({ ...EMPTY })}>
            <Plus className="mr-1.5 h-3.5 w-3.5" /> Add entry
          </Button>
        </div>
      }
    >
      <div className="space-y-3 text-xs">
        {error && <p className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-rose-300">{error}</p>}

        {draft && (
          <div className="space-y-2 rounded-lg border border-[#1b3a46] bg-[#06141a] p-3">
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                className="flex-1 rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none"
                placeholder="Title, e.g. Course fees and batches"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
              <div className="flex rounded border border-[#153945] p-0.5">
                {(['NOTES', 'FAQ'] as EntryType[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setDraft({ ...draft, type: t })}
                    className={`rounded px-3 py-1.5 ${draft.type === t ? 'bg-[#00df8f]/15 font-semibold text-[#00df8f]' : 'text-slate-400'}`}
                  >
                    {t === 'NOTES' ? 'Notes' : 'FAQ'}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              rows={6}
              className="w-full rounded border border-[#153945] bg-[#071419] p-2.5 text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none"
              placeholder={
                draft.type === 'FAQ'
                  ? 'Q: What is the fee?\nA: 25,000 rupees, payable in 2 instalments.\n\nQ: Is there a demo class?\nA: Yes, free, every Monday.'
                  : 'Write the facts in plain sentences: courses, fees, timings, address, offers, policies...'
              }
              value={draft.content}
              onChange={(e) => setDraft({ ...draft, content: e.target.value })}
            />
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-slate-500">{draft.content.length.toLocaleString()} characters</span>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => setDraft(null)}>
                  <X className="mr-1 h-3.5 w-3.5" /> Cancel
                </Button>
                <Button variant="primary" size="sm" isLoading={busy} onClick={save}>
                  {draft.id ? 'Save changes' : 'Add to knowledge base'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {entries === null ? (
          <p className="text-slate-500">Loading knowledge base...</p>
        ) : entries.length === 0 && !draft ? (
          <p className="rounded-lg border border-dashed border-[#1b3a46] p-4 text-center text-slate-500">
            No knowledge yet. Add notes or FAQs, or upload a brochure (PDF), so this client's AI employees can answer questions
            correctly instead of offering a callback.
          </p>
        ) : (
          <ul className="divide-y divide-[#102d38] rounded-lg border border-[#102d38]">
            {entries.map((entry) => {
              const editable = entry.type === 'NOTES' || entry.type === 'FAQ';
              const chars = (entry.content || '').length;
              return (
                <li key={entry.id} className="flex items-start justify-between gap-3 p-3">
                  <span className="flex min-w-0 gap-2.5">
                    {entry.type === 'FAQ' ? (
                      <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#00df8f]" />
                    ) : (
                      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[#00df8f]" />
                    )}
                    <span className="min-w-0">
                      <span className="block truncate font-semibold text-slate-200">{entry.name}</span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">
                        {typeLabel(entry.type)} · {chars.toLocaleString()} characters
                        {chars > PER_CALL_CHARS && ' · only the first ~8,000 are read on a call'}
                        {entry.metadata?.truncated && ' · long file, trimmed'}
                      </span>
                      <span className="mt-1 line-clamp-2 block text-slate-400">{entry.content}</span>
                    </span>
                  </span>
                  <span className="flex shrink-0 gap-1">
                    {editable && (
                      <button
                        type="button"
                        title="Edit"
                        onClick={() => setDraft({ id: entry.id, name: entry.name, type: entry.type as EntryType, content: entry.content || '' })}
                        className="rounded p-1.5 text-slate-400 hover:bg-[#0c2129] hover:text-slate-100"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <button
                      type="button"
                      title="Delete"
                      onClick={() => remove(entry)}
                      className="rounded p-1.5 text-slate-400 hover:bg-[#0c2129] hover:text-rose-300"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
};
