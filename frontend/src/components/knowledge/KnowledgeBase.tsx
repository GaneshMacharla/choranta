import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle, Download, File as FileIcon, FileSpreadsheet, FileText, HelpCircle, Image as ImageIcon, StickyNote, Trash2,
  UploadCloud,
} from 'lucide-react';
import { Card } from '../common/Card';
import { KnowledgeSource } from '../../types';
import { KnowledgeOverview, formatBytes, knowledgeApi } from '../../services/knowledge';

type Api = ReturnType<typeof knowledgeApi>;

export const fileIcon = (entry: KnowledgeSource) => {
  const name = (entry.metadata?.file?.name || entry.name || '').toLowerCase();
  if (/\.(png|jpe?g|gif|webp|heic|bmp)$/.test(name)) return ImageIcon;
  if (/\.(xlsx?|xlsm|csv|tsv)$/.test(name)) return FileSpreadsheet;
  if (/\.(pdf|docx?|txt|md|rtf)$/.test(name)) return FileText;
  return FileIcon;
};

/** One line under a document's name: size, when and who added it. */
export const documentLine = (entry: KnowledgeSource) => {
  const parts: string[] = [];
  if (entry.metadata?.file?.size_bytes) parts.push(formatBytes(entry.metadata.file.size_bytes));
  parts.push(new Date(entry.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }));
  if (entry.metadata?.added_by?.role) parts.push(entry.metadata.added_by.role === 'CLIENT' ? 'from the client' : 'by Choranta');
  return parts.join(' · ');
};

/**
 * A client's knowledge base: the documents the client uploads in the portal ("client"), stored as they are. Choranta's
 * team ("team") downloads and reads them while building the client's AI employees; no AI employee reads them. Notes
 * written before uploads became the only way in are still listed so they can be deleted.
 */
export const KnowledgeBase: React.FC<{ api: Api; mode: 'client' | 'team' }> = ({ api, mode }) => {
  const [data, setData] = useState<KnowledgeOverview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      setData(await api.overview());
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
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  const upload = (list: FileList | null) => {
    const files = Array.from(list || []);
    if (fileInput.current) fileInput.current.value = '';
    if (!files.length || !data) return;
    const tooBig = files.find((f) => f.size > data.storage.max_file_bytes);
    if (tooBig) return setError(`${tooBig.name} is over ${formatBytes(data.storage.max_file_bytes)}.`);
    run('upload', () => api.upload(files), `${files.length} ${files.length === 1 ? 'document' : 'documents'} uploaded.`);
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
  const team = mode === 'team';

  return (
    <div className="space-y-4">
      {error && <ErrorBox text={error} />}
      {notice && <p className="rounded border border-[#00df8f]/30 bg-[#00df8f]/10 p-2 text-xs text-[#00df8f]">{notice}</p>}

      <Card
        title={`Documents (${documents.length})`}
        subtitle={team ? 'Files the client uploaded. Download and read them to write each AI employee\'s knowledge.'
          : 'Brochures, price lists, fee charts, prospectus: any document about your business, as many as you like. Only our team reads them.'}
      >
        {team ? (
          documents.length === 0 && <p className="text-xs text-slate-500">The client hasn't uploaded any documents yet.</p>
        ) : (<>
        <input ref={fileInput} type="file" multiple accept=".pdf,.doc,.docx,.txt,.md,.rtf" className="hidden"
          onChange={(e) => upload(e.target.files)} />
        <button
          type="button"
          disabled={!!busy}
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files); }}
          className={`flex w-full flex-col items-center gap-1.5 rounded-lg border border-dashed p-8 text-center transition-colors ${
            dragging ? 'border-[#00df8f] bg-[#00df8f]/10' : 'border-[#1b3a46] hover:border-[#00df8f]/60'
          }`}
        >
          <UploadCloud className="h-8 w-8 text-[#00df8f]" />
          <span className="text-sm font-medium text-slate-200">{busy === 'upload' ? 'Uploading...' : 'Drop documents here or click to choose'}</span>
          <span className="text-[11px] text-slate-500">PDF, Word or text files, up to {formatBytes(data.storage.max_file_bytes)} each.</span>
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

      {notes.length > 0 && (
        <Card title={`Earlier notes (${notes.length})`} subtitle="Written before documents became the way to add knowledge.">
          <ul className="divide-y divide-[#102d38] rounded-lg border border-[#102d38] text-xs">
            {notes.map((n) => (
              <li key={n.id} className="flex items-start justify-between gap-3 p-3">
                <span className="flex min-w-0 gap-2.5">
                  {n.type === 'FAQ' ? <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" /> : <StickyNote className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />}
                  <span className="min-w-0">
                    <span className="block truncate font-semibold text-slate-200">{n.name}</span>
                    <span className="mt-1 line-clamp-2 block whitespace-pre-line text-slate-400">{n.content}</span>
                  </span>
                </span>
                <IconButton label={`Delete ${n.name}`} danger disabled={busy === `delete:${n.id}`} onClick={() => remove(n)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </IconButton>
              </li>
            ))}
          </ul>
        </Card>
      )}
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
      <div className="mt-3 flex items-center justify-end">
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
