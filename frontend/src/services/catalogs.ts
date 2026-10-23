import { fetchAuthedBlob } from './portal';
import { markUtc, request } from './api';
import { KnowledgeSource, Tool, Integration, CartesiaVoice } from '../types';

export const catalogsService = {
  // Each client's knowledge base (its AI employees answer from it)
  listClientKnowledge: (clientId: string) => request<KnowledgeSource[]>(`/clients/${clientId}/knowledge`),

  createClientKnowledge: (clientId: string, body: { name: string; type: 'NOTES' | 'FAQ'; content: string }) =>
    request<KnowledgeSource>(`/clients/${clientId}/knowledge`, { method: 'POST', body: JSON.stringify(body) }),

  updateClientKnowledge: (clientId: string, knowledgeId: string, body: { name: string; type: 'NOTES' | 'FAQ'; content: string }) =>
    request<KnowledgeSource>(`/clients/${clientId}/knowledge/${knowledgeId}`, { method: 'PUT', body: JSON.stringify(body) }),

  deleteClientKnowledge: (clientId: string, knowledgeId: string) =>
    request<void>(`/clients/${clientId}/knowledge/${knowledgeId}`, { method: 'DELETE' }),

  /** Uploads a PDF/TXT/MD/CSV whose text becomes a knowledge entry (request() always sends JSON, so this uses fetch). */
  uploadClientKnowledge: async (clientId: string, file: File, name?: string): Promise<KnowledgeSource> => {
    const form = new FormData();
    form.append('file', file);
    if (name) form.append('name', name);
    const token = localStorage.getItem('choranta_token');
    const response = await fetch(`/api/clients/${clientId}/knowledge/upload`, {
      method: 'POST',
      body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.error || data?.detail || response.statusText || 'Upload failed.');
    return markUtc(data) as KnowledgeSource;
  },

  getAgentKnowledge: async (agentId: string): Promise<KnowledgeSource[]> => {
    return request<KnowledgeSource[]>(`/agents/${agentId}/knowledge`);
  },

  attachKnowledge: async (agentId: string, knowledgeId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/knowledge/${knowledgeId}`, {
      method: 'POST',
    });
  },

  createAgentKnowledge: (agentId: string, body: { name: string; type: 'NOTES' | 'FAQ'; content: string }) =>
    request<KnowledgeSource>(`/agents/${agentId}/knowledge`, { method: 'POST', body: JSON.stringify(body) }),

  updateAgentKnowledge: (agentId: string, knowledgeId: string, body: { name: string; type: 'NOTES' | 'FAQ'; content: string }) =>
    request<KnowledgeSource>(`/agents/${agentId}/knowledge/${knowledgeId}`, { method: 'PUT', body: JSON.stringify(body) }),

  detachKnowledge: async (agentId: string, knowledgeId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/knowledge/${knowledgeId}`, {
      method: 'DELETE',
    });
  },

  // Tools
  listTools: async (): Promise<Tool[]> => {
    return request<Tool[]>('/tools');
  },

  attachTool: async (agentId: string, toolId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/tools/${toolId}`, {
      method: 'POST',
    });
  },

  detachTool: async (agentId: string, toolId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/tools/${toolId}`, {
      method: 'DELETE',
    });
  },

  // Integrations
  listIntegrations: async (): Promise<Integration[]> => {
    return request<Integration[]>('/integrations');
  },

  // Cartesia Voices Catalog
  listVoices: async (params?: { query?: string; gender?: string; language?: string }): Promise<CartesiaVoice[]> => {
    const queryParts: string[] = [];
    if (params?.query) queryParts.push(`query=${encodeURIComponent(params.query)}`);
    if (params?.gender) queryParts.push(`gender=${encodeURIComponent(params.gender)}`);
    if (params?.language) queryParts.push(`language=${encodeURIComponent(params.language)}`);
    const qs = queryParts.length ? `?${queryParts.join('&')}` : '';
    return request<CartesiaVoice[]>(`/catalogs/voices${qs}`);
  },

  getVoicePreviewUrl: (voiceId: string, token?: string | null): string => {
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    return `/api/catalogs/voices/${encodeURIComponent(voiceId)}/preview${tokenParam}`;
  },

  // Sarvam voices (the voices in use; the Cartesia catalog above is kept but not shown)
  listSarvamVoices: async (): Promise<CartesiaVoice[]> => {
    const voices = await request<Array<{ id: string; name: string; is_default: boolean }>>('/catalogs/sarvam-voices');
    return voices.map((v) => ({ ...v, provider: 'sarvam', language: null, description: 'Sarvam Bulbul v3 voice, made for Indian languages.' }));
  },

  /** Sarvam voice preview spoken in the agent's language (fetched with the user's token). */
  fetchSarvamPreview: (voiceId: string, language?: string | null): Promise<Blob> =>
    fetchAuthedBlob(
      `/catalogs/sarvam-voices/${encodeURIComponent(voiceId)}/preview${language ? `?language=${encodeURIComponent(language)}` : ''}`
    ),

  /** Cartesia voice preview spoken in the agent's language. */
  fetchCartesiaPreview: (voiceId: string, language?: string | null): Promise<Blob> =>
    fetchAuthedBlob(
      `/catalogs/voices/${encodeURIComponent(voiceId)}/preview${language ? `?language=${encodeURIComponent(language)}` : ''}`
    ),

  // Agent Templates
  listTemplates: async (): Promise<any[]> => {
    return request<any[]>('/catalogs/agent-templates');
  },
};
