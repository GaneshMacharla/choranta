import { request } from './api';

export interface WhatsAppAccount {
  connected: boolean;
  status?: 'ACTIVE' | 'INVALID';
  status_detail?: string | null;
  waba_id?: string;
  phone_number_id?: string;
  display_phone?: string | null;
  verified_name?: string | null;
  has_app_secret?: boolean;
}

export type TemplateStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'ERROR' | null;

export interface WhatsAppFollowup {
  agent_id: string;
  agent_name: string;
  placeholders: Array<{ key: string; label: string }>;
  languages: Array<{ code: string; label: string }>;
  configured: boolean;
  enabled: boolean;
  message: string;
  language: string;
  send_when: string[];
  button_text: string | null;
  button_url: string | null;
  template_status: TemplateStatus;
  template_detail: string | null;
  /** An approved version is being sent (maybe an earlier one while the latest is reviewed) */
  sending_version: boolean;
  sending_latest?: boolean;
}

export interface WhatsAppOverview {
  account: WhatsAppAccount;
  webhook_url: string;
  verify_token: string;
  followups: WhatsAppFollowup[];
}

export interface FollowupInput {
  enabled: boolean;
  message: string;
  language: string;
  send_when: string[];
  button_text: string | null;
  button_url: string | null;
}

export interface WhatsAppMessage {
  id: string;
  direction: 'OUT' | 'IN';
  phone: string;
  body: string | null;
  status: string;
  error: string | null;
  sent_at: string | null;
  created_at: string;
}

export const portalWhatsApp = {
  overview: () => request<WhatsAppOverview>('/portal/whatsapp'),
  connect: (body: { waba_id: string; phone_number_id: string; access_token: string; app_secret?: string }) =>
    request<WhatsAppOverview>('/portal/whatsapp/account', { method: 'PUT', body: JSON.stringify(body) }),
  disconnect: () => request<WhatsAppOverview>('/portal/whatsapp/account', { method: 'DELETE' }),
  saveFollowup: (agentId: string, body: FollowupInput) =>
    request<WhatsAppFollowup>(`/portal/whatsapp/followups/${agentId}`, { method: 'PUT', body: JSON.stringify(body) }),
  callThread: (callId: string) => request<WhatsAppMessage[]>(`/portal/whatsapp/calls/${callId}`),
  callSummaries: (callIds: string[]) =>
    request<Record<string, { status: string; replies: number }>>(`/portal/whatsapp/calls?ids=${callIds.join(',')}`),
};
