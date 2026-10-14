import { request } from './api';
import { fetchAuthedBlob } from './portal';

export type AgentRequestStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'CANCELLED';

export interface AgentRequest {
  id: string;
  client_id: string;
  client_name: string | null;
  client_code: string | null;
  name: string;
  company_name: string | null;
  business_type: string | null;
  business_type_label: string | null;
  voice_id: string | null;
  voice_name: string | null;
  notes: string | null;
  tasks: string[];
  task_labels: string[];
  languages: string[];
  language_labels: string[];
  status: AgentRequestStatus;
  agent_id: string | null;
  agent_name: string | null;
  admin_note: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface RequestOption {
  id: string;
  label: string;
}

export interface SarvamVoice {
  id: string;
  name: string;
  provider: 'sarvam';
  is_default: boolean;
}

export const REQUEST_STATUS_LABELS: Record<AgentRequestStatus, string> = {
  PENDING: 'Requested',
  IN_PROGRESS: 'Being set up',
  COMPLETED: 'Ready',
  REJECTED: 'Declined',
  CANCELLED: 'Cancelled',
};

export const REQUEST_STATUS_VARIANT: Record<AgentRequestStatus, 'yellow' | 'blue' | 'green' | 'red' | 'gray'> = {
  PENDING: 'yellow',
  IN_PROGRESS: 'blue',
  COMPLETED: 'green',
  REJECTED: 'red',
  CANCELLED: 'gray',
};

/** Client portal: request an AI employee (company name, type of business, AI employee name). */
export const portalAgentRequestsService = {
  voices: () => request<SarvamVoice[]>('/portal/voices'),
  preview: (voiceId: string) => fetchAuthedBlob(`/portal/voices/${encodeURIComponent(voiceId)}/preview`),
  list: () => request<{ can_request: boolean; requests: AgentRequest[] }>('/portal/agent-requests'),
  options: () =>
    request<{ business_types: RequestOption[]; languages: RequestOption[]; company_name: string; business_type: string }>(
      '/portal/agent-requests/options'
    ),
  create: (body: { company_name: string; business_type: string; name: string; languages: string[] }) =>
    request<AgentRequest>('/portal/agent-requests', { method: 'POST', body: JSON.stringify(body) }),
  cancel: (id: string) => request<AgentRequest>(`/portal/agent-requests/${id}`, { method: 'DELETE' }),
  me: () =>
    request<{ client_id: string; client_name: string; client_code: string | null; business_type: string | null; has_ai_employee: boolean }>('/portal/me'),
  updateCompanyName: (client_name: string) =>
    request<{ client_id: string; client_name: string; client_code: string | null; business_type: string | null; has_ai_employee: boolean }>('/portal/me', {
      method: 'PATCH',
      body: JSON.stringify({ client_name }),
    }),
};

/** Choranta admins: the queue of AI employees clients asked for. */
export const agentRequestsService = {
  list: (status?: string) => request<AgentRequest[]>(`/agent-requests${status ? `?status=${status}` : ''}`),
  get: (id: string) => request<AgentRequest>(`/agent-requests/${id}`),
  pendingCount: () => request<{ pending: number }>('/agent-requests/count'),
  preview: (voiceId: string) => fetchAuthedBlob(`/agent-requests/voices/${encodeURIComponent(voiceId)}/preview`),
  start: (id: string) => request<AgentRequest>(`/agent-requests/${id}/start`, { method: 'POST' }),
  complete: (id: string, agent_id: string) =>
    request<AgentRequest>(`/agent-requests/${id}/complete`, { method: 'POST', body: JSON.stringify({ agent_id }) }),
  reject: (id: string, note: string) =>
    request<AgentRequest>(`/agent-requests/${id}/reject`, { method: 'POST', body: JSON.stringify({ note }) }),
};
