import React, { useEffect, useState, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import {
  FlaskConical,
  Play,
  Square,
  Send,
  CheckCircle,
  AlertTriangle,
  Activity,
  RefreshCw,
  Mic,
  MicOff,
  Radio,
  Hand,
  Volume2,
  VolumeX,
  Sparkles,
  Layers,
  Sliders,
  History,
  Cpu,
  PhoneCall,
  PhoneOff,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { agentsService } from '../services/agents';
import { runtimeService } from '../services/runtime';
import { request } from '../services/api';
import { testScenariosService, TestRun, TestScenario } from '../services/testScenarios';
import { VoiceScenarioSuite } from '../components/testing/VoiceScenarioSuite';
import { PhoneCallTester } from '../components/testing/PhoneCallTester';
import {
  Agent,
  AgentVersion,
  ReadinessCheckResult,
  RuntimeSession,
  RuntimeEvent,
  SimulateTurnResult,
} from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Select } from '../components/common/Select';
import { StatusBadge, Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';

interface LiveChatMessage {
  id: string;
  sender: 'caller' | 'assistant';
  text: string;
  time: string;
  interrupted?: boolean;
  streaming?: boolean;
  toolStatus?: string;
}

const StreamingText: React.FC<{ message: LiveChatMessage }> = ({ message }) => {
  if (message.streaming && !message.text) {
    return (
      <span className="flex items-center gap-2">
        <span className="flex items-center gap-1" aria-label="AI Employee is typing">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
        </span>
        {message.toolStatus && <span className="text-[11px] text-purple-300">{message.toolStatus}</span>}
      </span>
    );
  }
  return (
    <>
      {message.text}
      {message.streaming && <span className="ml-0.5 inline-block h-3 w-[2px] translate-y-0.5 animate-pulse bg-slate-300" />}
      {message.toolStatus && <span className="mt-1 block text-[11px] text-purple-300">{message.toolStatus}</span>}
    </>
  );
};

export const TestLabPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialAgentId = searchParams.get('agentId') || '';
  const initialVersionId = searchParams.get('versionId') || '';
  const { token } = useAuth();

  // Agents & Versions catalog
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>(initialAgentId);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>(initialVersionId);

  // Readiness State
  const [readiness, setReadiness] = useState<ReadinessCheckResult | null>(null);
  const [isCheckingReadiness, setIsCheckingReadiness] = useState(false);

  // Active Session State
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [isStartingSession, setIsStartingSession] = useState(false);
  const [isEndingSession, setIsEndingSession] = useState(false);

  // Mode Tab: 'stream' | 'simulate' | 'webrtc'
  const [activeTab, setActiveTab] = useState<'stream' | 'simulate' | 'webrtc'>('stream');
  const [testMode, setTestMode] = useState<'voice' | 'phone' | 'chat' | 'scenarios'>('voice');
  const [showTestSetup, setShowTestSetup] = useState(false);
  const [showTestHistory, setShowTestHistory] = useState(false);
  const [showRuntimeDiagnostics, setShowRuntimeDiagnostics] = useState(false);
  const [testLanguage, setTestLanguage] = useState('en');
  const [runtimeMode, setRuntimeMode] = useState<'mock' | 'real' | null>(null);
  const [scenarios, setScenarios] = useState<TestScenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [scenarioName, setScenarioName] = useState('New conversation scenario');
  const [scenarioTurn, setScenarioTurn] = useState('I want to check appointment availability');
  const [scenarioRun, setScenarioRun] = useState<TestRun | null>(null);
  const [isScenarioActionRunning, setIsScenarioActionRunning] = useState(false);

  // Realtime WebRTC State
  const [webrtcStatus, setWebrtcStatus] = useState<'DISCONNECTED' | 'CONNECTING' | 'CONNECTED'>('DISCONNECTED');
  const [webrtcError, setWebrtcError] = useState<string | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const webrtcAudioElRef = useRef<HTMLAudioElement | null>(null);

  // Turn Simulator State (HTTP)
  const [userInput, setUserInput] = useState('I want to see 3 BHK apartments in Whitefield under 1.2 Cr');
  const [lastTurnResult, setLastTurnResult] = useState<SimulateTurnResult | null>(null);
  const [isSimulatingTurn, setIsSimulatingTurn] = useState(false);
  const [chatMessages, setChatMessages] = useState<LiveChatMessage[]>([]);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const runtimeChatScrollRef = useRef<HTMLDivElement | null>(null);

  // Keep the newest (streaming) text in view
  useEffect(() => {
    for (const el of [chatScrollRef.current, runtimeChatScrollRef.current]) {
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [chatMessages]);

  // Mock Lead & Company Source for Test Calls
  const [mockCallerName, setMockCallerName] = useState('Rahul Sharma');
  const [mockCompanyName, setMockCompanyName] = useState('Apex Realty Bangalore');

  // Realtime WebSocket Audio State (Phase 3B)
  const [wsStatus, setWsStatus] = useState<'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'STREAMING'>('DISCONNECTED');
  const [isRecording, setIsRecording] = useState(false);
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const [liveChat, setLiveChat] = useState<LiveChatMessage[]>([]);
  const [wsError, setWsError] = useState<string | null>(null);
  const [partialTranscript, setPartialTranscript] = useState<string | null>(null);
  const [latencyMetrics, setLatencyMetrics] = useState<{
    stt_ms?: number;
    llm_ms?: number;
    tts_ttfb_ms?: number;
    round_trip_ms?: number;
  } | null>(null);

  // Web Audio Refs
  const wsRef = useRef<WebSocket | null>(null);
  const playbackCtxRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const silenceTimerRef = useRef<any>(null);
  const hasSpokenRef = useRef(false);

  // Page loading & errors
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Computed Call In Progress State
  const isCallActive = Boolean(
    (activeSession && activeSession.status === 'ACTIVE') ||
    (chatMessages.length > 0 && chatMessages[chatMessages.length - 1]?.text !== 'Call ended.') ||
    webrtcStatus === 'CONNECTED'
  );

  useEffect(() => {
    request<{ mode: 'mock' | 'real' }>('/runtime/mode')
      .then((response) => setRuntimeMode(response.mode))
      .catch(() => setRuntimeMode(null));
  }, []);

  useEffect(() => {
    if (!selectedAgentId) return;
    testScenariosService.list(selectedAgentId).then((items) => {
      setScenarios(items);
      setSelectedScenarioId((current) => current || items[0]?.id || '');
    }).catch(() => setScenarios([]));
  }, [selectedAgentId]);

  useEffect(() => {
    if (!selectedAgentId || agents.length === 0) return;
    const ag = agents.find((a) => a.id === selectedAgentId);
    if (ag?.client_name && ag.client_name.toLowerCase() !== 'default client') {
      setMockCompanyName(ag.client_name);
    }
  }, [selectedAgentId, agents]);

  // 1. Initial Load: list agents
  useEffect(() => {
    const loadAgents = async () => {
      setIsLoading(true);
      try {
        const res = await agentsService.list({ limit: 100 });
        setAgents(res.items);
        if (!selectedAgentId && res.items.length > 0) {
          setSelectedAgentId(res.items[0].id);
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load AI employees.');
      } finally {
        setIsLoading(false);
      }
    };
    loadAgents();
  }, []);

  // 2. Load versions when agent changes
  useEffect(() => {
    if (!selectedAgentId) {
      setVersions([]);
      setSelectedVersionId('');
      setReadiness(null);
      return;
    }
    const loadVersions = async () => {
      try {
        const vList = await agentsService.getVersions(selectedAgentId);
        const published = vList.filter((v) => v.status === 'PUBLISHED');
        const latestFirst = [...published].sort((a, b) => b.version_number - a.version_number);
        setVersions(latestFirst);
        if (latestFirst.length > 0) {
          const match = latestFirst.find((v) => v.id === initialVersionId);
          setSelectedVersionId(match ? match.id : latestFirst[0].id);
        } else {
          setSelectedVersionId('');
        }
        setReadiness(null);
      } catch (err: any) {
        console.error('Error loading versions:', err);
      }
    };
    loadVersions();
  }, [selectedAgentId]);

  // 3. Automatically check readiness when selectedVersionId changes
  useEffect(() => {
    if (selectedAgentId && selectedVersionId) {
      handleCheckReadiness();
    }
  }, [selectedAgentId, selectedVersionId]);

  // Cleanup WebSocket and Audio contexts on unmount
  useEffect(() => {
    return () => {
      disconnectWebSocket();
    };
  }, []);

  const handleCheckReadiness = async () => {
    if (!selectedAgentId || !selectedVersionId) return;
    setIsCheckingReadiness(true);
    try {
      const res = await runtimeService.checkReadiness(selectedAgentId, selectedVersionId);
      setReadiness(res);
    } catch (err: any) {
      alert(`Readiness check error: ${err.message}`);
    } finally {
      setIsCheckingReadiness(false);
    }
  };

  const handleStartSession = async () => {
    if (!selectedAgentId || !selectedVersionId) return;
    setIsStartingSession(true);
    try {
      const selectedAgent = agents.find((a) => a.id === selectedAgentId);
      const effectiveCompany = mockCompanyName.trim() || selectedAgent?.client_name || 'Apex Realty Bangalore';
      const effectiveCaller = mockCallerName.trim() || 'Rahul Sharma';

      const sess = await runtimeService.startSession(selectedAgentId, selectedVersionId, {
        origin: 'internal_test_lab',
        user_name: effectiveCaller,
        company_name: effectiveCompany,
        lead_id: 'lead_re_101',
      });
      setActiveSession(sess);
      setLastTurnResult(null);

      const selectedVersion = versions.find((version) => version.id === selectedVersionId);
      const rawGreeting = selectedVersion?.configuration_json?.conversation?.greeting ||
        'Hello! How may I help you today?';

      const resolvedGreeting = (sess.metadata as any)?.resolved_greeting ||
        rawGreeting
          .replace(/\{\{user_name\}\}/g, effectiveCaller)
          .replace(/\{\{company_name\}\}/g, effectiveCompany)
          .replace(/\{\{[^}]+\}\}/g, '')
          .trim();

      setChatMessages([
        {
          id: `${Date.now()}-greeting`,
          sender: 'assistant',
          text: resolvedGreeting,
          time: new Date().toLocaleTimeString(),
        },
      ]);
      setLiveChat([]);
      const evts = await runtimeService.getEvents(sess.id);
      setEvents(evts);
    } catch (err: any) {
      alert(`Failed to start session: ${err.message}`);
    } finally {
      setIsStartingSession(false);
    }
  };

  const handleEndSession = async () => {
    if (!activeSession) return;
    const sessionIdToEnd = activeSession.id;
    disconnectWebSocket();
    disconnectWebRTC();
    setIsEndingSession(true);
    try {
      if (activeSession.status === 'ACTIVE') {
        await runtimeService.endSession(sessionIdToEnd);
      }
      setActiveSession(null);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-call-ended`,
          sender: 'assistant',
          text: 'Call ended.',
          time: new Date().toLocaleTimeString(),
        },
      ]);
      setLiveChat((prev) => [
        ...prev,
        {
          id: `${Date.now()}-call-ended`,
          sender: 'assistant',
          text: 'Call ended.',
          time: new Date().toLocaleTimeString(),
        },
      ]);
      const updatedEvents = await runtimeService.getEvents(sessionIdToEnd).catch(() => []);
      if (updatedEvents) setEvents(updatedEvents);
    } catch (err: any) {
      setActiveSession(null);
      console.warn('Session termination notice:', err?.message || err);
    } finally {
      setIsEndingSession(false);
    }
  };

  const handleCreateScenario = async () => {
    if (!selectedAgentId || !selectedVersionId || !scenarioName.trim() || !scenarioTurn.trim()) return;
    setIsScenarioActionRunning(true);
    try {
      const created = await testScenariosService.create({
        agent_id: selectedAgentId,
        agent_version_id: selectedVersionId,
        name: scenarioName.trim(),
        caller_goal: scenarioTurn.trim(),
        turns: scenarioTurn.split('\n').map((turn) => turn.trim()).filter(Boolean),
        expected: {},
      });
      setScenarios((current) => [created, ...current]);
      setSelectedScenarioId(created.id);
    } catch (err: any) {
      alert(`Scenario save failed: ${err.message || 'Unable to save scenario.'}`);
    } finally {
      setIsScenarioActionRunning(false);
    }
  };

  const handleRunScenario = async () => {
    if (!selectedScenarioId) return;
    setIsScenarioActionRunning(true);
    try {
      setScenarioRun(await testScenariosService.run(selectedScenarioId));
    } catch (err: any) {
      alert(`Scenario run failed: ${err.message || 'Unable to run scenario.'}`);
    } finally {
      setIsScenarioActionRunning(false);
    }
  };

  // -------------------------------------------------------------
  // REALTIME WEBSOCKET AUDIO STREAMING (PHASE 3B)
  // -------------------------------------------------------------
  // REALTIME WEBSOCKET AUDIO STREAMING (PHASE 3B)
  // -------------------------------------------------------------

  const downsampleTo16kHz = (inputData: Float32Array, inputSampleRate: number): Int16Array => {
    if (inputSampleRate === 16000) {
      const pcm16 = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      return pcm16;
    }
    const ratio = inputSampleRate / 16000;
    const newLength = Math.round(inputData.length / ratio);
    const pcm16 = new Int16Array(newLength);
    for (let i = 0; i < newLength; i++) {
      const originIdx = i * ratio;
      const floorIdx = Math.floor(originIdx);
      const ceilIdx = Math.min(floorIdx + 1, inputData.length - 1);
      const weight = originIdx - floorIdx;
      const sample = inputData[floorIdx] * (1 - weight) + inputData[ceilIdx] * weight;
      const s = Math.max(-1, Math.min(1, sample));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return pcm16;
  };

  const initPlaybackContext = () => {
    if (!playbackCtxRef.current || playbackCtxRef.current.state === 'closed') {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      try {
        playbackCtxRef.current = new AudioCtx({ sampleRate: 16000 });
      } catch {
        // Fallback for OS/audio drivers requiring native sample rate (e.g. 44.1k / 48k on Windows)
        playbackCtxRef.current = new AudioCtx();
      }
      nextPlayTimeRef.current = playbackCtxRef.current.currentTime;
    }
    if (playbackCtxRef.current.state === 'suspended') {
      playbackCtxRef.current.resume().catch(() => {});
    }
    return playbackCtxRef.current;
  };

  const playPcmAudioChunk = (pcmData: ArrayBuffer) => {
    try {
      const ctx = initPlaybackContext();
      const int16Array = new Int16Array(pcmData);
      const float32Array = new Float32Array(int16Array.length);
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768.0;
      }

      const audioBuffer = ctx.createBuffer(1, float32Array.length, 16000);
      audioBuffer.getChannelData(0).set(float32Array);

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);

      const now = ctx.currentTime;
      const startTime = Math.max(now, nextPlayTimeRef.current);
      source.start(startTime);
      nextPlayTimeRef.current = startTime + audioBuffer.duration;
      setIsAssistantSpeaking(true);
    } catch (e) {
      console.error('Audio playback error:', e);
    }
  };

  const connectWebSocket = () => {
    if (!activeSession || !token) return;
    initPlaybackContext();
    setWsError(null);
    setWsStatus('CONNECTING');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/runtime/sessions/${activeSession.id}/audio?token=${encodeURIComponent(
      token
    )}`;

    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('CONNECTED');
      initPlaybackContext();
    };

    ws.onmessage = async (event) => {
      if (typeof event.data !== 'string') {
        // Binary raw PCM audio frame from Cartesia TTS
        playPcmAudioChunk(event.data);
      } else {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'transcript') {
            if (msg.final) {
              setPartialTranscript(null);
              setLiveChat((prev) => [
                ...prev,
                {
                  id: Math.random().toString(36).substring(7),
                  sender: 'caller',
                  text: msg.text,
                  time: new Date().toLocaleTimeString(),
                },
              ]);
            } else {
              setPartialTranscript(msg.text);
            }
          } else if (msg.type === 'assistant_text') {
            setLiveChat((prev) => [
              ...prev,
              {
                id: Math.random().toString(36).substring(7),
                sender: 'assistant',
                text: msg.text,
                time: new Date().toLocaleTimeString(),
              },
            ]);
          } else if (msg.type === 'latency_metrics') {
            setLatencyMetrics(msg.metrics);
          } else if (msg.type === 'interrupted') {
            // Barge in received: clear audio context
            if (playbackCtxRef.current) {
              playbackCtxRef.current.close().catch(() => {});
              playbackCtxRef.current = null;
            }
            setIsAssistantSpeaking(false);
            setLiveChat((prev) => {
              if (prev.length === 0) return prev;
              const last = prev[prev.length - 1];
              if (last.sender === 'assistant') {
                return [...prev.slice(0, -1), { ...last, interrupted: true }];
              }
              return prev;
            });
          } else if (msg.type === 'turn_complete') {
            setIsAssistantSpeaking(false);
            if (msg.usage) {
              setActiveSession((prev) => prev ? { ...prev, usage: msg.usage } : prev);
            }
            // Refresh session events & usage in background
            if (activeSession) {
              runtimeService.getEvents(activeSession.id).then(setEvents).catch(() => {});
              runtimeService.getSession(activeSession.id).then(setActiveSession).catch(() => {});
            }
          } else if (msg.type === 'error') {
            setWsError(msg.message);
          }
        } catch (e) {
          console.error('WebSocket JSON parse error:', e);
        }
      }
    };

    ws.onerror = (e) => {
      console.error('WebSocket audio transport error:', e);
      setWsError('WebSocket transport connection failed. Please check network/auth.');
      setWsStatus('DISCONNECTED');
    };

    ws.onclose = () => {
      setWsStatus('DISCONNECTED');
      setIsRecording(false);
      setIsAssistantSpeaking(false);
    };
  };

  const disconnectWebSocket = () => {
    stopMicrophone();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (playbackCtxRef.current) {
      playbackCtxRef.current.close().catch(() => {});
      playbackCtxRef.current = null;
    }
    setWsStatus('DISCONNECTED');
    setIsAssistantSpeaking(false);
  };

  const startMicrophone = async () => {
    // Unlock and prime audio output on direct user gesture
    initPlaybackContext();

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connectWebSocket();
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;

      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      let audioCtx: AudioContext;
      try {
        audioCtx = new AudioCtx({ sampleRate: 16000 });
      } catch {
        // Fallback for audio devices on Windows requiring native hardware sample rate (e.g. 48kHz)
        audioCtx = new AudioCtx();
      }
      recordCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      // ScriptProcessor buffer 2048 samples ~128ms
      const processor = audioCtx.createScriptProcessor(2048, 1, 1);
      processorRef.current = processor;

      // Notify server turn started
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'start' }));
      }

      hasSpokenRef.current = false;
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }

      processor.onaudioprocess = (e) => {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        const inputData = e.inputBuffer.getChannelData(0);

        let sum = 0;
        for (let i = 0; i < inputData.length; i++) {
          sum += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sum / inputData.length);

        // VAD Speech Activity Detection
        if (rms > 0.02) {
          hasSpokenRef.current = true;
          if (silenceTimerRef.current) {
            clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = null;
          }
        } else if (hasSpokenRef.current && !silenceTimerRef.current) {
          // User paused speaking: auto-send turn after 1 second
          silenceTimerRef.current = setTimeout(() => {
            stopMicrophone();
          }, 1000);
        }

        // Downsample to exact 16kHz PCM16 for Cartesia STT
        const pcm16 = downsampleTo16kHz(inputData, audioCtx.sampleRate);
        wsRef.current.send(pcm16.buffer as ArrayBuffer);
      };

      // Connect through a zero-gain node to keep processor active without audio feedback into speakers
      const muteNode = audioCtx.createGain();
      muteNode.gain.value = 0;
      source.connect(processor);
      processor.connect(muteNode);
      muteNode.connect(audioCtx.destination);
      setIsRecording(true);
      setWsStatus('STREAMING');
    } catch (err: any) {
      alert(`Microphone access error: ${err.message || 'Permission denied'}`);
      setIsRecording(false);
    }
  };

  const stopMicrophone = () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    hasSpokenRef.current = false;

    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (recordCtxRef.current) {
      recordCtxRef.current.close().catch(() => {});
      recordCtxRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
    }
    setIsRecording(false);
    if (wsStatus === 'STREAMING') {
      setWsStatus('CONNECTED');
    }
  };

  const handleBargeIn = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'interrupt' }));
    }
    if (playbackCtxRef.current) {
      playbackCtxRef.current.close().catch(() => {});
      playbackCtxRef.current = null;
    }
    setIsAssistantSpeaking(false);
  };

  // -------------------------------------------------------------
  // REALTIME WEBRTC AUDIO STREAMING (OPUS / UDP)
  // -------------------------------------------------------------
  const connectWebRTC = async () => {
    if (!activeSession || !token) return;
    setWebrtcError(null);
    setWebrtcStatus('CONNECTING');

    try {
      // 1. Get user microphone stream
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      // 2. Setup RTCPeerConnection with STUN
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'] }],
      });
      pcRef.current = pc;

      // Add caller mic audio track
      stream.getTracks().forEach((track) => pc.addTrack(track, stream));

      // 3. Create DataChannel for real-time events & telemetry
      const dc = pc.createDataChannel('events');
      dataChannelRef.current = dc;

      dc.onopen = () => {
        setWebrtcStatus('CONNECTED');
      };

      dc.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'transcript') {
            if (msg.final) {
              setPartialTranscript(null);
              if (msg.text && msg.text.trim()) {
                setLiveChat((prev) => [
                  ...prev,
                  {
                    id: Math.random().toString(36).substring(7),
                    sender: 'caller',
                    text: msg.text.trim(),
                    time: new Date().toLocaleTimeString(),
                  },
                ]);
              }
            } else {
              setPartialTranscript(msg.text);
            }
          } else if (msg.type === 'assistant_text') {
            setLiveChat((prev) => [
              ...prev,
              {
                id: Math.random().toString(36).substring(7),
                sender: 'assistant',
                text: msg.text,
                time: new Date().toLocaleTimeString(),
              },
            ]);
            setIsAssistantSpeaking(true);
          } else if (msg.type === 'latency_metrics') {
            setLatencyMetrics(msg.metrics);
          } else if (msg.type === 'interrupted') {
            setIsAssistantSpeaking(false);
            setLiveChat((prev) => {
              if (prev.length === 0) return prev;
              const last = prev[prev.length - 1];
              if (last.sender === 'assistant') {
                return [...prev.slice(0, -1), { ...last, interrupted: true }];
              }
              return prev;
            });
          } else if (msg.type === 'turn_complete') {
            setIsAssistantSpeaking(false);
            if (msg.usage) {
              setActiveSession((prev) => (prev ? { ...prev, usage: msg.usage } : prev));
            }
            if (activeSession) {
              runtimeService.getEvents(activeSession.id).then(setEvents).catch(() => {});
              runtimeService.getSession(activeSession.id).then(setActiveSession).catch(() => {});
            }
          }
        } catch (e) {
          console.error('WebRTC DataChannel message parse error:', e);
        }
      };

      // 4. Handle incoming agent audio track via Opus/UDP
      pc.ontrack = (event) => {
        if (event.track.kind === 'audio') {
          const stream = event.streams && event.streams[0] ? event.streams[0] : new MediaStream([event.track]);
          if (!webrtcAudioElRef.current) {
            const audioEl = document.createElement('audio');
            audioEl.autoplay = true;
            (audioEl as any).playsInline = true;
            webrtcAudioElRef.current = audioEl;
            document.body.appendChild(audioEl);
          }
          webrtcAudioElRef.current.srcObject = stream;
          webrtcAudioElRef.current.play().catch((e) => console.log('Audio autoplay prevented:', e));
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'connected') {
          setWebrtcStatus('CONNECTED');
        } else if (['disconnected', 'failed', 'closed'].includes(pc.connectionState)) {
          setWebrtcStatus('DISCONNECTED');
        }
      };

      // 5. Create Offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait for ICE gathering to complete before sending SDP
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === 'complete') {
          resolve();
        } else {
          const checkState = () => {
            if (pc.iceGatheringState === 'complete') {
              pc.removeEventListener('icegatheringstatechange', checkState);
              resolve();
            }
          };
          pc.addEventListener('icegatheringstatechange', checkState);
          setTimeout(resolve, 1500);
        }
      });

      // 6. Send Offer to backend
      const res = await fetch(`/api/runtime/sessions/${activeSession.id}/webrtc/offer?token=${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: pc.localDescription?.sdp || offer.sdp,
          type: pc.localDescription?.type || offer.type,
        }),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Server rejected offer with status ${res.status}`);
      }

      const answer = await res.json();
      await pc.setRemoteDescription(new RTCSessionDescription(answer));
      setWebrtcStatus('CONNECTED');
    } catch (err: any) {
      console.error('WebRTC connection failed:', err);
      setWebrtcError(err.message || 'WebRTC connection failed');
      disconnectWebRTC();
    }
  };

  const disconnectWebRTC = () => {
    if (pcRef.current) {
      pcRef.current.getSenders().forEach((s) => s.track?.stop());
      pcRef.current.close();
      pcRef.current = null;
    }
    if (dataChannelRef.current) {
      dataChannelRef.current.close();
      dataChannelRef.current = null;
    }
    if (webrtcAudioElRef.current) {
      webrtcAudioElRef.current.srcObject = null;
    }
    setWebrtcStatus('DISCONNECTED');
    setIsAssistantSpeaking(false);
    if (activeSession) {
      fetch(`/api/runtime/sessions/${activeSession.id}/webrtc/close`, { method: 'POST' }).catch(() => {});
    }
  };

  const handleWebRTCBargeIn = () => {
    if (dataChannelRef.current && dataChannelRef.current.readyState === 'open') {
      dataChannelRef.current.send(JSON.stringify({ type: 'interrupt' }));
    }
    setIsAssistantSpeaking(false);
  };


  // -------------------------------------------------------------
  // SIMULATED TURN (HTTP - PHASE 3A)
  // -------------------------------------------------------------
  const handleSimulateTurn = async () => {
    if (!userInput.trim()) return;
    const inputText = userInput.trim();
    setIsSimulatingTurn(true);
    try {
      let currentSession = activeSession;
      const lastMsg = chatMessages[chatMessages.length - 1];
      const callWasEnded = lastMsg?.text === 'Call ended.';

      if (!currentSession || currentSession.status !== 'ACTIVE' || callWasEnded) {
        const selectedAgent = agents.find((a) => a.id === selectedAgentId);
        const effectiveCompany = mockCompanyName.trim() || selectedAgent?.client_name || 'Apex Realty Bangalore';
        const effectiveCaller = mockCallerName.trim() || 'Rahul Sharma';

        currentSession = await runtimeService.startSession(selectedAgentId, selectedVersionId, {
          origin: 'internal_test_lab',
          user_name: effectiveCaller,
          company_name: effectiveCompany,
          lead_id: 'lead_re_101',
        });
        setActiveSession(currentSession);

        const selectedVersion = versions.find((version) => version.id === selectedVersionId);
        const rawGreeting = selectedVersion?.configuration_json?.conversation?.greeting ||
          'Hello! How may I help you today?';

        const resolvedGreeting = (currentSession.metadata as any)?.resolved_greeting ||
          rawGreeting
            .replace(/\{\{user_name\}\}/g, effectiveCaller)
            .replace(/\{\{company_name\}\}/g, effectiveCompany)
            .replace(/\{\{[^}]+\}\}/g, '')
            .trim();

        setChatMessages([
          {
            id: `${Date.now()}-greeting`,
            sender: 'assistant',
            text: resolvedGreeting,
            time: new Date().toLocaleTimeString(),
          },
        ]);
      }

      setChatMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-caller`,
          sender: 'caller',
          text: inputText,
          time: new Date().toLocaleTimeString(),
        },
      ]);
      setUserInput('');

      // Stream the reply into an assistant bubble as the LLM produces it
      const assistantId = `${Date.now()}-assistant`;
      const setAssistant = (update: (msg: LiveChatMessage) => LiveChatMessage) =>
        setChatMessages((prev) => prev.map((msg) => (msg.id === assistantId ? update(msg) : msg)));
      setChatMessages((prev) => [
        ...prev,
        { id: assistantId, sender: 'assistant', text: '', time: new Date().toLocaleTimeString(), streaming: true },
      ]);

      const sessionForTurn = currentSession;
      let streamError: string | null = null;
      await runtimeService.streamTurn(sessionForTurn.id, inputText, (event) => {
        if (event.type === 'delta') {
          setAssistant((msg) => ({ ...msg, text: msg.text + event.text, toolStatus: undefined }));
        } else if (event.type === 'tool') {
          setAssistant((msg) => ({
            ...msg,
            toolStatus: event.status === 'started' ? `Running ${event.tool_name.replace(/_/g, ' ')}...` : undefined,
          }));
        } else if (event.type === 'done') {
          setAssistant((msg) => ({
            ...msg,
            text: event.display_text || event.assistant_response,
            streaming: false,
            toolStatus: undefined,
          }));
          setLastTurnResult({
            session_id: sessionForTurn.id,
            transcript: event.transcript,
            assistant_response: event.assistant_response,
            audio_duration_seconds: 0,
            tool_calls_executed: event.tool_calls_executed,
            usage: event.usage,
            events: event.events,
          });
          setActiveSession({
            ...sessionForTurn,
            status: 'ACTIVE',
            usage: event.usage || sessionForTurn.usage || {},
          });
          // The turn's events come back with the reply (they are persisted in the background)
          setEvents((prev) => [...prev, ...event.events]);
        } else if (event.type === 'error') {
          streamError = event.message;
        }
      });

      if (streamError) {
        setChatMessages((prev) => prev.filter((msg) => msg.id !== assistantId || msg.text));
        setAssistant((msg) => ({ ...msg, streaming: false, toolStatus: undefined }));
        throw new Error(streamError);
      }
    } catch (err: any) {
      setChatMessages((prev) => prev.filter((msg) => !(msg.sender === 'assistant' && msg.streaming && !msg.text)));
      alert(`Simulation turn failed: ${err.message}`);
    } finally {
      setIsSimulatingTurn(false);
    }
  };

  if (isLoading) {
    return <LoadingState message="Loading Voice Runtime Test Lab..." />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  }

  return (
    <div className="space-y-6 pb-16">
      {/* HEADER */}
      <div className="flex flex-col gap-4 rounded-xl border border-[#1b1f2d] bg-[#0c0e14] p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
            <span className="font-semibold text-slate-200">Voice Runtime</span>
            <span>&bull;</span>
            <span className="font-mono text-purple-400">Realtime Voice Providers</span>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-950/60 border border-purple-800/40 text-purple-400">
              <FlaskConical className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">Runtime Test Lab</h1>
                <Badge variant={runtimeMode === 'mock' ? 'yellow' : 'purple'} dot>
                  {runtimeMode === 'mock' ? 'MOCK RUNTIME ACTIVE' : 'CARTESIA + GEMINI ACTIVE'}
                </Badge>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                {runtimeMode === 'mock'
                  ? 'Safe simulated voice transport with no external provider calls.'
                  : 'Streaming audio transport connecting Cartesia (STT &amp; TTS) and Google Gemini (LLM) over WebSockets.'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* COMPACT TEST AGENT LAUNCHER */}
      <section className="overflow-hidden rounded-2xl border border-[#1b1f2d] bg-[#0c0e14] text-slate-100 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight">Test Agent</h2>
            {isCallActive && (
              <span className="flex items-center gap-1.5 rounded-full border border-emerald-800/60 bg-emerald-950/40 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
                Active Call
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isCallActive && (
              <Button
                type="button"
                size="sm"
                variant="danger"
                onClick={handleEndSession}
                disabled={isEndingSession}
                isLoading={isEndingSession}
                className="bg-red-600 hover:bg-red-500 text-white font-medium border-none shadow-sm px-3 py-1"
                title="End the active call"
              >
                <PhoneOff className="mr-1.5 h-3.5 w-3.5" /> End Call
              </Button>
            )}
            <button
              type="button"
              onClick={() => setShowTestHistory((visible) => !visible)}
              className="rounded-full p-2 text-slate-500 transition-colors hover:bg-[#151824] hover:text-slate-200"
              title="Show runtime event history"
            >
              <History className="h-4 w-4" />
            </button>
            <span className="rounded-full border border-amber-800/50 bg-amber-950/40 px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-300">
              {runtimeMode === 'real' ? 'Real providers' : 'Mock / Simulated'}
            </span>
          </div>
        </div>

        <div className="flex justify-center border-b border-[#1b1f2d] px-5 pb-4">
          <div className="inline-flex rounded-full bg-[#151824] p-1 shadow-inner">
            {[
              { id: 'voice' as const, label: 'Voice Call', icon: Mic },
              { id: 'phone' as const, label: 'Phone Call', icon: PhoneCall },
              { id: 'chat' as const, label: 'Chat Turn', icon: Sparkles },
              { id: 'scenarios' as const, label: 'Scenarios & Regressions', icon: Layers },
            ].map(({ id: modeId, label, icon: Icon }) => (
              <button
                key={modeId}
                type="button"
                onClick={() => setTestMode(modeId)}
                className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  testMode === modeId ? 'bg-purple-600 text-white shadow-sm font-semibold' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Icon className="h-4 w-4" /> {label}
              </button>
            ))}
          </div>
        </div>

        {/* Mock Context Banner */}
        <div className="border-b border-[#1b1f2d] bg-[#10131d]/90 px-5 py-2.5 flex flex-wrap items-center justify-between text-xs text-slate-300 gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400 flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" /> Mock Lead Active:
            </span>
            <span className="font-semibold text-slate-100">{mockCallerName}</span>
            <span className="text-slate-600">•</span>
            <span className="text-slate-400">Company:</span>
            <span className="font-medium text-slate-200">{mockCompanyName || agents.find((a) => a.id === selectedAgentId)?.client_name || 'Apex Realty Bangalore'}</span>
            <span className="text-slate-600">•</span>
            <span className="text-[11px] text-slate-400 font-mono">lead_re_101</span>
            <span className="rounded bg-emerald-950/60 border border-emerald-800/50 px-1.5 py-0.5 text-[10px] text-emerald-300">Mock Data Loaded</span>
          </div>
          <button
            type="button"
            onClick={() => setShowTestSetup((v) => !v)}
            className="text-[11px] text-indigo-400 hover:text-indigo-300 underline font-medium"
          >
            {showTestSetup ? 'Hide Custom Lead' : 'Change Lead / Company Data'}
          </button>
        </div>

        {showTestSetup && (
          <div className="grid gap-3 border-b border-[#1b1f2d] bg-[#10131d] px-5 py-4 sm:grid-cols-2 md:grid-cols-4">
            <Select
              label="Language"
              size="sm"
              options={(() => {
                const languages = (versions.find((version) => version.id === selectedVersionId)?.configuration_json as any)?.languages;
                const supported = Array.isArray(languages?.supported) ? languages.supported : ['en'];
                return supported.map((language: string) => ({ value: language, label: language }));
              })()}
              value={testLanguage}
              onChange={(event) => setTestLanguage(event.target.value)}
            />
            <div>
              <label className="block text-[11px] font-medium text-slate-300 mb-1">Mock Lead Name (user_name)</label>
              <input
                type="text"
                value={mockCallerName}
                onChange={(e) => setMockCallerName(e.target.value)}
                placeholder="e.g. Rahul Sharma"
                className="w-full rounded-md border border-[#26303c] bg-[#0c0e14] px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-[#00df8f] outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-300 mb-1">Company Name (company_name)</label>
              <input
                type="text"
                value={mockCompanyName}
                onChange={(e) => setMockCompanyName(e.target.value)}
                placeholder="e.g. Apex Realty Bangalore"
                className="w-full rounded-md border border-[#26303c] bg-[#0c0e14] px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-[#00df8f] outline-none"
              />
            </div>
            <div className="flex items-end">
              <div className="w-full rounded-md border border-emerald-800/40 bg-emerald-950/20 px-3 py-2 text-[11px] text-emerald-300 leading-tight">
                Mock Source Active: Auto-injected into greeting &amp; CRM tools.
              </div>
            </div>
          </div>
        )}

        {showTestHistory && (
          <div className="border-b border-[#1b1f2d] bg-[#10131d] px-5 py-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Runtime history</span>
              <span className="text-[11px] text-slate-400">{events.length} persisted events</span>
            </div>
            {events.length === 0 ? (
              <p className="text-xs text-slate-500">Start a session to populate the event history.</p>
            ) : (
              <div className="max-h-32 space-y-1 overflow-y-auto">
                {events.slice(-8).reverse().map((event) => (
                  <div key={event.id} className="flex items-center justify-between rounded border border-[#26303c] bg-[#0c0e14] px-3 py-2 text-[11px] text-slate-400">
                    <span className="font-mono">{event.event_type}</span>
                    <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {testMode === 'scenarios' ? (
          <div className="p-5 text-left border-t border-[#1b1f2d]">
            <VoiceScenarioSuite
              selectedAgentId={selectedAgentId}
              selectedVersionId={selectedVersionId}
              runtimeMode={runtimeMode}
              agents={agents}
              versions={versions}
            />
          </div>
        ) : testMode === 'phone' ? (
          <PhoneCallTester
            agentId={selectedAgentId}
            agentVersionId={selectedVersionId}
            ready={!!readiness?.ready}
          />
        ) : testMode === 'chat' ? (
          <div className="space-y-3 px-5 py-5 text-left">
            <div ref={chatScrollRef} className="max-h-72 min-h-[160px] space-y-2 overflow-y-auto rounded-lg border border-[#1b1f2d] bg-[#080b10] p-3">
              {chatMessages.length === 0 ? (
                <p className="py-8 text-center text-xs text-slate-500">Type a message below to test the agent...</p>
              ) : (
                chatMessages.map((message) =>
                  message.text === 'Call ended.' ? (
                    <div key={message.id} className="flex justify-center my-2">
                      <span className="flex items-center gap-1.5 rounded-full border border-red-800/50 bg-red-950/50 px-3 py-1 text-[11px] font-semibold text-red-300">
                        <PhoneOff className="h-3 w-3" /> Call ended
                      </span>
                    </div>
                  ) : (
                    <div key={message.id} className={`flex ${message.sender === 'caller' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-xs ${message.sender === 'caller' ? 'bg-emerald-950/40 text-emerald-200' : 'bg-[#151824] text-slate-200'}`}>
                        <StreamingText message={message} />
                      </div>
                    </div>
                  )
                )
              )}
            </div>
            <div className="flex gap-2">
              <input
                value={userInput}
                onChange={(event) => setUserInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && userInput.trim() && !isSimulatingTurn) {
                    handleSimulateTurn();
                  }
                }}
                disabled={isSimulatingTurn}
                placeholder={isCallActive ? "Type your response to continue the call..." : "Type a message to start a new call..."}
                className="min-w-0 flex-1 rounded-lg border border-[#26303c] bg-[#10131d] px-3 py-2 text-xs text-slate-100 placeholder-slate-500 outline-none focus:border-[#00df8f]"
              />
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={handleSimulateTurn}
                disabled={!userInput.trim() || isSimulatingTurn}
                isLoading={isSimulatingTurn}
              >
                <Send className="mr-1.5 h-3.5 w-3.5" /> Send
              </Button>
              {isCallActive && (
                <Button
                  type="button"
                  size="sm"
                  variant="danger"
                  onClick={handleEndSession}
                  disabled={isEndingSession}
                  isLoading={isEndingSession}
                  className="bg-red-600 hover:bg-red-500 text-white font-medium border-none shadow-sm px-3"
                  title="End and close active call session"
                >
                  <PhoneOff className="mr-1.5 h-3.5 w-3.5" /> End Call
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div className="flex min-h-[170px] flex-col items-center justify-center px-5 py-8 text-center">
            {webrtcStatus === 'CONNECTED' ? (
              <>
                <div className="mb-4 flex items-end gap-1.5" aria-hidden="true">
                  {[45, 75, 55, 90, 60, 80, 50, 70].map((height, index) => (
                    <span
                      key={index}
                      className="w-2 rounded-sm bg-emerald-400 animate-pulse"
                      style={{ height: `${height * 0.8}px`, animationDelay: `${index * 120}ms` }}
                    />
                  ))}
                </div>
                <p className="text-lg font-semibold text-emerald-300 flex items-center gap-2">
                  <Volume2 className="h-5 w-5 animate-bounce" /> Call in Progress with AI Agent
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  Streaming audio live (WebRTC + Opus) • Active session {activeSession?.id}
                </p>
                <Button
                  type="button"
                  variant="danger"
                  className="mt-4 rounded-full bg-red-600 hover:bg-red-500 text-white font-semibold px-6 py-2.5 shadow-lg shadow-red-950/60"
                  onClick={() => {
                    disconnectWebRTC();
                    handleEndSession();
                  }}
                >
                  <PhoneOff className="mr-2 h-4 w-4" /> End Call
                </Button>
              </>
            ) : (
              <>
                <div className="mb-5 flex items-end gap-1.5" aria-hidden="true">
                  {[32, 58, 40, 72, 46, 62].map((height, index) => (
                    <span key={index} className="w-2 rounded-sm bg-rose-400/80" style={{ height }} />
                  ))}
                </div>
                <p className="text-lg text-slate-200">
                  Start a call to test the agent
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {activeSession && activeSession.status === 'ACTIVE'
                    ? `Active session ${activeSession.id}`
                    : 'Select an agent and published version below'}
                </p>
              </>
            )}
          </div>
        )}

        {testMode !== 'scenarios' && (
          <div className="flex flex-col gap-3 border-t border-[#1b1f2d] p-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3 rounded-full border border-[#26303c] bg-[#10131d] px-4 py-2 text-sm text-slate-300">
              <button
                type="button"
                onClick={() => setShowTestSetup((visible) => !visible)}
                className="flex items-center gap-2 font-medium hover:text-slate-100"
              >
                <Sliders className="h-4 w-4 text-slate-500" />
                <span>Setup</span>
              </button>
              <span className="text-slate-600">|</span>
              <span className="text-xs text-slate-500">
                {selectedVersionId ? `Version ${versions.find((v) => v.id === selectedVersionId)?.version_number || '-'}` : 'No version selected'}
              </span>
            </div>

            {testMode === 'phone' ? null : webrtcStatus === 'CONNECTED' ? (
              <Button
                type="button"
                variant="danger"
                className="min-w-[180px] rounded-full bg-red-600 text-white hover:bg-red-500 font-semibold shadow-md shadow-red-950/50"
                onClick={() => {
                  disconnectWebRTC();
                  handleEndSession();
                }}
              >
                <PhoneOff className="mr-2 h-4 w-4" /> End Call
              </Button>
            ) : isCallActive ? (
              <div className="flex items-center gap-2.5">
                <Button
                  type="button"
                  variant="danger"
                  size="md"
                  className="rounded-full bg-red-600 hover:bg-red-500 text-white font-semibold px-6 py-2 shadow-md shadow-red-950/50"
                  onClick={handleEndSession}
                  isLoading={isEndingSession}
                >
                  <PhoneOff className="mr-2 h-4 w-4" /> End Call
                </Button>
                {testMode === 'voice' && (
                  <Button
                    type="button"
                    variant="primary"
                    className="min-w-[160px] rounded-full bg-emerald-600 text-white hover:bg-emerald-500 font-semibold shadow-md shadow-emerald-950/50"
                    disabled={webrtcStatus === 'CONNECTING'}
                    isLoading={webrtcStatus === 'CONNECTING'}
                    onClick={() => {
                      setActiveTab('webrtc');
                      connectWebRTC();
                    }}
                  >
                    <Play className="mr-2 h-4 w-4" /> Start Audio Stream
                  </Button>
                )}
              </div>
            ) : (
              <Button
                type="button"
                variant="primary"
                className="min-w-[180px] rounded-full bg-emerald-600 text-white hover:bg-emerald-500 font-semibold shadow-md"
                disabled={!readiness?.ready}
                isLoading={isStartingSession}
                onClick={handleStartSession}
              >
                <Play className="mr-2 h-4 w-4" /> Start New Call
              </Button>
            )}
          </div>
        )}
      </section>

      {testMode !== 'scenarios' && (
        <VoiceScenarioSuite
          selectedAgentId={selectedAgentId}
          selectedVersionId={selectedVersionId}
          runtimeMode={runtimeMode}
          agents={agents}
          versions={versions}
        />
      )}

      {activeSession && (
        <div className="flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setShowRuntimeDiagnostics((visible) => !visible)}
          >
            <Activity className="mr-1.5 h-3.5 w-3.5" />
            {showRuntimeDiagnostics ? 'Hide runtime diagnostics' : 'Open runtime diagnostics'}
          </Button>
        </div>
      )}

      {/* TOP CONTROLS & READINESS */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Selection Card */}
        <Card title="Agent & Pinned Version" className="lg:col-span-1">
          <div className="space-y-4 text-xs">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">Select AI Employee</label>
              <Select
                options={agents.map((ag) => ({
                  value: ag.id,
                  label: `${ag.name} (${ag.role})`,
                }))}
                value={selectedAgentId}
                onChange={(e) => setSelectedAgentId(e.target.value)}
                disabled={activeSession?.status === 'ACTIVE'}
                placeholder="Choose AI Employee..."
                size="sm"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Select Published Version (Immutable)
              </label>
              {versions.length === 0 ? (
                <div className="rounded border border-amber-900/40 bg-amber-950/20 p-2.5 text-[11px] text-amber-300 space-y-2">
                  <p>No published versions found for this agent. Please publish Version 1 in the Agent Studio.</p>
                  <Link
                    to={`/agents/${selectedAgentId}`}
                    className="inline-flex items-center gap-1 font-semibold text-[#00df8f] hover:underline"
                  >
                    Open Agent Studio &rarr;
                  </Link>
                </div>
              ) : (
                <>
                  <Select
                    options={versions.map((v) => ({
                      value: v.id,
                      label: `Version ${v.version_number} • ${v.id.substring(0, 16)}...`,
                    }))}
                    value={selectedVersionId}
                    onChange={(e) => setSelectedVersionId(e.target.value)}
                    disabled={activeSession?.status === 'ACTIVE'}
                    placeholder="Choose Version..."
                    size="sm"
                  />

                  {/* Configured Voice Summary Chip */}
                  {(() => {
                    const selVer = versions.find((v) => v.id === selectedVersionId);
                    const voiceConf = (selVer?.configuration_json as any)?.voice;
                    return (
                      <div className="rounded bg-[#0c1c24] border border-[#143c49] p-2 flex items-center justify-between text-[11px] mt-2">
                        <div className="flex items-center gap-2">
                          <Volume2 className="h-3.5 w-3.5 text-purple-400 shrink-0" />
                          <span className="text-slate-300 truncate">
                            Voice: <strong className="text-slate-100">{voiceConf?.voice_id ? `${voiceConf.voice_id.substring(0, 8)}...` : 'Default (Greg)'}</strong>
                          </span>
                        </div>
                        <Link
                          to={`/agents/${selectedAgentId}?tab=voice`}
                          className="text-[10px] text-[#00df8f] hover:underline shrink-0 ml-2"
                        >
                          Configure
                        </Link>
                      </div>
                    );
                  })()}
                </>
              )}
            </div>

            <div className="pt-2 flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                className="flex-1"
                onClick={handleCheckReadiness}
                isLoading={isCheckingReadiness}
                disabled={!selectedVersionId || activeSession?.status === 'ACTIVE'}
              >
                <RefreshCw className="h-3 w-3 mr-1" /> Re-check Readiness
              </Button>

              <Button
                variant="primary"
                size="sm"
                className="flex-1"
                onClick={handleStartSession}
                isLoading={isStartingSession}
                disabled={!readiness?.ready || activeSession?.status === 'ACTIVE'}
              >
                <Play className="h-3 w-3 mr-1" /> Start Session
              </Button>
            </div>
          </div>
        </Card>

        {/* Readiness Checklist Card */}
        <Card title="Runtime Readiness Verification" className="lg:col-span-2">
          {!readiness ? (
            <div className="py-6 text-center text-xs text-slate-500">
              Select an agent and published version to run readiness checks.
            </div>
          ) : (
            <div className="space-y-3 text-xs">
              <div
                className={`rounded-lg p-3 border flex items-center justify-between ${
                  readiness.ready
                    ? 'border-emerald-900/60 bg-emerald-950/30 text-emerald-300'
                    : 'border-rose-900/60 bg-rose-950/30 text-rose-300'
                }`}
              >
                <div className="flex items-center gap-2">
                  {readiness.ready ? (
                    <CheckCircle className="h-4 w-4 text-emerald-400" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-rose-400" />
                  )}
                  <span className="font-semibold">
                    {readiness.ready ? 'Passed All Runtime Prerequisites' : 'Readiness Validation Failed'}
                  </span>
                </div>
                <Badge variant={readiness.ready ? 'green' : 'red'}>
                  {readiness.ready ? 'READY TO EXECUTE' : 'BLOCKED'}
                </Badge>
              </div>

              {/* Checklist breakdown */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-2">
                <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2.5">
                  <span className="text-[10px] text-slate-500 block">VERSION STATUS</span>
                  <span className="font-semibold text-emerald-400">PUBLISHED</span>
                </div>
                <div className="rounded border border-[#143c49] bg-[#06141a] p-2.5">
                  <span className="text-[10px] text-slate-500 block">SCHEMA CONTRACT</span>
                  <span className="font-semibold text-[#00df8f]">v1.0 CANONICAL</span>
                </div>
                <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2.5">
                  <span className="text-[10px] text-slate-500 block">PROVIDER STACK</span>
                  <span className="font-semibold text-purple-400">CARTESIA + GEMINI</span>
                </div>
                <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2.5">
                  <span className="text-[10px] text-slate-500 block">VERSION NUMBER</span>
                  <span className="font-mono text-slate-200 font-bold">
                    v{readiness.version_number ?? '1'}
                  </span>
                </div>
              </div>

              {/* Errors & Warnings */}
              {readiness.errors.length > 0 && (
                <div className="space-y-1 pt-1">
                  <span className="text-[10px] font-bold text-rose-400 uppercase">Errors:</span>
                  {readiness.errors.map((e, idx) => (
                    <div key={idx} className="text-rose-300 font-mono text-[11px]">
                      &bull; {e}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* ACTIVE RUNTIME SESSION PANEL */}
      {activeSession && showRuntimeDiagnostics && (
        <div className="space-y-6">
          {/* Session Banner */}
          <div className="rounded-xl border border-purple-900/50 bg-[#0c0e14] p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-950/60 border border-purple-800/40 text-purple-400">
                <Activity className="h-4 w-4 animate-pulse" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-sm text-slate-100">{activeSession.id}</span>
                  <StatusBadge status={activeSession.status} />
                  <span className="text-[10px] font-mono text-slate-400">
                    Pinned Version: {activeSession.agent_version_id}
                  </span>
                </div>
                <span className="text-xs text-slate-400">
                  Started at: {activeSession.started_at ? new Date(activeSession.started_at).toLocaleTimeString() : 'N/A'}
                  {activeSession.ended_at && ` • Ended at: ${new Date(activeSession.ended_at).toLocaleTimeString()}`}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Tab Selector */}
              <div className="flex rounded-lg bg-[#151824] p-1 border border-[#232736]">
                <button
                  onClick={() => {
                    disconnectWebRTC();
                    setActiveTab('stream');
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                    activeTab === 'stream'
                      ? 'bg-purple-600 text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Radio className="h-3 w-3 inline mr-1" />
                  Live Voice (Cartesia + Gemini)
                </button>
                <button
                  onClick={() => {
                    disconnectWebSocket();
                    disconnectWebRTC();
                    setActiveTab('simulate');
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                    activeTab === 'simulate'
                      ? 'bg-purple-600 text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Sparkles className="h-3 w-3 inline mr-1" />
                  Turn Simulator (HTTP)
                </button>
                <button
                  onClick={() => {
                    disconnectWebSocket();
                    setActiveTab('webrtc');
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                    activeTab === 'webrtc'
                      ? 'bg-emerald-600 text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <PhoneCall className="h-3 w-3 inline mr-1" />
                  WebRTC Voice (Opus)
                </button>
              </div>

              {activeSession.status === 'ACTIVE' && (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleEndSession}
                  isLoading={isEndingSession}
                  className="bg-red-600 hover:bg-red-500 text-white font-medium shadow-sm"
                >
                  <PhoneOff className="h-3 w-3 mr-1" /> End Call
                </Button>
              )}
            </div>
          </div>

          {/* MAIN INTERACTION GRID */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* LEFT / CENTER: STREAMING VOICE CONSOLE OR SIMULATOR */}
            <div className="lg:col-span-2 space-y-4">
              {activeTab === 'webrtc' ? (
                /* REALTIME WEBRTC STREAMING CONSOLE */
                <Card
                  title="Realtime Voice Stream (WebRTC + Opus)"
                  subtitle="Ultra-Low Latency UDP PeerConnection with Opus Codec & Native AEC"
                >
                  <div className="space-y-4 text-xs">
                    {/* WebRTC Audio Status Header */}
                    <div className="flex items-center justify-between p-3 rounded-lg bg-[#10121a] border border-[#1b1f2d]">
                      <div className="flex items-center gap-3">
                        <div
                          className={`h-3 w-3 rounded-full ${
                            webrtcStatus === 'CONNECTED'
                              ? 'bg-emerald-400 animate-ping'
                              : webrtcStatus === 'CONNECTING'
                              ? 'bg-amber-400 animate-pulse'
                              : 'bg-slate-600'
                          }`}
                        />
                        <span className="font-mono text-xs font-semibold text-slate-200">
                          Status: {webrtcStatus}
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {isAssistantSpeaking && (
                          <span className="flex items-center gap-1 rounded bg-purple-950/60 border border-purple-800/40 px-2 py-0.5 text-[11px] text-purple-300">
                            <Volume2 className="h-3 w-3 animate-bounce" /> Assistant Speaking
                          </span>
                        )}
                        {webrtcStatus === 'CONNECTED' && (
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={disconnectWebRTC}
                            className="text-slate-400 hover:text-slate-200"
                          >
                            Disconnect
                          </Button>
                        )}
                      </div>
                    </div>

                    {webrtcError && (
                      <div className="rounded bg-rose-950/30 border border-rose-900/60 p-2.5 text-xs text-rose-300">
                        {webrtcError}
                      </div>
                    )}

                    {/* WebRTC Call Controls */}
                    <div className="flex flex-col gap-3.5 p-4 rounded-xl bg-[#0c0e14] border border-[#1b1f2d]">
                      <div className="flex flex-wrap items-center gap-3">
                        {webrtcStatus !== 'CONNECTED' ? (
                          <Button
                            variant="primary"
                            size="md"
                            className="bg-emerald-600 hover:bg-emerald-500 font-semibold px-5 py-2.5 shadow-md shadow-emerald-950/50"
                            onClick={connectWebRTC}
                            disabled={activeSession.status !== 'ACTIVE' || webrtcStatus === 'CONNECTING'}
                            isLoading={webrtcStatus === 'CONNECTING'}
                          >
                            <PhoneCall className="h-4 w-4 mr-2 shrink-0 inline" />
                            <span className="whitespace-nowrap">Start WebRTC Voice Call (Opus / UDP)</span>
                          </Button>
                        ) : (
                          <Button
                            variant="danger"
                            size="md"
                            className="font-semibold px-5 py-2.5 shadow-md shadow-red-950/50 animate-pulse"
                            onClick={disconnectWebRTC}
                          >
                            <PhoneOff className="h-4 w-4 mr-2 shrink-0 inline" />
                            <span className="whitespace-nowrap">Hang Up / End WebRTC Call</span>
                          </Button>
                        )}

                        {/* Barge-in / Interruption Button */}
                        <Button
                          variant="secondary"
                          size="md"
                          onClick={handleWebRTCBargeIn}
                          disabled={!isAssistantSpeaking}
                          className={`px-4 py-2.5 ${
                            isAssistantSpeaking
                              ? 'border-rose-800 bg-rose-950/40 text-rose-300 hover:bg-rose-900/50 font-medium'
                              : 'opacity-40 cursor-not-allowed text-slate-500'
                          }`}
                        >
                          <Hand className="h-4 w-4 mr-2 shrink-0 inline text-rose-400" />
                          <span className="whitespace-nowrap">Barge-in / Interrupt</span>
                        </Button>

                        <div className="ml-auto hidden sm:flex items-center gap-2 text-[11px] text-slate-400 font-mono bg-[#10131d] px-2.5 py-1.5 rounded-md border border-[#1d2232]">
                          <Radio className="h-3 w-3 text-emerald-400 animate-pulse" />
                          <span>Opus UDP • Low-Latency</span>
                        </div>
                      </div>

                      <div className="text-[11px] text-slate-400 bg-[#10131d] px-3.5 py-2 rounded-lg border border-[#1b1f2d] flex items-center gap-2">
                        <Sparkles className="h-3.5 w-3.5 text-indigo-400 shrink-0" />
                        <span>
                          {webrtcStatus === 'CONNECTED'
                            ? '🎙️ WebRTC call active via Opus/UDP. Speak naturally into your microphone—audio streams continuously with native echo cancellation.'
                            : 'Click Start WebRTC Voice Call to open a peer-to-peer UDP audio stream.'}
                        </span>
                      </div>
                    </div>

                    {/* Live Transcript / Dialogue View */}
                    <div className="space-y-2">
                      <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                        Live Conversation Stream
                      </div>
                      <div className="min-h-[180px] max-h-[320px] overflow-y-auto rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-2">
                        {liveChat.length === 0 && !partialTranscript ? (
                          <div className="py-12 text-center text-xs text-slate-600">
                            Connect WebRTC audio and speak into the microphone to converse in real time.
                          </div>
                        ) : (
                          <>
                            {liveChat.map((msg) => (
                              <div
                                key={msg.id}
                                className={`flex flex-col ${
                                  msg.sender === 'caller' ? 'items-end' : 'items-start'
                                }`}
                              >
                                <div className="text-[10px] text-slate-500 mb-0.5 flex items-center gap-1">
                                  <span>{msg.sender === 'caller' ? 'Caller' : 'AI Employee (Cartesia)'}</span>
                                  <span>{msg.time}</span>
                                  {msg.interrupted && (
                                    <span className="text-rose-400 font-medium">[Interrupted]</span>
                                  )}
                                </div>
                                <div
                                  className={`rounded-lg px-3 py-2 text-xs max-w-[85%] ${
                                    msg.sender === 'caller'
                                      ? 'bg-emerald-950/40 border border-emerald-800/40 text-emerald-200'
                                      : 'bg-[#151824] border border-[#232736] text-slate-100'
                                  }`}
                                >
                                  {msg.text}
                                </div>
                              </div>
                            ))}

                            {/* Streaming Partial Transcript */}
                            {partialTranscript && (
                              <div className="flex flex-col items-end">
                                <div className="text-[10px] text-emerald-400/70 mb-0.5 flex items-center gap-1 font-mono">
                                  <Radio className="h-3 w-3 animate-pulse" /> Caller Speaking (Streaming STT)...
                                </div>
                                <div className="rounded-lg px-3 py-2 text-xs max-w-[85%] bg-emerald-950/20 border border-emerald-800/20 text-emerald-300/80 italic">
                                  {partialTranscript}
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>

                      {/* Monotonic Latency Metrics Bar */}
                      {latencyMetrics && (
                        <div className="pt-2">
                          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                            Realtime Turn Latency Metrics (Monotonic)
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            <div className="rounded border border-[#143c49] bg-[#06141a] p-2">
                              <span className="text-[10px] text-slate-500 block">STT Turn Final</span>
                              <span className="font-mono text-xs font-bold text-[#00df8f]">
                                {latencyMetrics.stt_ms !== undefined ? `${latencyMetrics.stt_ms} ms` : '--'}
                              </span>
                            </div>
                            <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2">
                              <span className="text-[10px] text-slate-500 block">Gemini LLM</span>
                              <span className="font-mono text-xs font-bold text-amber-400">
                                {latencyMetrics.llm_ms !== undefined ? `${latencyMetrics.llm_ms} ms` : '--'}
                              </span>
                            </div>
                            <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2">
                              <span className="text-[10px] text-slate-500 block">TTS (TTFB)</span>
                              <span className="font-mono text-xs font-bold text-purple-400">
                                {latencyMetrics.tts_ttfb_ms !== undefined ? `${latencyMetrics.tts_ttfb_ms} ms` : '--'}
                              </span>
                            </div>
                            <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2">
                              <span className="text-[10px] text-slate-500 block">Round-Trip Total</span>
                              <span className="font-mono text-xs font-bold text-emerald-400">
                                {latencyMetrics.round_trip_ms != null ? `${latencyMetrics.round_trip_ms} ms` : '--'}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              ) : activeTab === 'stream' ? (
                /* REALTIME VOICE WEBSOCKET STREAMING CONSOLE */
                <Card
                  title="Realtime Voice Stream (Cartesia + Gemini)"
                  subtitle="PCM 16-bit 16kHz Full-Duplex Audio Transport"
                >
                  <div className="space-y-4 text-xs">
                    {/* Audio Status Header */}
                    <div className="flex items-center justify-between p-3 rounded-lg bg-[#10121a] border border-[#1b1f2d]">
                      <div className="flex items-center gap-3">
                        <div
                          className={`h-3 w-3 rounded-full ${
                            wsStatus === 'STREAMING'
                              ? 'bg-emerald-400 animate-ping'
                              : wsStatus === 'CONNECTED'
                              ? 'bg-blue-400'
                              : wsStatus === 'CONNECTING'
                              ? 'bg-amber-400 animate-pulse'
                              : 'bg-slate-600'
                          }`}
                        />
                        <span className="font-mono text-xs font-semibold text-slate-200">
                          Status: {wsStatus}
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {isAssistantSpeaking && (
                          <span className="flex items-center gap-1 rounded bg-purple-950/60 border border-purple-800/40 px-2 py-0.5 text-[11px] text-purple-300">
                            <Volume2 className="h-3 w-3 animate-bounce" /> Assistant Speaking
                          </span>
                        )}

                        {wsStatus === 'DISCONNECTED' ? (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={connectWebSocket}
                            disabled={activeSession.status !== 'ACTIVE'}
                          >
                            <Radio className="h-3 w-3 mr-1" /> Connect Audio WebSocket
                          </Button>
                        ) : (
                          <Button variant="secondary" size="sm" onClick={disconnectWebSocket}>
                            Disconnect
                          </Button>
                        )}
                      </div>
                    </div>

                    {wsError && (
                      <div className="rounded bg-rose-950/30 border border-rose-900/60 p-2.5 text-xs text-rose-300">
                        {wsError}
                      </div>
                    )}

                    {/* Microphone & Barge-in Controls */}
                    <div className="flex flex-col gap-3.5 p-4 rounded-xl bg-[#0c0e14] border border-[#1b1f2d]">
                      <div className="flex flex-wrap items-center gap-3">
                        {!isRecording ? (
                          <Button
                            variant="primary"
                            size="md"
                            className="bg-emerald-600 hover:bg-emerald-500 font-semibold px-5 py-2.5 shadow-md shadow-emerald-950/50"
                            onClick={startMicrophone}
                            disabled={activeSession.status !== 'ACTIVE'}
                          >
                            <Mic className="h-4 w-4 mr-2 shrink-0 inline" />
                            <span className="whitespace-nowrap">Start Talking (Microphone)</span>
                          </Button>
                        ) : (
                          <Button
                            variant="danger"
                            size="md"
                            className="font-semibold px-5 py-2.5 shadow-md shadow-red-950/50 animate-pulse"
                            onClick={stopMicrophone}
                          >
                            <MicOff className="h-4 w-4 mr-2 shrink-0 inline" />
                            <span className="whitespace-nowrap">Finish Speaking (Send Turn)</span>
                          </Button>
                        )}

                        {/* Barge-in / Interruption Button */}
                        <Button
                          variant="secondary"
                          size="md"
                          onClick={handleBargeIn}
                          disabled={!isAssistantSpeaking}
                          className={`px-4 py-2.5 ${
                            isAssistantSpeaking
                              ? 'border-rose-800 bg-rose-950/40 text-rose-300 hover:bg-rose-900/50 font-medium'
                              : 'opacity-40 cursor-not-allowed text-slate-500'
                          }`}
                        >
                          <Hand className="h-4 w-4 mr-2 shrink-0 inline text-rose-400" />
                          <span className="whitespace-nowrap">Barge-in / Interrupt</span>
                        </Button>

                        <div className="ml-auto hidden sm:flex items-center gap-2 text-[11px] text-slate-400 font-mono bg-[#10131d] px-2.5 py-1.5 rounded-md border border-[#1d2232]">
                          <Radio className="h-3 w-3 text-purple-400" />
                          <span>PCM 16kHz • WebSocket</span>
                        </div>
                      </div>

                      <div className="text-[11px] text-slate-400 bg-[#10131d] px-3.5 py-2 rounded-lg border border-[#1b1f2d] flex items-center gap-2">
                        <Sparkles className="h-3.5 w-3.5 text-indigo-400 shrink-0" />
                        <span>
                          {isRecording
                            ? '🎙️ Listening... Speak naturally and pause to send automatically, or click above to send immediately.'
                            : 'Click Start Talking to stream your voice in real time.'}
                        </span>
                      </div>
                    </div>

                    {/* Live Transcript / Dialogue View */}
                    <div className="space-y-2">
                      <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                        Live Conversation Stream
                      </div>
                      <div className="min-h-[180px] max-h-[320px] overflow-y-auto rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-2">
                        {liveChat.length === 0 && !partialTranscript ? (
                          <div className="py-12 text-center text-xs text-slate-600">
                            Connect audio and speak into the microphone to converse in real time.
                          </div>
                        ) : (
                          <>
                            {liveChat.map((msg) => (
                              <div
                                key={msg.id}
                                className={`flex flex-col ${
                                  msg.sender === 'caller' ? 'items-end' : 'items-start'
                                }`}
                              >
                                <div
                                  className={`max-w-[85%] rounded-lg p-3 text-xs ${
                                    msg.sender === 'caller'
                                      ? 'bg-[#052b20]/40 border border-[#0a4d39]/50 text-slate-100'
                                      : 'bg-[#091b22] border border-[#143c49] text-slate-200'
                                  }`}
                                >
                                  <div className="flex items-center justify-between gap-4 text-[10px] text-slate-400 mb-1">
                                    <span className="font-semibold uppercase">
                                      {msg.sender === 'caller' ? 'Caller (Browser)' : 'AI Employee (Cartesia)'}
                                    </span>
                                    <span>{msg.time}</span>
                                  </div>
                                  <p className="leading-relaxed">{msg.text}</p>
                                  {msg.interrupted && (
                                    <span className="mt-1 inline-block text-[10px] font-mono text-rose-400">
                                      [Interrupted by Caller]
                                    </span>
                                  )}
                                </div>
                              </div>
                            ))}
                            {partialTranscript && (
                              <div className="flex flex-col items-end">
                                <div className="max-w-[85%] rounded-lg p-3 text-xs bg-[#052b20]/25 border border-[#0a4d39]/40 text-slate-200 italic animate-pulse">
                                  <div className="flex items-center gap-1.5 text-[10px] text-[#00df8f] mb-1">
                                    <Radio className="h-3 w-3 animate-spin" /> Caller Speaking (Streaming STT)...
                                  </div>
                                  <p>{partialTranscript}</p>
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>

                      {/* Realtime Turn Latency Instrumentation Panel */}
                      {latencyMetrics && (
                        <div className="pt-2">
                          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                            Realtime Turn Latency Metrics (Monotonic)
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            <div className="rounded border border-[#143c49] bg-[#06141a] p-2">
                              <span className="text-[10px] text-slate-500 block">STT Turn Final</span>
                              <span className="font-mono text-xs font-bold text-[#00df8f]">
                                {latencyMetrics.stt_ms !== undefined ? `${latencyMetrics.stt_ms} ms` : '--'}
                              </span>
                            </div>
                            <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2">
                              <span className="text-[10px] text-slate-500 block">Gemini LLM</span>
                              <span className="font-mono text-xs font-bold text-amber-400">
                                {latencyMetrics.llm_ms !== undefined ? `${latencyMetrics.llm_ms} ms` : '--'}
                              </span>
                            </div>
                            <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2">
                              <span className="text-[10px] text-slate-500 block">TTS (TTFB)</span>
                              <span className="font-mono text-xs font-bold text-purple-400">
                                {latencyMetrics.tts_ttfb_ms !== undefined ? `${latencyMetrics.tts_ttfb_ms} ms` : '--'}
                              </span>
                            </div>
                            <div className="rounded border border-[#1b1f2d] bg-[#0c0e14] p-2">
                              <span className="text-[10px] text-slate-500 block">Round-Trip Total</span>
                              <span className="font-mono text-xs font-bold text-emerald-400">
                                {latencyMetrics.round_trip_ms != null ? `${latencyMetrics.round_trip_ms} ms` : '--'}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              ) : (
                /* HTTP CHAT CONSOLE */
                <Card title="Runtime Chat" subtitle="Text conversation over the active HTTP runtime session" className="lg:col-span-2">
                  <div className="space-y-4 text-xs">
                    <div ref={runtimeChatScrollRef} className="min-h-[250px] max-h-[360px] overflow-y-auto rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-3">
                      {chatMessages.length === 0 ? (
                        <div className="flex min-h-[220px] items-center justify-center text-center text-xs text-slate-600">
                          Start a chat turn to test the agent&apos;s conversation flow.
                        </div>
                      ) : (
                        chatMessages.map((message) => (
                          <div
                            key={message.id}
                            className={`flex flex-col ${
                              message.sender === 'caller' ? 'items-end' : 'items-start'
                            }`}
                          >
                            <div className="mb-1 flex items-center gap-2 text-[10px] text-slate-500">
                              <span>{message.sender === 'caller' ? 'You' : 'AI Employee'}</span>
                              <span>{message.time}</span>
                            </div>
                            <div
                              className={`max-w-[85%] rounded-lg px-3 py-2 text-xs ${
                                message.sender === 'caller'
                                  ? 'border border-emerald-800/40 bg-emerald-950/40 text-emerald-100'
                                  : 'border border-[#232736] bg-[#151824] text-slate-100'
                              }`}
                            >
                              <StreamingText message={message} />
                            </div>
                          </div>
                        ))
                      )}
                      {isSimulatingTurn && !chatMessages.some((m) => m.streaming) && (
                        <div className="flex items-center gap-2 text-[11px] text-purple-300">
                          <span className="h-2 w-2 animate-pulse rounded-full bg-purple-400" />
                          AI Employee is thinking...
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-300">
                        Message the agent
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          className="flex-1 rounded bg-[#10121a] border border-[#232736] p-2 text-xs text-slate-100 placeholder-slate-500"
                          value={userInput}
                          onChange={(e) => setUserInput(e.target.value)}
                          placeholder="Say something to the agent..."
                          disabled={activeSession.status !== 'ACTIVE'}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSimulateTurn();
                          }}
                        />
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={handleSimulateTurn}
                          isLoading={isSimulatingTurn}
                          disabled={activeSession.status !== 'ACTIVE' || !userInput.trim()}
                        >
                          <Send className="h-3 w-3 mr-1" /> Send
                        </Button>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
                      <span>Quick prompts:</span>
                      {[
                        'I want to check doctor availability for an appointment',
                        'What are your operating hours?',
                        'Please schedule me for tomorrow morning',
                      ].map((preset, i) => (
                        <button
                          key={i}
                          onClick={() => setUserInput(preset)}
                          className="rounded bg-[#0c222b] border border-[#143c49] px-2 py-0.5 text-slate-300 hover:text-[#00df8f] transition-colors"
                          disabled={activeSession.status !== 'ACTIVE'}
                        >
                          "{preset}"
                        </button>
                      ))}
                    </div>

                    {lastTurnResult && (
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[#102d38] pt-3 text-[10px] text-slate-500">
                        <span>Last turn processed</span>
                        <span className="text-emerald-400">{lastTurnResult.tool_calls_executed} tool call(s)</span>
                        <span>Audio: {lastTurnResult.audio_duration_seconds}s</span>
                      </div>
                    )}
                  </div>
                </Card>
              )}
            </div>

            {/* RIGHT COLUMN: LIVE USAGE METRICS & ARCHITECTURE */}
            <div className="space-y-4">
              <Card title="Live Usage Metrics">
                <div className="space-y-3 text-xs">
                  <div className="flex justify-between items-center p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">STT Duration</span>
                    <span className="font-mono font-bold text-[#00df8f]">
                      {activeSession.usage.stt_seconds ?? 0}s
                    </span>
                  </div>

                  <div className="flex justify-between items-center p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">TTS Audio Duration</span>
                    <span className="font-mono font-bold text-purple-400">
                      {activeSession.usage.tts_seconds ?? 0}s
                    </span>
                  </div>

                  <div className="flex justify-between items-center p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">LLM Input Tokens</span>
                    <span className="font-mono font-bold text-slate-200">
                      {activeSession.usage.llm_input_tokens ?? 0}
                    </span>
                  </div>

                  <div className="flex justify-between items-center p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">LLM Output Tokens</span>
                    <span className="font-mono font-bold text-slate-200">
                      {activeSession.usage.llm_output_tokens ?? 0}
                    </span>
                  </div>

                  <div className="flex justify-between items-center p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">Total Session Duration</span>
                    <span className="font-mono font-bold text-emerald-400">
                      {activeSession.usage.session_duration_seconds ?? 0}s
                    </span>
                  </div>
                </div>
              </Card>

              {/* Provider Architecture Summary Card */}
              <Card title="Provider Architecture">
                <div className="space-y-2 text-[11px]">
                  <div className="flex items-center justify-between p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">STT Provider:</span>
                    <span className="font-mono font-semibold text-purple-400">Cartesia (Ink-2)</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded bg-[#06141a] border border-[#143c49]">
                    <span className="text-slate-400">LLM Provider:</span>
                    <span className="font-mono font-semibold text-[#00df8f]">Gemini 3.8 Flash</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded bg-[#0c0e14] border border-[#1b1f2d]">
                    <span className="text-slate-400">TTS Provider:</span>
                    <span className="font-mono font-semibold text-emerald-400">Cartesia (Sonic-2)</span>
                  </div>
                  <div className="flex items-center justify-between p-2 rounded bg-[#0c0e14] border border-[#1b1f2d]">
                    <span className="text-slate-400">Audio Protocol:</span>
                    <span className="font-mono font-semibold text-slate-200">
                      {activeTab === 'webrtc'
                        ? 'WebRTC Opus RTP (UDP)'
                        : activeTab === 'stream'
                        ? 'PCM 16k Mono (WebSocket)'
                        : 'JSON Turn (HTTP)'}
                    </span>
                  </div>
                </div>
              </Card>
            </div>
          </div>

          {/* CHRONOLOGICAL EVENT TIMELINE STREAM */}
          <Card
            title={`Immutable Runtime Event Stream (${events.length})`}
            subtitle="Real-time timeline persisted into runtime_events table"
          >
            <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
              {events.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">No events recorded yet.</div>
              ) : (
                events.map((evt) => (
                  <div
                    key={evt.id}
                    className="flex items-start justify-between rounded border border-[#1b1f2d] bg-[#0c0e14] p-2.5 text-xs font-mono"
                  >
                    <div className="flex items-start gap-2.5">
                      <span className="text-slate-500 text-[11px] shrink-0">
                        {new Date(evt.timestamp).toLocaleTimeString()}
                      </span>
                      <div>
                        <div className="flex items-center gap-2">
                          <span
                            className={`font-semibold ${
                              evt.event_type.startsWith('USER')
                                ? 'text-[#00df8f]'
                                : evt.event_type.startsWith('LLM')
                                ? 'text-purple-400'
                                : evt.event_type.startsWith('TOOL')
                                ? 'text-amber-400'
                                : evt.event_type.startsWith('TTS')
                                ? 'text-emerald-400'
                                : evt.event_type.startsWith('AUDIO')
                                ? 'text-cyan-400'
                                : evt.event_type.includes('INTERRUPTED')
                                ? 'text-rose-400'
                                : 'text-slate-200'
                            }`}
                          >
                            {evt.event_type}
                          </span>
                          <span className="text-[10px] text-slate-600">{evt.id}</span>
                        </div>
                        {evt.payload && Object.keys(evt.payload).length > 0 && (
                          <div className="mt-1 text-[11px] text-slate-400 font-sans">
                            {JSON.stringify(evt.payload)}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};
