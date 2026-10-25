import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Circle, Download, File as FileIcon, FileSpreadsheet, FileText, HelpCircle, Image as ImageIcon,
  Pencil, Plus, StickyNote, Trash2, UploadCloud, X,
} from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { KnowledgeSource } from '../../types';
import { DetailField, KnowledgeOverview, NoteBody, formatBytes, knowledgeApi } from '../../services/knowledge';

type Api = ReturnType<typeof knowledgeApi>;
type EntryType = 'NOTES' | 'FAQ';
interface Draft extends NoteBody {
  id: string | null;
}

const FIELD = 'w-full rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';
const PLACEHOLDERS: Record<EntryType, string> = {
  NOTES:
    'e.g. Smile Dental Care, Kukatpally, Hyderabad. Open 10am-8pm, closed Sundays.\nConsultation fee Rs 300. Cleaning Rs 1,200. Root canal from Rs 4,500.\nParking available in the basement.',
  FAQ: 'Q: Do you accept insurance?\nA: Yes, we accept Star Health and ICICI Lombard.\n\nQ: Is there parking?\nA: Yes, free parking in the basement.',
};

export const fileIcon = (entry: KnowledgeSource) => {
  const name = (entry.metadata?.file?.name || entry.name || '').toLowerCase();
  if (/\.(png|jpe?g|gif|webp|heic|bmp)$/.test(name)) return ImageIcon;
  if (/\.(xlsx?|xlsm|csv|tsv)$/.test(name)) return FileSpreadsheet;
  if (/\.(pdf|docx?|txt|md|rtf)$/.test(name)) return FileText;
  return FileIcon;
};

/** One line under a document's name: size, when, who added it, and whether its text could be read. */
export const documentLine = (entry: KnowledgeSource) => {
  const parts: string[] = [];
  if (entry.metadata?.file?.size_bytes) parts.push(formatBytes(entry.metadata.file.size_bytes));
  parts.push(new Date(entry.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }));
  if (entry.metadata?.added_by?.role) parts.push(entry.metadata.added_by.role === 'CLIENT' ? 'from the client' : 'by Choranta');
  return parts.join(' · ');
};

export const TextStatus: React.FC<{ entry: KnowledgeSource }> = ({ entry }) => {
  const status = entry.metadata?.text_status;
  if (status === 'NO_TEXT') return <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300">No readable text</span>;
  if (status === 'TRUNCATED') return <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300">Long file, trimmed</span>;
  return <span className="rounded bg-[#00df8f]/10 px-1.5 py-0.5 text-[10px] text-[#00df8f]">Read by AI</span>;
};

/**
 * A client's knowledge base: the business details its type of business should give, documents (any type, any
 * number) and extra notes/FAQs. Only the client adds to it, in the portal ("client"); Choranta's team reviews it
 * ("team"): sees the gaps, downloads documents and deletes what's wrong.
 */
