import React, { useState, useEffect } from 'react';
import {
  PhoneCall,
  PhoneIncoming,
  RefreshCw,
  Volume2,
  FileText,
  Activity,
} from 'lucide-react';
import { telephonyService, Call, CallDetail } from '../services/telephony';
import { clientsService } from '../services/clients';
import { agentsService } from '../services/agents';
import { Client, Agent } from '../types';
import { Card } from '../components/common/Card';
import { Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { Modal } from '../components/common/Modal';
import { Select } from '../components/common/Select';
import { LoadingState } from '../components/common/LoadingState';
import { EmptyState } from '../components/common/EmptyState';
import { ErrorState } from '../components/common/ErrorState';
import { CallRecordingPlayer } from '../components/telephony/CallRecordingPlayer';

export const CallsPage: React.FC = () => {
  const [calls, setCalls] = useState<Call[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [clientFilter, setClientFilter] = useState('');
  const [agentFilter, setAgentFilter] = useState('');

  // Selected call detail modal
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [callDetail, setCallDetail] = useState<CallDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchCalls = async () => {
    try {
      setLoading(true);
      setError(null);
      const [callsData, clientsRes, agentsRes] = await Promise.all([
        telephonyService.getCalls({
          status: statusFilter || undefined,
          client_id: clientFilter || undefined,
          agent_id: agentFilter || undefined,
          limit: 100,
        }),
        clientsService.list({ limit: 100 }).catch(() => ({ items: [], total: 0 })),
        agentsService.list({ limit: 100 }).catch(() => ({ items: [], total: 0 })),
      ]);

      setCalls(callsData);
      setClients(clientsRes.items || []);
      setAgents(agentsRes.items || []);
    } catch (err: any) {
      setError(err?.message || 'Failed to load calls history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCalls();
  }, [statusFilter, clientFilter, agentFilter]);

  const handleOpenDetail = async (id: string) => {
    setSelectedCallId(id);
    try {
      setDetailLoading(true);
      const detail = await telephonyService.getCall(id);
      setCallDetail(detail);
    } catch (err: any) {
      alert(err?.message || 'Failed to load call detail');
      setSelectedCallId(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const formatDuration = (seconds: number) => {
    if (!seconds || seconds <= 0) return '0s';
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    if (m === 0) return `${s}s`;
    return `${m}m ${s}s`;
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'ACTIVE':
        return (
          <Badge variant="blue" size="sm" dot>
            Active Now
          </Badge>
        );
      case 'RINGING':
        return (
          <Badge variant="yellow" size="sm" dot>
            Ringing
          </Badge>
        );
      case 'ANSWERED':
        return (
          <Badge variant="blue" size="sm">
            Answered
          </Badge>
        );
      case 'COMPLETED':
        return (
          <Badge variant="green" size="sm">
            Completed
          </Badge>
        );
      case 'FAILED':
      case 'REJECTED':
        return (
          <Badge variant="red" size="sm">
            Failed
          </Badge>
        );
      default:
        return (
          <Badge variant="gray" size="sm">
            {status}
          </Badge>
        );
    }
  };

  if (loading && calls.length === 0) {
    return <LoadingState message="Loading phone calls history..." />;
  }

  if (error && calls.length === 0) {
    return <ErrorState message={error} onRetry={fetchCalls} />;
  }

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <PhoneCall className="h-6 w-6 text-[#00df8f]" />
            <h1 className="text-2xl font-semibold text-slate-100">Calls History & Transcripts</h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Real-time audit log of all inbound phone calls, full transcripts, and latency telemetry.
          </p>
        </div>
        <Button variant="secondary" onClick={fetchCalls} className="gap-2 self-start sm:self-auto">
          <RefreshCw className="h-4 w-4" />
          Refresh Calls
        </Button>
      </div>

      {/* Filter Bar */}
      <Card className="p-4 bg-[#111420] border-[#1d2232]">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Select
            label="Call Status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            options={[
              { value: '', label: 'All Statuses' },
              { value: 'ACTIVE', label: 'Active (Live)' },
              { value: 'RINGING', label: 'Ringing' },
              { value: 'COMPLETED', label: 'Completed' },
              { value: 'FAILED', label: 'Failed / Rejected' },
            ]}
          />

          <Select
            label="Client"
            value={clientFilter}
            onChange={(e) => setClientFilter(e.target.value)}
            options={[
              { value: '', label: 'All Clients' },
              ...clients.map((c) => ({ value: c.id, label: c.name })),
            ]}
          />

          <Select
            label="AI Employee"
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            options={[
              { value: '', label: 'All AI Employees' },
              ...agents.map((a) => ({ value: a.id, label: a.name })),
            ]}
          />
        </div>
      </Card>

      {/* Calls Table */}
      <Card className="bg-[#0f121d] border-[#1b1f2e] overflow-hidden">
        <div className="p-4 border-b border-[#1b1f2e] flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Inbound Calls</h2>
          <span className="text-xs text-slate-500">{calls.length} records</span>
        </div>

        {calls.length === 0 ? (
          <EmptyState
            icon={<PhoneIncoming className="h-6 w-6 text-slate-400" />}
            title="No Calls Found"
            description="Inbound PSTN calls arriving on provisioned Exotel phone numbers will appear here in real-time."
          />
        ) : (
          <div className="w-full overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="border-b border-[#1f2433] bg-[#0c0d14] text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-5 py-3 font-medium">Date / Time</th>
                  <th className="px-5 py-3 font-medium">Caller</th>
                  <th className="px-5 py-3 font-medium">Destination</th>
                  <th className="px-5 py-3 font-medium">Client & AI Employee</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Duration</th>
                  <th className="px-5 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1b1f2b]">
                {calls.map((call) => (
                  <tr key={call.id} className="hover:bg-[#141826] transition-colors">
                    <td className="px-5 py-3.5 text-xs text-slate-400 whitespace-nowrap">
                      {new Date(call.created_at).toLocaleString()}
                    </td>
                    <td className="px-5 py-3.5 font-mono text-xs text-slate-200">
                      {call.caller_number}
                    </td>
                    <td className="px-5 py-3.5 font-mono text-xs text-slate-400">
                      {call.destination_number}
                    </td>
                    <td className="px-5 py-3.5">
                      <div>
                        <span className="text-xs font-medium text-slate-200 block">
                          {call.agent_name || 'Agent'}
                        </span>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-[11px] text-slate-500">{call.client_name || 'Client'}</span>
                          {call.agent_version_number && (
                            <Badge variant="blue" size="sm">
                              v{call.agent_version_number}
                            </Badge>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">{getStatusBadge(call.status)}</td>
                    <td className="px-5 py-3.5 text-xs text-slate-300 font-mono">
                      {formatDuration(call.duration_seconds)}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleOpenDetail(call.id)}
                        className="text-xs text-[#00df8f] hover:text-[#00f59b]"
                      >
                        Inspect Call
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Call Detail Modal */}
      <Modal
        isOpen={Boolean(selectedCallId)}
        onClose={() => {
          setSelectedCallId(null);
          setCallDetail(null);
        }}
        title={`Call Details: ${callDetail?.provider_call_id || selectedCallId || ''}`}
        maxWidth="2xl"
      >
        {detailLoading || !callDetail ? (
          <div className="py-8">
            <LoadingState message="Fetching call recording and transcript..." />
          </div>
        ) : (
          <div className="space-y-6 max-h-[75vh] overflow-y-auto pr-1">
            {/* Call Meta Summary */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-[#0d101a] p-3 rounded border border-[#1b2030] text-xs">
              <div>
                <span className="text-slate-500 block">Status</span>
                <span className="font-medium text-slate-200">{callDetail.status}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Duration</span>
                <span className="font-medium text-slate-200 font-mono">
                  {formatDuration(callDetail.duration_seconds)}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Caller</span>
                <span className="font-medium text-slate-200 font-mono">{callDetail.caller_number}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Reason</span>
                <span className="font-medium text-slate-200 capitalize">
                  {callDetail.termination_reason || 'Normal'}
                </span>
              </div>
            </div>

            {/* Choranta's own stereo recording of both sides of the call */}
            {callDetail.has_recording && <CallRecordingPlayer callId={callDetail.id} />}

            {/* Carrier recording (if the carrier provided a playable link) */}
            {!callDetail.has_recording && callDetail.recording_url && (
              <div className="p-3 bg-[#052b20]/25 border border-[#0a4d39]/50 rounded space-y-2">
                <span className="text-xs font-semibold text-[#00df8f] flex items-center gap-1.5">
                  <Volume2 className="h-4 w-4" />
                  Exotel PSTN Recording
                </span>
                <audio controls src={callDetail.recording_url} className="w-full h-8" />
              </div>
            )}

            {/* Conversation Transcript */}
            <div className="space-y-3">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-[#00df8f]" />
                Live Conversation Dialogue
              </h3>

              {callDetail.conversation && callDetail.conversation.length > 0 ? (
                <div className="space-y-2.5 bg-[#06141a] p-4 rounded border border-[#143c49] max-h-64 overflow-y-auto">
                  {callDetail.conversation.map((msg, i) => {
                    const isAssistant = msg.role === 'assistant';
                    return (
                      <div
                        key={i}
                        className={`flex flex-col ${isAssistant ? 'items-start' : 'items-end'}`}
                      >
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
                          {isAssistant ? callDetail.agent_name || 'AI Assistant' : 'Caller'}
                        </span>
                        <div
                          className={`p-3 rounded-lg text-xs max-w-[85%] leading-relaxed ${
                            isAssistant
                              ? 'bg-[#0c222b] text-slate-200 border border-[#163e4c]'
                              : 'bg-[#00df8f]/15 text-slate-100 border border-[#00df8f]/30'
                          }`}
                        >
                          {msg.content || (msg as any).text}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : callDetail.transcript_summary ? (
                <div className="bg-[#090b12] p-4 rounded border border-[#171b29] text-xs text-slate-300 leading-relaxed">
                  {callDetail.transcript_summary}
                </div>
              ) : (
                <div className="p-4 bg-[#090b12] rounded border border-[#171b29] text-xs text-slate-500 text-center">
                  No transcript recorded for this turn.
                </div>
              )}
            </div>

            {/* Turn Latency & Telemetry */}
            {callDetail.usage && (
              <div className="p-3 bg-[#0d101a] rounded border border-[#1b2030] text-xs space-y-2">
                <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                  <Activity className="h-3.5 w-3.5 text-emerald-400" />
                  Voice Pipeline Latency & Usage
                </span>
                <div className="grid grid-cols-3 gap-2 font-mono text-[11px]">
                  <div className="bg-black/30 p-2 rounded">
                    <span className="text-slate-500 block">Audio Input</span>
                    <span className="text-slate-200">
                      {Math.round(callDetail.usage.stt_audio_seconds || 0)}s
                    </span>
                  </div>
                  <div className="bg-black/30 p-2 rounded">
                    <span className="text-slate-500 block">LLM Tokens</span>
                    <span className="text-slate-200">
                      {(callDetail.usage.llm_input_tokens || 0) +
                        (callDetail.usage.llm_output_tokens || 0)}
                    </span>
                  </div>
                  <div className="bg-black/30 p-2 rounded">
                    <span className="text-slate-500 block">TTS Output</span>
                    <span className="text-slate-200">
                      {Math.round(callDetail.usage.tts_audio_seconds || 0)}s
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Close Button */}
            <div className="flex justify-end pt-3 border-t border-[#1b2030]">
              <Button
                variant="secondary"
                onClick={() => {
                  setSelectedCallId(null);
                  setCallDetail(null);
                }}
              >
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
