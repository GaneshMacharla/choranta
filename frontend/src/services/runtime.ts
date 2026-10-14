import { ApiError, request } from './api';
import {
  ReadinessCheckResult,
  RuntimeSession,
  RuntimeEvent,
  SimulateTurnResult,
  StreamTurnEvent,
} from '../types';

export type MockCallOutcome = 'completed' | 'no-answer' | 'busy' | 'failed';

export const runtimeService = {
  /** How many test or live conversations an AI employee has had. */
  sessionCount: (agentId: string) => request<{ sessions: number }>(`/runtime/agents/${agentId}/session-count`),

  simulateMockCall: async (
    agentId: string,
    agentVersionId: string,
    utterances: string[]
  ): Promise<{ label: string; call_id: string; session_id: string; status: string; event_count: number; usage: Record<string, any>; billing_excluded: boolean }> => {
    return request(`/mock/calls/simulate`, {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        agent_version_id: agentVersionId,
        utterances,
      }),
    });
  },

  completePendingMockCalls: async (body: {
    status: MockCallOutcome;
    duration_seconds?: number;
    campaign_id?: string;
    call_ids?: string[];
  }): Promise<{ label: string; status: string; updated: number; call_ids: string[] }> => {
    return request(`/mock/calls/complete-pending`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  checkReadiness: async (
    agentId: string,
    versionId: string
  ): Promise<ReadinessCheckResult> => {
    return request<ReadinessCheckResult>('/runtime/readiness', {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        agent_version_id: versionId,
      }),
    });
  },

  startSession: async (
    agentId: string,
    versionId: string,
    metadata?: Record<string, any>
  ): Promise<RuntimeSession> => {
    return request<RuntimeSession>('/runtime/sessions', {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        agent_version_id: versionId,
        metadata: metadata || {},
      }),
    });
  },

  getSession: async (sessionId: string): Promise<RuntimeSession> => {
    return request<RuntimeSession>(`/runtime/sessions/${sessionId}`);
  },

  endSession: async (sessionId: string): Promise<RuntimeSession> => {
    return request<RuntimeSession>(`/runtime/sessions/${sessionId}/end`, {
      method: 'POST',
    });
  },

  simulateTurn: async (
    sessionId: string,
    inputText: string,
    options: { synthesizeAudio?: boolean } = {}
  ): Promise<SimulateTurnResult> => {
    return request<SimulateTurnResult>(`/runtime/sessions/${sessionId}/simulate_turn`, {
      method: 'POST',
      body: JSON.stringify({
        input_text: inputText,
        synthesize_audio: options.synthesizeAudio ?? true,
      }),
    });
  },

  /**
   * Streams a chat turn over Server-Sent Events, calling onEvent for each
   * delta / tool / done / error event as it arrives.
   */
  streamTurn: async (
    sessionId: string,
    inputText: string,
    onEvent: (event: StreamTurnEvent) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const token = localStorage.getItem('choranta_token');
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`/api/runtime/sessions/${sessionId}/stream_turn`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ input_text: inputText }),
      signal,
    });

    if (!response.ok || !response.body) {
      let data: any = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      if (response.status === 401) {
        localStorage.removeItem('choranta_token');
        localStorage.removeItem('choranta_user');
        if (window.location.pathname !== '/login') window.location.href = '/login';
      }
      throw new ApiError(data?.error || data?.detail || response.statusText || 'Request failed', response.status, data?.details);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of frame.split('\n')) {
          if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)) as StreamTurnEvent);
        }
        boundary = buffer.indexOf('\n\n');
      }
    }
  },

  getEvents: async (sessionId: string): Promise<RuntimeEvent[]> => {
    return request<RuntimeEvent[]>(`/runtime/sessions/${sessionId}/events`);
  },
};
