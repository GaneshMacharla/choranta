import { request } from './api';
import { Client, ClientCreateInput, ClientUpdateInput } from '../types';

export interface ClientListResponse {
  items: Client[];
  total: number;
}

export const clientsService = {
  list: async (params?: { skip?: number; limit?: number; status?: string; business_type?: string; search?: string }): Promise<ClientListResponse> => {
    const query = new URLSearchParams();
    if (params?.skip !== undefined) query.set('skip', params.skip.toString());
    if (params?.limit !== undefined) query.set('limit', params.limit.toString());
    if (params?.status) query.set('status', params.status);
    if (params?.business_type) query.set('business_type', params.business_type);
    if (params?.search) query.set('search', params.search);

    const queryString = query.toString() ? `?${query.toString()}` : '';
    return request<ClientListResponse>(`/clients${queryString}`);
  },

  get: async (id: string): Promise<Client> => {
    return request<Client>(`/clients/${id}`);
  },

  create: async (payload: ClientCreateInput): Promise<Client> => {
    return request<Client>('/clients', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  update: async (id: string, payload: ClientUpdateInput): Promise<Client> => {
    return request<Client>(`/clients/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
};
