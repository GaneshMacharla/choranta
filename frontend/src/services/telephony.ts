import { request } from './api';

export interface PhoneNumber {
  id: string;
  client_id: string;
  client_name?: string;
  agent_id?: string;
  agent_name?: string;
  agent_version_id?: string;
  agent_version_number?: number;
  provider: string;
  provider_number_id?: string;
  phone_number: string;
  country_code: string;
  status: string;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface CreatePhoneNumberInput {
  phone_number: string;
  client_id: string;
  agent_id?: string;
  agent_version_id?: string;
  provider?: string;
  country_code?: string;
  status?: string;
}

export interface UpdatePhoneNumberInput {
  agent_id?: string;
  agent_version_id?: string;
  status?: string;
  metadata?: Record<string, any>;
}

export interface PhoneNumberReadiness {
  phone_number_id: string;
  phone_number: string;
  ready: boolean;
  errors: string[];
  warnings: string[];
  agent_id?: string;
  agent_version_id?: string;
}

/**
 * Call cost and client charge. Operators receive only the charge fields; admins also get
 * our cost (breakdown, total, per_minute), the profit and the rates.
 */
export interface CallCost {
  currency: 'INR';
  estimated: boolean;
  duration_seconds: number;
  billed_minutes: number;
  charge_total: number;
  charge_per_minute: number | null;
  breakdown?: { telephony: number; speech_to_text: number; text_to_speech: number; llm: number; infra: number };
  total?: number;
  per_minute?: number | null;
  profit_percent?: number;
  profit?: number;
  llm_provider?: string;
  rates?: {
    telephony_per_minute_inr: number;
    billing_pulse_seconds: number;
    stt_usd_per_minute: number;
    tts_usd_per_minute: number;
    llm_input_usd_per_million_tokens: number;
    llm_output_usd_per_million_tokens: number;
    usd_to_inr: number;
    infra_per_minute_inr: number;
  };
}

export interface Call {
  id: string;
  client_id: string;
  client_name?: string;
  agent_id: string;
  agent_name?: string;
  agent_version_id: string;
  agent_version_number?: number;
  phone_number_id?: string;
  runtime_session_id?: string;
  provider: string;
  provider_call_id: string;
  direction: string;
  caller_number: string;
  destination_number: string;
  status: string;
  started_at?: string;
  answered_at?: string;
  ended_at?: string;
  duration_seconds: number;
  termination_reason?: string;
  recording_url?: string;
  has_recording?: boolean;
  cost?: CallCost | null;
  transcript_summary?: string;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface CallDetail extends Call {
  events: Array<{
    id: string;
    event_type: string;
    timestamp: string;
    payload?: any;
  }>;
  usage: Record<string, any>;
  conversation: Array<{
    role: string;
    content: string;
    timestamp?: string;
  }>;
}

export interface TelephonyOverview {
  provider: string;
  provider_status: string;
  total_phone_numbers: number;
  active_phone_numbers: number;
  assigned_phone_numbers: number;
  total_calls_today: number;
  completed_calls_today: number;
  active_calls_now: number;
}

/** Call from a provisioned number (phone_number_id) or directly as an agent (agent_id + agent_version_id). */
export interface InitiateOutboundCallInput {
  phone_number_id?: string;
  agent_id?: string;
  agent_version_id?: string;
  caller_id?: string;
  destination_number: string;
  flow_id?: string;
  custom_field?: string;
}

export const telephonyService = {
  async getOverview(): Promise<TelephonyOverview> {
    return request<TelephonyOverview>('/telephony/overview');
  },

  async getPhoneNumbers(params?: { client_id?: string; status?: string }): Promise<PhoneNumber[]> {
    const q = new URLSearchParams();
    if (params?.client_id) q.set('client_id', params.client_id);
    if (params?.status) q.set('status', params.status);
    const qs = q.toString() ? `?${q.toString()}` : '';
    return request<PhoneNumber[]>(`/telephony/numbers${qs}`);
  },

  async createPhoneNumber(data: CreatePhoneNumberInput): Promise<PhoneNumber> {
    return request<PhoneNumber>('/telephony/numbers', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updatePhoneNumber(id: string, data: UpdatePhoneNumberInput): Promise<PhoneNumber> {
    return request<PhoneNumber>(`/telephony/numbers/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async deletePhoneNumber(id: string): Promise<void> {
    return request<void>(`/telephony/numbers/${id}`, {
      method: 'DELETE',
    });
  },

  async checkReadiness(id: string): Promise<PhoneNumberReadiness> {
    return request<PhoneNumberReadiness>(`/telephony/numbers/${id}/readiness`);
  },

  async getCalls(params?: {
    status?: string;
    direction?: string;
    client_id?: string;
    agent_id?: string;
    limit?: number;
    skip?: number;
  }): Promise<Call[]> {
    const q = new URLSearchParams();
    if (params?.status) q.set('status', params.status);
    if (params?.direction) q.set('direction', params.direction);
    if (params?.client_id) q.set('client_id', params.client_id);
    if (params?.agent_id) q.set('agent_id', params.agent_id);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.skip) q.set('skip', String(params.skip));
    const qs = q.toString() ? `?${q.toString()}` : '';
    return request<Call[]>(`/telephony/calls${qs}`);
  },

  async getCall(id: string): Promise<CallDetail> {
    return request<CallDetail>(`/telephony/calls/${id}`);
  },

  /** Fetches the call's stereo WAV recording with the user's auth token. */
  async getRecordingBlob(id: string): Promise<Blob> {
    const token = localStorage.getItem('choranta_token');
    const response = await fetch(`/api/telephony/calls/${id}/recording`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = (await response.json())?.detail || detail;
      } catch {
        // non-JSON error body
      }
      throw new Error(detail || 'Could not load the recording.');
    }
    return response.blob();
  },

  async initiateOutboundCall(data: InitiateOutboundCallInput): Promise<Call> {
    return request<Call>('/telephony/calls/outbound', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

