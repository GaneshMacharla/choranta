import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Cpu, ShieldCheck, Zap, Radio, Phone, FlaskConical, CheckCircle2, Lock } from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';

export const ProvidersPage: React.FC = () => {
  const navigate = useNavigate();

  const providers = [
    {
      category: 'Speech-to-Text (STT)',
      provider: 'Cartesia',
      model: 'Sonic Streaming STT',
      protocol: 'WebSocket PCM 16kHz Mono',
      latencyTarget: '< 90 ms',
      envVar: 'CARTESIA_API_KEY',
      status: 'OPERATIONAL',
      features: ['Real-time word timestamps', 'Acoustic voice activity detection', 'Barge-in interruption support'],
    },
    {
      category: 'LLM Reasoning',
      provider: 'Google Gemini',
      model: 'Gemini 3.8 Flash',
      protocol: 'REST / Streaming API',
      latencyTarget: '< 250 ms',
      envVar: 'GEMINI_API_KEY',
      status: 'OPERATIONAL',
      features: ['Structured function calling', 'Canonical agent prompt grounding', 'Low-temperature deterministic dialogue'],
    },
    {
      category: 'Text-to-Speech (TTS)',
      provider: 'Cartesia',
      model: 'Sonic Low-Latency Synthesis',
      protocol: 'Chunked WebSocket Binary Stream',
      latencyTarget: '< 120 ms',
      envVar: 'CARTESIA_API_KEY',
      status: 'OPERATIONAL',
      features: ['Emotion and pacing modulation', '16kHz and 8kHz PCM transcoding', 'Instant packet streaming'],
    },
    {
      category: 'Telephony Carrier',
      provider: 'Exotel',
      model: 'Voicebot Applet (AgentStream)',
      protocol: 'Bidirectional WebSocket Media Streams',
      latencyTarget: '< 40 ms transport',
      envVar: 'EXOTEL_ACCOUNT_SID / API_KEY / API_TOKEN / WEBHOOK_SECRET',
      status: 'OPERATIONAL',
      features: ['ExoPhone routing with E.164 normalization', 'Shared-secret webhook authentication', 'Call recording & PSTN bridge'],
    },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <Cpu className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">AI Providers &amp; Runtime Engine</h1>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Internal configuration status, streaming models, latency targets, and carrier infrastructure.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            size="sm"
            onClick={() => navigate('/agents')}
            leftIcon={<FlaskConical className="h-3.5 w-3.5" />}
          >
            Test an AI Employee
          </Button>
        </div>
      </div>

      {/* Security Banner */}
      <div className="rounded-lg border border-[#143c49] bg-[#091b22] p-4 text-xs flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#052b20] border border-[#0a4d39] text-[#00df8f] shrink-0">
            <Lock className="h-4 w-4" />
          </div>
          <div>
            <span className="font-semibold text-slate-200 block">Strict Credential Isolation</span>
            <span className="text-slate-400">
              Provider API credentials, auth tokens, and telephony keys remain secured server-side in the backend environment. Keys are never exposed or transmitted to the browser client.
            </span>
          </div>
        </div>
        <Badge variant="green" dot size="sm">
          Protected
        </Badge>
      </div>

      {/* Providers Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {providers.map((p) => (
          <Card key={p.category} title={p.category} action={<Badge variant="green" dot>{p.status}</Badge>}>
            <div className="space-y-3.5 text-xs">
              <div className="flex items-center justify-between pb-3 border-b border-[#102d38]">
                <span className="text-slate-400">Provider &bull; Engine</span>
                <span className="font-semibold text-slate-100 font-mono">
                  {p.provider} &bull; {p.model}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-slate-400">Streaming Protocol</span>
                <span className="font-mono text-slate-300">{p.protocol}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-slate-400">Latency Target</span>
                <span className="font-mono text-[#00df8f] font-semibold">{p.latencyTarget}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-slate-400">Credential Key Vault</span>
                <span className="font-mono text-xs text-slate-400 bg-[#06141a] px-2 py-0.5 rounded border border-[#153945]">
                  {p.envVar} &bull; <span className="text-[#00df8f]">••••••••</span>
                </span>
              </div>

              <div className="pt-2">
                <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1.5">
                  Runtime Capabilities
                </span>
                <ul className="space-y-1">
                  {p.features.map((f, i) => (
                    <li key={i} className="flex items-center gap-1.5 text-slate-300 text-[11px]">
                      <CheckCircle2 className="h-3 w-3 text-[#00df8f] shrink-0" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};
