import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DollarSign, Clock, PhoneCall, FlaskConical, Info, ArrowUpRight } from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { request } from '../services/api';

interface MockAnalytics {
  label: string;
  calls: { total: number; completed: number; failed: number };
  duration_seconds: number;
  usage: {
    stt_seconds: number;
    tts_seconds: number;
    llm_input_tokens: number;
    llm_output_tokens: number;
  };
  cost: { stt_usd: number; tts_usd: number; llm_usd: number; total_usd: number };
  billing_excluded: boolean;
}

export const UsagePage: React.FC = () => {
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState<MockAnalytics | null>(null);

  useEffect(() => {
    request<MockAnalytics>('/mock/analytics').then(setAnalytics).catch(() => setAnalytics(null));
  }, []);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <DollarSign className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">Usage &amp; Telemetry Costs</h1>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Multi-tenant resource attribution, provider billing reconciliation, and carrier cost reporting.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate('/calls')}
            leftIcon={<PhoneCall className="h-3.5 w-3.5" />}
          >
            Inspect Calls Audit Log
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => navigate('/agents')}
            leftIcon={<FlaskConical className="h-3.5 w-3.5" />}
          >
            Live Turn Telemetry
          </Button>
        </div>
      </div>

      {/* Professional Internal Notice */}
      <div className="rounded-xl border border-[#143c49] bg-[#091b22] p-6 shadow-xl">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#00df8f]/10 border border-[#00df8f]/20 text-[#00df8f] shrink-0">
            <Info className="h-5 w-5" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-slate-100">Operational Module Roadmap Notice</h2>
              <Badge variant="blue" size="sm">Phase 4 Scheduled</Badge>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed max-w-3xl">
              Aggregate monthly billing reconciliation and client invoice generation are scheduled for Phase 4.
              In accordance with Choranta operational policies, no simulated or placeholder financial transactions are generated.
            </p>
            <p className="text-xs text-slate-400 leading-relaxed max-w-3xl">
              Per-call token counts, streaming duration, and turn latencies are continuously recorded in real-time in the backend database. You can inspect live granular metrics immediately in the modules below.
            </p>
          </div>
        </div>
      </div>

      {/* Architectural Telemetry Tracking Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card
          title="Voice Stream Seconds"
          subtitle="Simulated STT and TTS duration"
        >
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-3 font-mono text-sm text-slate-100">
              <span>STT {analytics?.usage.stt_seconds ?? 0}s</span>
              <span>TTS {analytics?.usage.tts_seconds ?? 0}s</span>
            </div>
            <p className="text-slate-300 leading-relaxed">
              Mock audio usage is tracked separately from provider consumption and is excluded from billing.
            </p>
            <div className="pt-3 border-t border-[#102d38]">
              <button
                onClick={() => navigate('/agents')}
                className="text-[#00df8f] hover:text-[#00f59b] text-xs font-medium inline-flex items-center gap-1"
              >
                Test in an AI Employee <ArrowUpRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </Card>

        <Card
          title="LLM Token Accounting"
          subtitle="Simulated deterministic token accounting"
        >
          <div className="space-y-3 text-xs">
            <div className="font-mono text-sm text-slate-100">
              {((analytics?.usage.llm_input_tokens ?? 0) + (analytics?.usage.llm_output_tokens ?? 0)).toLocaleString()} tokens
            </div>
            <p className="text-slate-300 leading-relaxed">
              Scripted mock responses report simulated tokens and never call Gemini.
            </p>
            <div className="pt-3 border-t border-[#102d38]">
              <button
                onClick={() => navigate('/calls')}
                className="text-[#00df8f] hover:text-[#00f59b] text-xs font-medium inline-flex items-center gap-1"
              >
                Inspect Call Logs <ArrowUpRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </Card>

        <Card
          title="Simulated Cost"
          subtitle="Configurable mock pricing estimate"
        >
          <div className="space-y-3 text-xs">
            <div className="font-mono text-2xl font-bold text-[#00df8f]">
              ${analytics?.cost.total_usd.toFixed(4) ?? '0.0000'}
            </div>
            <p className="text-slate-300 leading-relaxed">
              {analytics?.calls.total ?? 0} simulated calls, {analytics?.calls.completed ?? 0} completed. Excluded from real invoices.
            </p>
            <div className="pt-3 border-t border-[#102d38]">
              <button
                onClick={() => navigate('/telephony')}
                className="text-[#00df8f] hover:text-[#00f59b] text-xs font-medium inline-flex items-center gap-1"
              >
                View Telephony Numbers <ArrowUpRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
