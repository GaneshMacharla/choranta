import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { BookOpen, CheckCircle2, Circle, ClipboardList, HelpCircle, StickyNote } from 'lucide-react';
import { Card } from '../common/Card';
import { KnowledgeSource } from '../../types';
import { KnowledgeOverview, clientKnowledge } from '../../services/knowledge';
import { DocumentCard } from './KnowledgeBase';

const Tick: React.FC<{ on: boolean; onClick: () => void; label: string }> = ({ on, onClick, label }) => (
  <button type="button" title={on ? `Stop using ${label}` : `Use ${label}`} aria-label={label} onClick={onClick} className="shrink-0">
    {on ? <CheckCircle2 className="h-4 w-4 text-[#00df8f]" /> : <Circle className="h-4 w-4 text-slate-600" />}
  </button>
);

/**
 * Build tab "5. Knowledge": the client's documents for the team to download and read while writing this employee's
 * own knowledge (no AI employee reads them), plus older notes and details with a tick for whether it answers from them.
 */
export const AgentKnowledgeSources: React.FC<{
  clientId: string;
  clientName?: string;
  selected: string[];
  onToggle: (id: string) => void;
  onDeleted: (id: string) => void;
}> = ({ clientId, clientName, selected, onToggle, onDeleted }) => {
  const api = useMemo(() => clientKnowledge(clientId), [clientId]);
  const [data, setData] = useState<KnowledgeOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = () => api.overview().then(setData).catch((e) => setError(e.message || 'Could not load the knowledge base.'));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const remove = async (entry: KnowledgeSource) => {
    if (!window.confirm(`Delete "${entry.name}" from ${clientName || "the client"}'s knowledge base? This can't be undone.`)) return;
    setDeleting(entry.id);
    setError(null);
    try {
      await api.deleteEntry(entry.id);
      onDeleted(entry.id);
      await load();
    } catch (e: any) {
      setError(e.message || 'Could not delete.');
    } finally {
      setDeleting(null);
    }
  };

  const download = (entry: KnowledgeSource) => {
    setError(null);
    api.download(entry).catch((e: any) => setError(e.message || 'Download failed.'));
  };

  const entries = data?.entries || [];
  const documents = entries.filter((e) => e.type === 'DOCUMENT' || e.type === 'PDF' || e.type === 'TEXT');
  const notes = entries.filter((e) => e.type === 'NOTES' || e.type === 'FAQ');
  const filledDetails = (data?.fields || []).filter((f) => f.value);

  return (
    <Card
      title={<span className="flex items-center gap-2 text-sm font-semibold text-slate-100"><BookOpen className="h-4 w-4 text-[#00df8f]" /> 5. Knowledge</span>}
      subtitle={`Documents ${clientName || 'the client'} uploaded, for you to read. This employee never reads them: write what it needs to know in its own knowledge below.`}
      action={<Link to={`/clients/${clientId}`} className="text-xs text-[#00df8f] hover:underline">Review knowledge base</Link>}
    >
      <div className="space-y-3 text-xs">
        {error && <p className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-rose-300">{error}</p>}
        {!data ? (
          !error && <p className="text-slate-500">Loading knowledge base...</p>
        ) : (
          <>
            {documents.length === 0 && (
              <p className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5 text-amber-200">
                {clientName || 'The client'} hasn't uploaded any documents yet. They upload them under Knowledge in their portal.
              </p>
            )}

            {data.details_id && filledDetails.length > 0 && (
              <div className="rounded-lg border border-[#143c49] bg-[#071419] p-3">
                <div className="flex items-center gap-2">
                  <Tick on={selected.includes(data.details_id)} onClick={() => onToggle(data.details_id!)} label="Business details" />
                  <ClipboardList className="h-4 w-4 text-[#00df8f]" />
                  <span className="font-semibold text-slate-200">Business details</span>
                  <span className="ml-auto text-[10px] text-slate-500">{filledDetails.length} filled</span>
                </div>
                {filledDetails.length > 0 && (
                  <dl className="mt-2 grid grid-cols-1 gap-x-3 gap-y-1 pl-6 sm:grid-cols-[max-content_1fr]">
                    {filledDetails.map((f) => (
                      <React.Fragment key={f.key}>
                        <dt className="text-slate-500">{f.label}</dt>
                        <dd className="truncate text-slate-300" title={f.value}>{f.value}</dd>
                      </React.Fragment>
                    ))}
                  </dl>
                )}
              </div>
            )}

            {documents.length > 0 && (
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {documents.map((d) => (
                  <DocumentCard key={d.id} entry={d} busy={deleting === d.id} onDownload={download} onDelete={remove} />
                ))}
              </div>
            )}

            {notes.length > 0 && (
              <div className="space-y-1.5">
                {notes.map((n) => (
                  <div key={n.id} className="flex items-center gap-2 rounded border border-[#102d38] px-3 py-2">
                    <Tick on={selected.includes(n.id)} onClick={() => onToggle(n.id)} label={n.name} />
                    {n.type === 'FAQ' ? <HelpCircle className="h-3.5 w-3.5 text-sky-400" /> : <StickyNote className="h-3.5 w-3.5 text-amber-300" />}
                    <span className="truncate text-slate-200">{n.name}</span>
                    <span className="ml-auto text-[10px] text-slate-500">{(n.content || '').length.toLocaleString()} chars</span>
                  </div>
                ))}
              </div>
            )}

          </>
        )}
      </div>
    </Card>
  );
};
