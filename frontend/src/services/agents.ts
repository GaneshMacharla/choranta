import { request } from './api';
import { Agent, AgentCreateInput, AgentDraftRequest, AgentDraftResponse, AgentUpdateInput, AgentVersion } from '../types';

export interface AgentListResponse {
  items: Agent[];
  total: number;
}

export const agentsService = {
  list: async (params?: { skip?: number; limit?: number; client_id?: string; status?: string; search?: string }): Promise<AgentListResponse> => {
    const query = new URLSearchParams();
    if (params?.skip !== undefined) query.set('skip', params.skip.toString());
    if (params?.limit !== undefined) query.set('limit', params.limit.toString());
    if (params?.client_id) query.set('client_id', params.client_id);
    if (params?.status) query.set('status', params.status);
    if (params?.search) query.set('search', params.search);

    const queryString = query.toString() ? `?${query.toString()}` : '';
    return request<AgentListResponse>(`/agents${queryString}`);
  },

  draftConfiguration: async (payload: AgentDraftRequest): Promise<AgentDraftResponse> => {
    return request<AgentDraftResponse>('/agents/draft-configuration', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  get: async (id: string): Promise<Agent> => {
    return request<Agent>(`/agents/${id}`);
  },

  create: async (payload: AgentCreateInput): Promise<Agent> => {
    return request<Agent>('/agents', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  update: async (id: string, payload: AgentUpdateInput): Promise<Agent> => {
    return request<Agent>(`/agents/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  getVersions: async (id: string): Promise<AgentVersion[]> => {
    return request<AgentVersion[]>(`/agents/${id}/versions`);
  },

  publishVersion: async (id: string): Promise<AgentVersion> => {
    return request<AgentVersion>(`/agents/${id}/versions`, {
      method: 'POST',
    });
  },

  delete: async (id: string): Promise<void> => {
    return request<void>(`/agents/${id}`, {
      method: 'DELETE',
    });
  },

  deleteAll: async (): Promise<{ message: string; count: number }> => {
    return request<{ message: string; count: number }>('/agents', {
      method: 'DELETE',
    });
  },
};
