import { request } from './api';
import { downloadAuthed } from './portal';

export type CampaignScope = 'admin' | 'portal';
export type CampaignKind = 'BULK' | 'TRIGGER';
export type CampaignStatus = 'DRAFT' | 'SCHEDULED' | 'RUNNING' | 'PAUSED' | 'STOPPING' | 'COMPLETED' | 'CANCELLED';
export type RecipientStatus = 'PENDING' | 'DIALING' | 'RETRY_WAIT' | 'COMPLETED' | 'FAILED' | 'SKIPPED';

export interface CallingWindow {
  start_min: number;
  end_min: number;
}

export interface CampaignStats {
  total: number;
  pending: number;
  dialing: number;
  retry_wait: number;
  completed: number;
  failed: number;
  skipped: number;
  answered: number;
  done: number;
  outcomes: Record<string, number>;
  answer_rate: number | null;
  attempts: number;
  minutes: number;
  /** {output variable: {value: count}} from answered calls */
  collected: Record<string, Record<string, number>>;
}

export interface CampaignSettings {
  name: string;
  purpose: 'SERVICE' | 'PROMOTIONAL';
  kind: CampaignKind;
  agent_id: string;
  agent_version_id: string;
  provider: string;
  caller_number_ids: string[];
  timezone?: string | null;
  windows: CallingWindow[];
  days: number[];
  start_at?: string | null;
  max_concurrent: number;
  retry_max: number;
  retry_intervals_min: number[];
  retry_on: string[];
  /** Optional results webhook (https); '' removes it */
  webhook_url?: string | null;
}

export interface Campaign extends CampaignSettings {
  id: string;
  client_id: string;
  client_name?: string | null;
  agent_name?: string | null;
  agent_version_number?: number | null;
  caller_numbers: string[];
  status: CampaignStatus;
  pause_reason?: string | null;
  timezone: string;
  launched_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
  stats: CampaignStats;
  webhook_secret?: string | null;
  /** Campaign details every call receives (e.g. course_name), keyed by the agent's input names */
  variables?: Record<string, string> | null;
}

/** An agent input typed once per campaign, e.g. the course and demo timings of a batch announcement */
export interface CampaignInput {
  name: string;
  description: string;
  required: boolean;
  example?: string;
}

export interface CampaignRecipient {
  id: string;
  phone: string;
  name?: string | null;
  variables: Record<string, string>;
  lead_id?: string | null;
  source?: string | null;
  status: RecipientStatus;
  attempts: number;
  next_attempt_at?: string | null;
  last_call_id?: string | null;
  last_dialed_at?: string | null;
  outcome?: string | null;
  result: {
    outputs?: Record<string, unknown>;
    actions?: Array<{ tool: string; arguments: Record<string, unknown> }>;
    lead?: { qualification_status?: string | null; call_disposition?: string | null; next_action?: string | null };
    summary?: string;
  };
  error?: string | null;
  updated_at: string;
}

export interface CampaignOptions {
  client_id: string;
  timezone: string;
  agents: Array<{
    id: string;
    name: string;
    versions: Array<{ id: string; version_number: number; created_at: string; campaign_inputs?: CampaignInput[] }>;
  }>;
  numbers: Array<{ id: string; phone_number: string; provider: string; usable: boolean; reason?: string | null }>;
  connections: Array<{ id: string; name: string }>;
  concurrency_cap: number | null;
  max_recipients: number;
}

export interface LeadOption {
  id: string;
  name: string;
  phone: string;
  lead_source?: string | null;
  status?: string | null;
  call_disposition?: string | null;
  created_at: string;
}

export interface CsvPreview {
  valid: number;
  invalid: Array<{ line: number | null; value: string; reason: string }>;
  invalid_count: number;
  duplicates: number;
  phone_column?: string | null;
  variable_names: string[];
  sample: Array<{ phone: string; name?: string | null; variables: Record<string, string> }>;
}

export interface RecipientImportResult {
  added: number;
  already_present: number;
  invalid: Array<{ line: number | null; value: string; reason: string }>;
  invalid_count: number;
  duplicates: number;
}

