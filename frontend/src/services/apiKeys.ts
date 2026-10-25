import { request } from './api';

export interface ApiKey {
  id: string;
  client_id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

export interface CreatedApiKey extends ApiKey {
  /** The full key: shown once, never retrievable again */
  key: string;
}

export interface IntegrationsInfo {
  leads_url: string;
  rate_limit_per_minute: number;
  trigger_campaigns: Array<{ id: string; name: string; status: string }>;
  active_keys: number;
}

export const portalApiKeys = {
  list: () => request<ApiKey[]>('/portal/api-keys'),
  create: (name: string) => request<CreatedApiKey>('/portal/api-keys', { method: 'POST', body: JSON.stringify({ name }) }),
  revoke: (id: string) => request<ApiKey>(`/portal/api-keys/${id}`, { method: 'DELETE' }),
  info: () => request<IntegrationsInfo>('/portal/integrations'),
};

export interface InstantSetup {
  leads_url: string;
  /** A published AI employee exists */
  has_agent: boolean;
  campaigns: Array<{ id: string; name: string; status: string }>;
  running: boolean;
  /** The key created for the client automatically; null if the server can't store one */
  key: { id: string; prefix: string; created_at: string; last_used_at?: string | null } | null;
}

export const portalInstantSetup = {
  get: () => request<InstantSetup>('/portal/instant-setup'),
  revealKey: () => request<{ key: string }>('/portal/instant-setup/key', { method: 'POST' }),
  regenerateKey: () => request<InstantSetup>('/portal/instant-setup/key/regenerate', { method: 'POST' }),
};
