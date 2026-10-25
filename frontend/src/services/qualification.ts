import { request } from './api';

export type FieldType = 'boolean' | 'number' | 'string' | 'interest';

export interface QualificationField {
  name: string;
  label: string;
  data_type: FieldType;
}

export interface Condition {
  field: string;
  op: string;
  value?: string[] | string | number;
}

/** Any group whose conditions all hold qualifies the lead */
export type Rules = Condition[][];

export interface QualificationSetup {
  agent_id: string;
  agent_name: string;
  fields: QualificationField[];
  ops: Record<FieldType, string[]>;
  interest_values: Array<{ value: string; label: string }>;
  configured: boolean;
  rules: Rules;
  ai_criteria: string | null;
  suggested_rules: Rules;
}

export interface Qualification {
  status: 'qualified' | 'not_qualified' | 'unknown';
  reason: string | null;
  source: 'rules' | 'ai' | 'interest';
}

export const portalQualification = {
  list: () => request<QualificationSetup[]>('/portal/qualification'),
  save: (agentId: string, body: { rules: Rules; ai_criteria: string | null }) =>
    request<QualificationSetup>(`/portal/qualification/${agentId}`, { method: 'PUT', body: JSON.stringify(body) }),
  reevaluate: (agentId: string) =>
    request<{ changed: number; days: number }>(`/portal/qualification/${agentId}/reevaluate`, { method: 'POST' }),
};
