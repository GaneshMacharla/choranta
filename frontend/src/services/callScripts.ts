import { request } from './api';

/** An admin-maintained call script shared by the AI employees linked to it (one per template). */
export interface StandardCallScript {
  key: string;
  name: string;
  discovery_questions: string[];
  offer_points: string[];
  next_step: string;
  updated_at?: string | null;
}

export const callScriptsService = {
  async list(): Promise<StandardCallScript[]> {
    return request<StandardCallScript[]>('/call-scripts');
  },

  /** Admins only. Linked employees use the new script from their next publish. */
  async update(
    key: string,
    data: Pick<StandardCallScript, 'discovery_questions' | 'offer_points' | 'next_step'>
  ): Promise<StandardCallScript> {
    return request<StandardCallScript>(`/call-scripts/${key}`, { method: 'PUT', body: JSON.stringify(data) });
  },
};
