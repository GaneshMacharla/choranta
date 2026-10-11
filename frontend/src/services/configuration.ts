import { request } from './api';
import {
  AgentConfigurationData,
  ValidationResult,
  AgentVersion,
  VersionComparison,
} from '../types';

export interface AgentConfigurationResponse {
  agent_id: string;
  configuration: AgentConfigurationData;
  updated_at: string;
  status: string;
}

export const configurationService = {
  getConfiguration: async (agentId: string): Promise<AgentConfigurationResponse> => {
    return request<AgentConfigurationResponse>(`/agents/${agentId}/configuration`);
  },

  updateConfiguration: async (
    agentId: string,
    configuration: AgentConfigurationData
  ): Promise<AgentConfigurationResponse> => {
    return request<AgentConfigurationResponse>(`/agents/${agentId}/configuration`, {
      method: 'PUT',
      body: JSON.stringify(configuration),
    });
  },

  validateConfiguration: async (agentId: string): Promise<ValidationResult> => {
    return request<ValidationResult>(`/agents/${agentId}/configuration/validate`, {
      method: 'POST',
    });
  },

  createVersion: async (agentId: string): Promise<AgentVersion> => {
    return request<AgentVersion>(`/agents/${agentId}/versions`, {
      method: 'POST',
    });
  },

  getVersionDetail: async (agentId: string, versionId: string): Promise<AgentVersion> => {
    return request<AgentVersion>(`/agents/${agentId}/versions/${versionId}`);
  },

  compareVersions: async (
    agentId: string,
    baseVersion: number,
    compareVersion: number
  ): Promise<VersionComparison> => {
    return request<VersionComparison>(
      `/agents/${agentId}/versions/compare?base_version=${baseVersion}&compare_version=${compareVersion}`
    );
  },

  restoreVersion: async (
    agentId: string,
    versionId: string
  ): Promise<{ agent_id: string; restored_from_version: number; message: string }> => {
    return request<{ agent_id: string; restored_from_version: number; message: string }>(
      `/agents/${agentId}/versions/${versionId}/restore`,
      {
        method: 'POST',
      }
    );
  },
};
