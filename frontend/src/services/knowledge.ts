import { downloadAuthed } from './portal';
import { markUtc, request } from './api';
import { KnowledgeSource } from '../types';

export type DetailState = 'FILLED' | 'IN_DOCUMENTS' | 'MISSING';

export interface DetailField {
  key: string;
  label: string;
  hint: string;
  required: boolean;
  value: string;
  in_documents: boolean;
  state: DetailState;
}

export interface KnowledgeOverview {
  business_type?: string | null;
  fields: DetailField[];
  /** Required fields nobody has filled in or marked as covered by a document */
  gaps: string[];
  details_id: string | null;
  entries: KnowledgeSource[];
  storage: { used_bytes: number; quota_bytes: number; max_file_bytes: number };
}

export type NoteBody = { name: string; type: 'NOTES' | 'FAQ'; content: string };

/**
 * A client's knowledge base. The same endpoints serve the client portal (/portal/knowledge) and
 * Choranta's team on the client's page (/clients/{id}/knowledge).
 */
export const knowledgeApi = (base: string) => ({
  overview: () => request<KnowledgeOverview>(`${base}/overview`).then((o) => ({ ...o, entries: o.entries.map((e) => markUtc(e) as KnowledgeSource) })),

  saveDetails: (fields: Record<string, { value: string; in_documents: boolean }>) =>
    request<KnowledgeSource>(`${base}/details`, { method: 'PUT', body: JSON.stringify({ fields }) }),

  createNote: (body: NoteBody) => request<KnowledgeSource>(base, { method: 'POST', body: JSON.stringify(body) }),

  updateEntry: (id: string, body: NoteBody) => request<KnowledgeSource>(`${base}/${id}`, { method: 'PUT', body: JSON.stringify(body) }),

  deleteEntry: (id: string) => request<void>(`${base}/${id}`, { method: 'DELETE' }),

  /** Any number of files of any type (request() always sends JSON, so this uses fetch). */
  upload: async (files: File[]): Promise<KnowledgeSource[]> => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    const token = localStorage.getItem('choranta_token');
    const response = await fetch(`/api${base}/upload`, {
      method: 'POST',
      body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.error || data?.detail || response.statusText || 'Upload failed.');
    return (data as KnowledgeSource[]).map((e) => markUtc(e) as KnowledgeSource);
  },

  download: (entry: KnowledgeSource) => downloadAuthed(`${base}/${entry.id}/download`, entry.metadata?.file?.name || entry.name),
});

export const portalKnowledge = knowledgeApi('/portal/knowledge');
export const clientKnowledge = (clientId: string) => knowledgeApi(`/clients/${clientId}/knowledge`);

export const formatBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