export const KnowledgeBase: React.FC<{ api: Api; mode: 'client' | 'team' }> = ({ api, mode }) => {
  const [data, setData] = useState<KnowledgeOverview | null>(null);
  const [values, setValues] = useState<Record<string, { value: string; in_documents: boolean }>>({});
  const [detailsDirty, setDetailsDirty] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      const o = await api.overview();
      setData(o);
      setValues(Object.fromEntries(o.fields.map((f) => [f.key, { value: f.value, in_documents: f.in_documents }])));
      setDetailsDirty(false);
    } catch (err: any) {
      setError(err.message || 'Could not load the knowledge base.');
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const run = async (label: string, action: () => Promise<unknown>, done?: string) => {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      await action();
      await load();
      if (done) setNotice(done);
      return true;
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
      return false;
    } finally {
      setBusy(null);
    }
  };

  const setField = (key: string, patch: Partial<{ value: string; in_documents: boolean }>) => {
    setValues((prev) => ({ ...prev, [key]: { ...(prev[key] || { value: '', in_documents: false }), ...patch } }));
    setDetailsDirty(true);
  };

  const upload = (list: FileList | null) => {
    const files = Array.from(list || []);
    if (fileInput.current) fileInput.current.value = '';
    if (!files.length || !data) return;
    const tooBig = files.find((f) => f.size > data.storage.max_file_bytes);
    if (tooBig) return setError(`${tooBig.name} is over ${formatBytes(data.storage.max_file_bytes)}.`);
    run('upload', () => api.upload(files), `${files.length} ${files.length === 1 ? 'document' : 'documents'} added.`);
  };

  const saveNote = async () => {
    if (!draft) return;
    const body = { name: draft.name.trim(), type: draft.type, content: draft.content.trim() };
    if (!body.name || !body.content) return setError('Add a title and some details.');
    const ok = await run('note', () => (draft.id ? api.updateEntry(draft.id, body) : api.createNote(body)));
    if (ok) setDraft(null);
  };

  const remove = (entry: KnowledgeSource) => {
    const who = mode === 'team' ? "This client's AI employees" : 'Your AI employees';
    if (window.confirm(`Delete "${entry.name}"? ${who} will stop using it. This can't be undone.`)) {
      run(`delete:${entry.id}`, () => api.deleteEntry(entry.id));
    }
  };

  const download = (entry: KnowledgeSource) => {
    setError(null);
    api.download(entry).catch((err: any) => setError(err.message || 'Download failed.'));
  };

  if (!data) {
    return error ? <ErrorBox text={error} /> : <p className="text-xs text-slate-500">Loading knowledge base...</p>;
  }

  const documents = data.entries.filter((e) => e.type === 'DOCUMENT' || e.type === 'PDF' || e.type === 'TEXT');
  const notes = data.entries.filter((e) => e.type === 'NOTES' || e.type === 'FAQ');
  const required = data.fields.filter((f) => f.required);
  const covered = required.length - data.gaps.length;
  const team = mode === 'team';

  return (
    <div className="space-y-4">
      {error && <ErrorBox text={error} />}
      {notice && <p className="rounded border border-[#00df8f]/30 bg-[#00df8f]/10 p-2 text-xs text-[#00df8f]">{notice}</p>}

      <GapsSummary data={data} covered={covered} total={required.length} mode={mode} />

      <Card
        title="1. Business details"
        subtitle={
          mode === 'client'
            ? 'What every caller asks about. Type it in, or tick "In my documents" if a file you upload below has it.'
            : 'What the client has filled in. Missing required fields are the gaps to ask them about.'
        }
      >
        {team ? (
          <dl className="grid grid-cols-1 gap-x-4 gap-y-2.5 text-xs md:grid-cols-2">
            {data.fields.map((f) => <DetailView key={f.key} field={f} />)}
          </dl>
        ) : (
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 md:grid-cols-2">
            {data.fields.map((f) => (
              <DetailInput key={f.key} field={f} value={values[f.key] || { value: '', in_documents: false }} onChange={(patch) => setField(f.key, patch)} />
            ))}
          </div>
        )}
        {!team && <div className="mt-4 flex items-center justify-end gap-3">
          {detailsDirty && <span className="text-[11px] text-amber-300">Unsaved changes</span>}
          <Button variant="primary" size="sm" disabled={!detailsDirty || !!busy} isLoading={busy === 'details'}
            onClick={() => run('details', () => api.saveDetails(values), 'Business details saved.')}>
            Save details
          </Button>
        </div>}
      </Card>

      <Card
        title={`2. Documents (${documents.length})`}
        subtitle={team ? 'Files the client uploaded. Download them to check for anything the AI employee is missing.'
          : 'Brochures, price lists, menus, fee charts, prospectus, photos: any file, as many as you like.'}
      >
        {team ? (
          documents.length === 0 && <p className="text-xs text-slate-500">The client hasn't uploaded any documents yet.</p>
        ) : (<>
        <input ref={fileInput} type="file" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
        <button
          type="button"
          disabled={!!busy}
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files); }}
          className={`flex w-full flex-col items-center gap-1.5 rounded-lg border border-dashed p-6 text-center transition-colors ${
            dragging ? 'border-[#00df8f] bg-[#00df8f]/10' : 'border-[#1b3a46] hover:border-[#00df8f]/60'
          }`}
        >
          <UploadCloud className="h-7 w-7 text-[#00df8f]" />
          <span className="text-sm font-medium text-slate-200">{busy === 'upload' ? 'Uploading...' : 'Drop files here or click to choose'}</span>
          <span className="text-[11px] text-slate-500">
            Up to {formatBytes(data.storage.max_file_bytes)} each. PDF, Word, Excel and text files are read automatically.
          </span>
        </button>
        </>)}
        <StorageMeter used={data.storage.used_bytes} quota={data.storage.quota_bytes} />

        {documents.length > 0 && (
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {documents.map((d) => (
              <DocumentCard key={d.id} entry={d} busy={busy === `delete:${d.id}`} onDownload={download} onDelete={remove} />
            ))}
          </div>
        )}
      </Card>

      <Card
        title={`3. Additional details (${notes.length})`}
        subtitle={team ? 'Notes and FAQs the client wrote.' : 'Anything else your AI employee should know: offers, common questions, what to say when...'}
        action={!team && !draft && (
          <Button variant="primary" size="sm" leftIcon={<Plus className="h-3.5 w-3.5" />} onClick={() => setDraft({ id: null, name: '', type: 'NOTES', content: '' })}>
            Add details
          </Button>
        )}
      >
        <div className="space-y-3 text-xs">
          {draft && (
            <div className="space-y-3 rounded-lg border border-[#1b3a46] bg-[#06141a] p-4">
              <div className="flex flex-wrap items-end gap-3">
                <label className="min-w-[220px] flex-1 space-y-1">
                  <span className="block font-medium text-slate-300">Title</span>
                  <input className={FIELD} placeholder="e.g. Timings & prices" value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                </label>
                <div className="flex rounded-full bg-[#0c2129] p-0.5">
                  {(['NOTES', 'FAQ'] as EntryType[]).map((t) => (
                    <button key={t} type="button" onClick={() => setDraft({ ...draft, type: t })}
                      className={`rounded-full px-3 py-1 font-medium ${draft.type === t ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300'}`}>
                      {t === 'FAQ' ? 'FAQ' : 'Notes'}
                    </button>
                  ))}
                </div>
              </div>
              <textarea rows={7} className={`${FIELD} font-mono text-[12px]`} placeholder={PLACEHOLDERS[draft.type]} value={draft.content}
                onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
              <p className="text-[11px] text-slate-500">
                {draft.type === 'FAQ' ? 'Write each question as "Q:" and its answer as "A:". ' : ''}Short, plain facts work best.
              </p>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" size="sm" onClick={() => setDraft(null)}><X className="mr-1 h-3.5 w-3.5" /> Cancel</Button>
                <Button variant="primary" size="sm" isLoading={busy === 'note'} onClick={saveNote}>{draft.id ? 'Save changes' : 'Add knowledge'}</Button>
              </div>
            </div>
          )}
          {notes.length === 0 && !draft ? (
            <p className="text-slate-500">Nothing added yet.</p>
          ) : (
            <ul className="divide-y divide-[#102d38] rounded-lg border border-[#102d38]">
              {notes.map((n) => (
                <li key={n.id} className="flex items-start justify-between gap-3 p-3">
                  <span className="flex min-w-0 gap-2.5">
                    {n.type === 'FAQ' ? <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" /> : <StickyNote className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />}
                    <span className="min-w-0">
                      <span className="block truncate font-semibold text-slate-200">{n.name}</span>
                      <span className="mt-1 line-clamp-2 block whitespace-pre-line text-slate-400">{n.content}</span>
                    </span>
                  </span>
                  <span className="flex shrink-0 gap-1">
                    {!team && <IconButton label={`Edit ${n.name}`} onClick={() => setDraft({ id: n.id, name: n.name, type: n.type as EntryType, content: n.content || '' })}>
                      <Pencil className="h-3.5 w-3.5" />
                    </IconButton>}
                    <IconButton label={`Delete ${n.name}`} danger onClick={() => remove(n)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
};

const ErrorBox: React.FC<{ text: string }> = ({ text }) => (
  <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-xs text-rose-300">
    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {text}
  </div>
);

export const IconButton: React.FC<{ label: string; onClick: () => void; danger?: boolean; disabled?: boolean; children: React.ReactNode }> = ({
  label, onClick, danger, disabled, children,
}) => (
  <button type="button" title={label} aria-label={label} disabled={disabled} onClick={onClick}
    className={`rounded p-1.5 text-slate-400 hover:bg-[#0c2129] disabled:opacity-40 ${danger ? 'hover:text-rose-300' : 'hover:text-slate-100'}`}>
    {children}
  </button>
);

/** How much of the knowledge base is there, and what's still missing. */
export const GapsSummary: React.FC<{ data: KnowledgeOverview; covered: number; total: number; mode: 'client' | 'team' }> = ({ data, covered, total, mode }) => {
  const pct = total ? Math.round((covered / total) * 100) : 100;
  const complete = data.gaps.length === 0;
  return (
    <div className={`rounded-lg border p-4 ${complete ? 'border-[#00df8f]/30 bg-[#00df8f]/5' : 'border-amber-500/30 bg-amber-500/5'}`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-100">
          {complete ? 'All required details are covered' : `${covered} of ${total} required details covered`}
        </p>
        <span className="text-xs text-slate-400">{pct}%</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#0c2129]">
        <div className={`h-full rounded-full ${complete ? 'bg-[#00df8f]' : 'bg-amber-400'}`} style={{ width: `${pct}%` }} />
      </div>
      {!complete && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="text-slate-400">{mode === 'team' ? 'Gaps:' : 'Still needed:'}</span>
          {data.gaps.map((g) => <span key={g} className="rounded-full border border-amber-500/40 px-2 py-0.5 text-amber-200">{g}</span>)}
        </div>
      )}
      {data.unreadable_documents.length > 0 && (
        <p className="mt-2 text-[11px] text-slate-400">
          {mode === 'team'
            ? `No text could be read from: ${data.unreadable_documents.join(', ')}. Download and check them, then add what's needed as details.`
            : `We couldn't read text from ${data.unreadable_documents.join(', ')}; our team will check them.`}
        </p>
      )}
    </div>
  );
};

const DetailInput: React.FC<{
  field: DetailField;
  value: { value: string; in_documents: boolean };
  onChange: (patch: Partial<{ value: string; in_documents: boolean }>) => void;
}> = ({ field, value, onChange }) => {
  const filled = !!value.value.trim();
  const state = filled ? 'FILLED' : value.in_documents ? 'IN_DOCUMENTS' : 'MISSING';
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
        {state === 'MISSING' ? <Circle className="h-3.5 w-3.5 text-slate-600" /> : <CheckCircle2 className="h-3.5 w-3.5 text-[#00df8f]" />}
        {field.label}
        {field.required ? <span className="text-rose-400">*</span> : <span className="text-[10px] font-normal text-slate-500">(optional)</span>}
      </div>
      <input className={FIELD} placeholder={field.hint} value={value.value} onChange={(e) => onChange({ value: e.target.value })} />
      <label className={`flex items-center gap-1.5 text-[11px] ${filled ? 'text-slate-600' : 'text-slate-400'}`}>
        <input type="checkbox" className="accent-[#00df8f]" disabled={filled} checked={!filled && value.in_documents}
          onChange={(e) => onChange({ in_documents: e.target.checked })} />
        In my documents
      </label>
    </div>
  );
};

const DetailView: React.FC<{ field: DetailField }> = ({ field }) => (
  <div className="min-w-0">
    <dt className="flex items-center gap-1.5 font-medium text-slate-400">
      {field.state === 'MISSING' ? <Circle className="h-3.5 w-3.5 text-slate-600" /> : <CheckCircle2 className="h-3.5 w-3.5 text-[#00df8f]" />}
      {field.label}
      {!field.required && <span className="text-[10px] font-normal text-slate-500">(optional)</span>}
    </dt>
    <dd className="mt-0.5 pl-5">
      {field.state === 'FILLED' ? (
        <span className="whitespace-pre-line text-slate-200">{field.value}</span>
      ) : field.state === 'IN_DOCUMENTS' ? (
        <span className="text-sky-300">In the client's documents</span>
      ) : (
        <span className={field.required ? 'text-amber-300' : 'text-slate-600'}>{field.required ? 'Missing' : 'Not given'}</span>
      )}
    </dd>
  </div>
);

const StorageMeter: React.FC<{ used: number; quota: number }> = ({ used, quota }) => {
  const pct = Math.min(100, Math.round((used / Math.max(1, quota)) * 100));
  return (
    <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
      <div className="h-1 w-32 overflow-hidden rounded-full bg-[#0c2129]">
        <div className={`h-full ${pct > 85 ? 'bg-amber-400' : 'bg-[#00df8f]'}`} style={{ width: `${pct}%` }} />
      </div>
      {formatBytes(used)} of {formatBytes(quota)} used
    </div>
  );
};

export const DocumentCard: React.FC<{
  entry: KnowledgeSource;
  busy?: boolean;
  onDownload: (entry: KnowledgeSource) => void;
  onDelete: (entry: KnowledgeSource) => void;
  extra?: React.ReactNode;
}> = ({ entry, busy, onDownload, onDelete, extra }) => {
  const Icon = fileIcon(entry);
  const hasFile = !!entry.metadata?.file;
  return (
    <div className="flex flex-col rounded-lg border border-[#143c49] bg-[#071419] p-3">
      <div className="flex items-start gap-2.5">
        <Icon className="mt-0.5 h-5 w-5 shrink-0 text-[#00df8f]" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-200" title={entry.name}>{entry.name}</p>
          <p className="mt-0.5 text-[11px] text-slate-500">{documentLine(entry)}</p>
        </div>
        {extra}
      </div>
      <div className="mt-3 flex items-center justify-between">
        <TextStatus entry={entry} />
        <span className="flex gap-1">
          <IconButton label={hasFile ? `Download ${entry.name}` : 'Original file not kept (added before downloads)'} disabled={!hasFile} onClick={() => onDownload(entry)}>
            <Download className="h-3.5 w-3.5" />
          </IconButton>
          <IconButton label={`Delete ${entry.name}`} danger disabled={busy} onClick={() => onDelete(entry)}>
            <Trash2 className="h-3.5 w-3.5" />
          </IconButton>
        </span>
      </div>
    </div>
  );
};
