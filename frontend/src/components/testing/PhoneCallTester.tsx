import React, { useEffect, useRef, useState } from 'react';
import { PhoneCall, PhoneOutgoing, AlertTriangle, CheckCircle } from 'lucide-react';
import { Button } from '../common/Button';
import { telephonyService, CallDetail } from '../../services/telephony';
import { CallCostCard } from '../telephony/CallCostCard';

const STORAGE_KEY = 'choranta_test_phone_number';
const POLL_MS = 2000;
const TERMINAL_STATUSES = ['COMPLETED', 'FAILED', 'TERMINATED'];

const STATUS_LABELS: Record<string, string> = {
  INITIATED: 'Dialing your phone...',
  RINGING: 'Ringing...',
  ANSWERED: 'Answered, connecting the agent...',
  ACTIVE: 'Live: talk to the agent',
  COMPLETED: 'Call ended',
  FAILED: 'Call failed',
  TERMINATED: 'Call ended',
};

interface PhoneCallTesterProps {
  agentId: string;
  agentVersionId: string;
  ready: boolean;
}

/**
 * Places a real outbound phone call from the selected agent to the tester's own number
 * and follows the call live (status + transcript) by polling the call record.
 */
export const PhoneCallTester: React.FC<PhoneCallTesterProps> = ({ agentId, agentVersionId, ready }) => {
  const [phoneNumber, setPhoneNumber] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || '';
    } catch {
      return '';
    }
  });
  const [dialing, setDialing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [callId, setCallId] = useState<string | null>(null);
  const [call, setCall] = useState<CallDetail | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  const isLive = !!call && !TERMINAL_STATUSES.includes(call.status);

  // Follow the call until it ends
  useEffect(() => {
    if (!callId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const detail = await telephonyService.getCall(callId);
        if (cancelled) return;
        setCall(detail);
        if (TERMINAL_STATUSES.includes(detail.status)) return;
      } catch {
        // Transient errors: keep polling
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [callId]);

  useEffect(() => {
    if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [call?.conversation?.length]);

  const handleCall = async () => {
    const number = phoneNumber.trim();
    if (!number) return;
    try {
      localStorage.setItem(STORAGE_KEY, number);
    } catch {
      // Remembering the number is only a convenience
    }
    setDialing(true);
    setError(null);
    setCall(null);
    setCallId(null);
    try {
      const placed = await telephonyService.initiateOutboundCall({
        agent_id: agentId,
        agent_version_id: agentVersionId,
        destination_number: number,
      });
      setCallId(placed.id);
    } catch (err: any) {
      setError(err?.message || 'Could not place the call.');
    } finally {
      setDialing(false);
    }
  };

  const statusLabel = call ? STATUS_LABELS[call.status] || call.status : null;

  return (
    <div className="space-y-4 px-5 py-6 text-left">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex-1 text-xs text-slate-400">
          <span className="mb-1 block font-medium text-slate-300">Your phone number</span>
          <input
            type="tel"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && phoneNumber.trim() && ready && !dialing && !isLive) handleCall();
            }}
            placeholder="+919876543210 or 09876543210"
            disabled={dialing || isLive}
            className="w-full rounded-lg border border-[#26303c] bg-[#10131d] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-[#00df8f]"
          />
        </label>
        <Button
          type="button"
          variant="primary"
          className="min-w-[180px] rounded-full bg-emerald-600 text-white hover:bg-emerald-500 font-semibold shadow-md"
          onClick={handleCall}
          disabled={!phoneNumber.trim() || !ready || !agentId || !agentVersionId || isLive}
          isLoading={dialing}
        >
          <PhoneOutgoing className="mr-2 h-4 w-4" /> Call my phone
        </Button>
      </div>

      {!ready && (
        <p className="text-xs text-amber-400/90">Select an agent and a ready published version in Setup first.</p>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {call && (
        <div className="space-y-3 rounded-lg border border-[#1b1f2d] bg-[#080b10] p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm text-slate-200">
              {isLive ? (
                <PhoneCall className="h-4 w-4 animate-pulse text-emerald-400" />
              ) : call.status === 'FAILED' ? (
                <AlertTriangle className="h-4 w-4 text-rose-400" />
              ) : (
                <CheckCircle className="h-4 w-4 text-slate-400" />
              )}
              <span>{statusLabel}</span>
            </div>
            <span className="font-mono text-[11px] text-slate-500">
              {call.destination_number}
              {call.duration_seconds ? ` · ${Math.round(call.duration_seconds)}s` : ''}
            </span>
          </div>
          {call.status === 'FAILED' && call.termination_reason && (
            <p className="text-xs text-rose-300">Reason: {call.termination_reason}</p>
          )}
          <div ref={transcriptRef} className="max-h-64 space-y-2 overflow-y-auto">
            {call.conversation.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-500">
                {isLive ? 'The transcript will appear here once you start talking.' : 'No conversation was recorded.'}
              </p>
            ) : (
              call.conversation.map((turn, index) => (
                <div key={index} className={`flex ${turn.role === 'caller' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[80%] rounded-lg px-3 py-2 text-xs ${
                      turn.role === 'caller' ? 'bg-emerald-950/40 text-emerald-200' : 'bg-[#151824] text-slate-200'
                    }`}
                  >
                    {turn.content}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {call && !isLive && call.cost && <CallCostCard cost={call.cost} />}

      <p className="text-[11px] leading-relaxed text-slate-500">
        Exotel rings your phone from the configured ExoPhone; when you answer, the agent greets you. Exotel trial
        accounts can only call numbers verified in the Exotel dashboard.
      </p>
    </div>
  );
};
