import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle, Mic, MicOff, PhoneCall, PhoneOff, Volume2, Wrench } from 'lucide-react';
import { Button } from '../common/Button';
import { telephonyService, CallDetail, BrowserCallAnswer } from '../../services/telephony';
import { CallRecordingPlayer } from '../telephony/CallRecordingPlayer';

type CallState = 'idle' | 'connecting' | 'live' | 'ended';

interface TranscriptLine {
  id: number;
  role: 'caller' | 'assistant';
  text: string;
  interrupted?: boolean;
}

const END_REASONS: Record<string, string> = {
  caller_hangup: 'You ended the call',
  agent_ended: 'The AI employee ended the call',
  caller_silent: 'Ended after the caller stayed silent',
  max_duration: 'Reached the maximum call length',
  connection_failed: 'The audio connection failed',
  connection_timeout: 'The audio connection never started',
};

interface BrowserCallTesterProps {
  agentId?: string;
  agentVersionId?: string;
  ready: boolean;
  userName?: string;
  companyName?: string;
  /** Starts the call some other way (e.g. a client's trial); defaults to the staff browser-call API */
  onStart?: (offer: { sdp: string; type: string }) => Promise<BrowserCallAnswer>;
  onHangUp?: (callId: string) => Promise<unknown>;
  /** For clients: a single call, without staff details (reply times, tools, call log, recording) */
  clientMode?: boolean;
  clientIntro?: string;
  onEnded?: () => void;
}

/**
 * Free test call from the browser over WebRTC. The call runs the same pipeline as a phone call
 * (turn-taking, streamed replies, fillers, barge-in, call limits, recording) and is logged as a test call.
 */
