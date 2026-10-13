import { request } from './api';
import { KnowledgeSource, Tool, Integration, CartesiaVoice } from '../types';

export const catalogsService = {
  // Knowledge Sources
  listKnowledge: async (): Promise<KnowledgeSource[]> => {
    return request<KnowledgeSource[]>('/knowledge');
  },

  getAgentKnowledge: async (agentId: string): Promise<KnowledgeSource[]> => {
    return request<KnowledgeSource[]>(`/agents/${agentId}/knowledge`);
  },

  attachKnowledge: async (agentId: string, knowledgeId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/knowledge/${knowledgeId}`, {
      method: 'POST',
    });
  },

  detachKnowledge: async (agentId: string, knowledgeId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/knowledge/${knowledgeId}`, {
      method: 'DELETE',
    });
  },

  // Tools
  listTools: async (): Promise<Tool[]> => {
    return request<Tool[]>('/tools');
  },

  getAgentTools: async (agentId: string): Promise<Tool[]> => {
    return request<Tool[]>(`/agents/${agentId}/tools`);
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

  getAgentIntegrations: async (agentId: string): Promise<Integration[]> => {
    return request<Integration[]>(`/agents/${agentId}/integrations`);
  },

  attachIntegration: async (agentId: string, integrationId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/integrations/${integrationId}`, {
      method: 'POST',
    });
  },

  detachIntegration: async (agentId: string, integrationId: string): Promise<void> => {
    return request<void>(`/agents/${agentId}/integrations/${integrationId}`, {
      method: 'DELETE',
    });
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

  // Agent Templates
  listTemplates: async (): Promise<any[]> => {
    return request<any[]>('/catalogs/agent-templates');
  },

  getTemplate: async (templateId: string): Promise<any> => {
    return request<any>(`/catalogs/agent-templates/${templateId}`);
  },
};