export interface DoNotCallEntry {
  id: string;
  client_id: string;
  phone: string;
  source: string;
  note?: string | null;
  created_at: string;
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

/** Campaign API for internal users (/campaigns) or client portal users (/portal/campaigns). */
export function campaignsApi(scope: CampaignScope) {
  const base = scope === 'portal' ? '/portal/campaigns' : '/campaigns';
  const clientQuery = (clientId?: string) => (scope === 'admin' && clientId ? `client_id=${encodeURIComponent(clientId)}` : '');

  return {
    scope,
    list: (params: { client_id?: string; status?: string; kind?: CampaignKind } = {}) => {
      const query = new URLSearchParams();
      if (scope === 'admin' && params.client_id) query.set('client_id', params.client_id);
      if (params.status) query.set('status', params.status);
      if (params.kind) query.set('kind', params.kind);
      const qs = query.toString();
      return request<Campaign[]>(`${base}${qs ? `?${qs}` : ''}`);
    },
    get: (id: string) => request<Campaign>(`${base}/${id}`),
    options: (clientId?: string) => request<CampaignOptions>(`${base}/options?${clientQuery(clientId)}`),
    leads: (params: { client_id?: string; search?: string; skip?: number; limit?: number }) => {
      const query = new URLSearchParams();
      if (scope === 'admin' && params.client_id) query.set('client_id', params.client_id);
      if (params.search) query.set('search', params.search);
      query.set('skip', String(params.skip ?? 0));
      query.set('limit', String(params.limit ?? 50));
      return request<{ total: number; items: LeadOption[] }>(`${base}/options/leads?${query.toString()}`);
    },
    previewCsv: (csvText: string) => request<CsvPreview>(`${base}/preview-csv`, json({ csv_text: csvText })),
    create: (settings: CampaignSettings & { client_id?: string }) => request<Campaign>(base, json(settings)),
    update: (id: string, settings: Partial<CampaignSettings>) =>
      request<Campaign>(`${base}/${id}`, { method: 'PATCH', body: JSON.stringify(settings) }),
    remove: (id: string) => request<void>(`${base}/${id}`, { method: 'DELETE' }),
    importCsv: (id: string, csvText: string) =>
      request<RecipientImportResult>(`${base}/${id}/recipients/csv`, json({ csv_text: csvText })),
    importLeads: (id: string, leadIds: string[]) =>
      request<RecipientImportResult>(`${base}/${id}/recipients/leads`, json({ lead_ids: leadIds })),
    recipients: (id: string, params: { status?: string; search?: string; skip?: number; limit?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.status) query.set('status', params.status);
      if (params.search) query.set('search', params.search);
      query.set('skip', String(params.skip ?? 0));
      query.set('limit', String(params.limit ?? 50));
      return request<{ items: CampaignRecipient[]; total: number }>(`${base}/${id}/recipients?${query.toString()}`);
    },
    launch: (id: string, consent: boolean) => request<Campaign>(`${base}/${id}/launch`, json({ consent })),
    action: (id: string, action: 'pause' | 'resume' | 'stop' | 'cancel' | 'webhook-secret') =>
      request<Campaign>(`${base}/${id}/${action}`, json({})),
    exportCsv: (campaign: Campaign) =>
      downloadAuthed(`${base}/${campaign.id}/export.csv`, `${campaign.name.replace(/[^\w-]+/g, '_')}-results.csv`),
    dncList: (clientId?: string) => request<DoNotCallEntry[]>(`${base}/dnc?${clientQuery(clientId)}`),
    dncAdd: (phone: string, note?: string, clientId?: string) =>
      request<DoNotCallEntry>(`${base}/dnc`, json({ phone, note, client_id: scope === 'admin' ? clientId : undefined })),
    dncRemove: (entryId: string) => request<void>(`${base}/dnc/${entryId}`, { method: 'DELETE' }),
  };
}

export type CampaignsApi = ReturnType<typeof campaignsApi>;

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export const minutesToTime = (m: number) =>
  `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

export const timeToMinutes = (t: string) => {
  const [h, m] = t.split(':').map((x) => parseInt(x, 10));
  return (h || 0) * 60 + (m || 0);
};

export const SAMPLE_CSV = 'name,phone,course_enquired\nPriya Reddy,9876543210,NEET 2027\nRahul Sharma,+919876543211,JEE Main\n';