export const BrowserCallTester: React.FC<BrowserCallTesterProps> = ({
  agentId,
  agentVersionId,
  ready,
  userName,
  companyName,
  onStart,
  onHangUp,
  clientMode = false,
  clientIntro,
  onEnded,
}) => {
  const [state, setState] = useState<CallState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [callId, setCallId] = useState<string | null>(null);
  const [lines, setLines] = useState<TranscriptLine[]>([]);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [toolName, setToolName] = useState<string | null>(null);
  const [latencies, setLatencies] = useState<number[]>([]);
  const [muted, setMuted] = useState(false);
  const [endReason, setEndReason] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [summary, setSummary] = useState<CallDetail | null>(null);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const callIdRef = useRef<string | null>(null);
  const lineIdRef = useRef(0);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  // Latest hang-up handler, also for the unmount cleanup
  const hangUpRef = useRef<(callId: string) => Promise<unknown>>(onHangUp ?? telephonyService.hangUpBrowserCall);
  hangUpRef.current = onHangUp ?? telephonyService.hangUpBrowserCall;
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;

  const addLine = (line: Omit<TranscriptLine, 'id'>) =>
    setLines((prev) => [...prev, { ...line, id: ++lineIdRef.current }]);

  useEffect(() => {
    if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [lines, agentSpeaking]);

  useEffect(() => {
    if (state !== 'live' || !startedAt) return;
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 500);
    return () => clearInterval(timer);
  }, [state, startedAt]);

  // Leaving the page ends the call
  useEffect(
    () => () => {
      if (pcRef.current && callIdRef.current) hangUpRef.current(callIdRef.current).catch(() => {});
      teardown();
    },
    []
  );

  const teardown = () => {
    micRef.current?.getTracks().forEach((track) => track.stop());
    micRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
  };

  const finish = (reason: string) => {
    teardown();
    setAgentSpeaking(false);
    setToolName(null);
    setEndReason(reason);
    setState('ended');
    const id = callIdRef.current;
    // Give the server a moment to save the recording and close the call record
    if (id && !clientMode) setTimeout(() => telephonyService.getCall(id).then(setSummary).catch(() => {}), 1500);
    if (onEndedRef.current) setTimeout(() => onEndedRef.current?.(), 1500);
  };

  const handleMessage = (raw: string) => {
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    switch (msg.type) {
      case 'connected':
        setState('live');
        setStartedAt(Date.now());
        break;
      case 'caller_text':
        if (msg.text) addLine({ role: 'caller', text: msg.text });
        break;
      case 'agent_speaking':
        setAgentSpeaking(true);
        setToolName(null);
        if (typeof msg.response_latency_ms === 'number') setLatencies((prev) => [...prev, msg.response_latency_ms]);
        break;
      case 'tool_started':
        setToolName(msg.tool_name || 'a tool');
        break;
      case 'agent_text':
        setAgentSpeaking(false);
        if (msg.text) addLine({ role: 'assistant', text: msg.text, interrupted: !!msg.interrupted });
        break;
      case 'interrupted':
        setAgentSpeaking(false);
        break;
      case 'call_ended':
        finish(msg.reason || 'caller_hangup');
        break;
    }
  };

  const startCall = async () => {
    setError(null);
    setLines([]);
    setLatencies([]);
    setSummary(null);
    setEndReason(null);
    setElapsed(0);
    setMuted(false);
    setState('connecting');
    try {
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      micRef.current = mic;

      const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
      pcRef.current = pc;
      mic.getTracks().forEach((track) => pc.addTrack(track, mic));

      const channel = pc.createDataChannel('events');
      // The server starts sending once it knows our end of the channel is open
      channel.onopen = () => channel.send(JSON.stringify({ type: 'hello' }));
      channel.onmessage = (event) => handleMessage(event.data);

      pc.ontrack = (event) => {
        if (!audioRef.current) return;
        audioRef.current.srcObject = event.streams[0] || new MediaStream([event.track]);
        audioRef.current.play().catch(() => {});
      };
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' && pcRef.current === pc) {
          setError('The audio connection dropped.');
          finish('connection_failed');
        }
      };

      await pc.setLocalDescription(await pc.createOffer());
      // Send the offer with its ICE candidates (no trickle ICE)
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === 'complete') return resolve();
        const done = () => {
          if (pc.iceGatheringState === 'complete') {
            pc.removeEventListener('icegatheringstatechange', done);
            resolve();
          }
        };
        pc.addEventListener('icegatheringstatechange', done);
        setTimeout(resolve, 2000);
      });

      const offer = { sdp: pc.localDescription!.sdp, type: pc.localDescription!.type };
      const answer = onStart
        ? await onStart(offer)
        : await telephonyService.startBrowserCall({
            agent_id: agentId ?? '',
            agent_version_id: agentVersionId ?? '',
            ...offer,
            user_name: userName?.trim() || undefined,
            company_name: companyName?.trim() || undefined,
          });
      callIdRef.current = answer.call_id;
      setCallId(answer.call_id);
      await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
    } catch (err: any) {
      teardown();
      setState('idle');
      setError(
        err?.name === 'NotAllowedError'
          ? 'Microphone access was blocked. Allow the microphone for this site and try again.'
          : err?.message || 'Could not start the call.'
      );
    }
  };

  const endCall = () => {
    const id = callIdRef.current;
    if (id) hangUpRef.current(id).catch(() => {});
    finish('caller_hangup');
  };

  const toggleMute = () => {
    const next = !muted;
    micRef.current?.getAudioTracks().forEach((track) => (track.enabled = !next));
    setMuted(next);
  };

  const avgLatency = latencies.length ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) : null;
  const clock = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
  const inCall = state === 'connecting' || state === 'live';

  return (
    <div className="space-y-4 px-5 py-6 text-left">
      <audio ref={audioRef} autoPlay className="hidden" />

      <div className="flex flex-col items-center justify-center gap-3 py-2 text-center">
        {state === 'live' ? (
          <>
            <div className="flex h-10 items-end gap-1.5" aria-hidden="true">
              {[45, 75, 55, 90, 60, 80, 50, 70].map((height, index) => (
                <span
                  key={index}
                  className={`w-2 rounded-sm ${agentSpeaking ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`}
                  style={{ height: `${(agentSpeaking ? height : 20) * 0.45}px`, animationDelay: `${index * 120}ms` }}
                />
              ))}
            </div>
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
              <Volume2 className="h-4 w-4" />
              {toolName && !clientMode ? (
                <span className="flex items-center gap-1.5 text-purple-300">
                  <Wrench className="h-3.5 w-3.5" /> Using {toolName}...
                </span>
              ) : agentSpeaking ? (
                'AI employee is speaking'
              ) : (
                'Listening: talk to the AI employee'
              )}
            </p>
            <p className="font-mono text-xs text-slate-500">
              {clock}
              {avgLatency !== null && !clientMode && ` · avg reply ${avgLatency} ms`}
              {muted && ' · muted'}
            </p>
          </>
        ) : state === 'connecting' ? (
          <p className="flex items-center gap-2 text-sm text-slate-300">
            <PhoneCall className="h-4 w-4 animate-pulse text-emerald-400" /> Connecting...
          </p>
        ) : state === 'ended' ? (
          <p className="flex items-center gap-2 text-sm text-slate-300">
            <CheckCircle className="h-4 w-4 text-slate-400" /> Call ended
            {endReason && <span className="text-slate-500">· {END_REASONS[endReason] || endReason}</span>}
          </p>
        ) : clientMode ? (
          <>
            <p className="text-lg text-slate-200">Talk to your AI employee from your browser</p>
            {clientIntro && <p className="max-w-md text-xs text-slate-400">{clientIntro}</p>}
          </>
        ) : (
          <>
            <p className="text-lg text-slate-200">Talk to the AI employee from your browser</p>
            <p className="max-w-md text-xs text-slate-500">
              Runs exactly like a phone call, with phone-quality audio, but free: no telephony charges and no credits
              used. Headphones give the most realistic test.
            </p>
          </>
        )}

        <div className="flex items-center gap-2.5">
          {inCall ? (
            <>
              <Button
                type="button"
                variant="secondary"
                className="rounded-full"
                onClick={toggleMute}
                disabled={state !== 'live'}
                title={muted ? 'Unmute microphone' : 'Mute microphone'}
              >
                {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              </Button>
              <Button
                type="button"
                variant="danger"
                className="min-w-[160px] rounded-full bg-red-600 font-semibold text-white shadow-md shadow-red-950/50 hover:bg-red-500"
                onClick={endCall}
              >
                <PhoneOff className="mr-2 h-4 w-4" /> End Call
              </Button>
            </>
          ) : clientMode && state === 'ended' ? null : (
            <Button
              type="button"
              variant="primary"
              className="min-w-[180px] rounded-full bg-emerald-600 font-semibold text-white shadow-md hover:bg-emerald-500"
              onClick={startCall}
              disabled={!ready || (!onStart && (!agentId || !agentVersionId))}
            >
              <PhoneCall className="mr-2 h-4 w-4" /> {state === 'ended' ? 'Call again' : 'Start Call'}
            </Button>
          )}
        </div>
      </div>

      {!ready && state === 'idle' && !clientMode && (
        <p className="text-center text-xs text-amber-400/90">Select an agent and a ready published version in Setup first.</p>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {(lines.length > 0 || state === 'live') && (
        <div ref={transcriptRef} className="max-h-72 space-y-2 overflow-y-auto rounded-lg border border-[#1b1f2d] bg-[#080b10] p-3">
          {lines.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-500">The transcript appears here as you talk.</p>
          ) : (
            lines.map((line) => (
              <div key={line.id} className={`flex ${line.role === 'caller' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] rounded-lg px-3 py-2 text-xs ${
                    line.role === 'caller' ? 'bg-emerald-950/40 text-emerald-200' : 'bg-[#151824] text-slate-200'
                  }`}
                >
                  {line.text}
                  {line.interrupted && <span className="ml-1.5 text-[10px] text-amber-400">(interrupted)</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {state === 'ended' && callId && !clientMode && (
        <div className="space-y-3 rounded-lg border border-[#1b1f2d] bg-[#080b10] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
            <span>
              Test call <span className="font-mono text-slate-300">{callId}</span>
              {summary?.duration_seconds ? ` · ${Math.round(summary.duration_seconds)}s` : ''}
              {' · '}not billed
            </span>
            <Link to="/calls" className="font-medium text-indigo-400 underline hover:text-indigo-300">
              Open in call logs
            </Link>
          </div>
          {summary?.has_recording && <CallRecordingPlayer callId={callId} />}
        </div>
      )}
    </div>
  );
};
